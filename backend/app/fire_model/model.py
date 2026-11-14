"""
model.py — Arquitectura ConvLSTM para propagación de fuego por chunks y
utilidades de aprendizaje continuo (fine-tuning y "channel surgery").

Entrada : (batch, T, H, W, C)  -> historia de los últimos T pasos de la rejilla
Salida  : (batch, H, W, 1)     -> P(chunk en llamas en t+1), activación sigmoid

Requiere TensorFlow >= 2.16 (Keras 3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import logging
import math
import os

import keras
from keras import layers, ops
import numpy as np

try:
    from . import config
    from .config import ModelConfig
except ImportError:
    import config
    from config import ModelConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nombres de capa estables. La transferencia de pesos se hace POR NOMBRE, así
# que estos nombres forman parte del "contrato" de la arquitectura.
# ---------------------------------------------------------------------------
INPUT_NAME = "chunk_sequence"
OUTPUT_NAME = "fire_probability"


def convlstm_name(i: int) -> str:
    return f"convlstm_{i}"


def bn_name(i: int) -> str:
    return f"bn_{i}"


def head_name(i: int) -> str:
    return f"head_conv_{i}"


# ===========================================================================
# 1. Arquitectura (Algoritmo CATA)
# ===========================================================================
def build_cata_model(cfg: ModelConfig | None = None) -> keras.Model:
    """Construye el modelo del algoritmo CATA (ConvLSTM) parametrizado por `cfg`.

    Topología:
        Input(T,H,W,C)
          -> [ConvLSTM2D -> BatchNorm] x len(convlstm_filters)
             (todas devuelven secuencias excepto la última, que colapsa T)
          -> [Conv2D 3x3 ReLU] x len(head_filters)
          -> Conv2D 1x1 sigmoid  ==> (H, W, 1)

    `padding="same"` en todo el modelo: la resolución espacial se conserva y
    cada celda de salida se alinea 1:1 con su chunk de entrada.
    """
    cfg = cfg or ModelConfig()
    reg = keras.regularizers.L2(cfg.l2_reg) if cfg.l2_reg > 0 else None

    inputs = keras.Input(shape=cfg.input_shape, name=INPUT_NAME)
    x = inputs

    n_blocks = len(cfg.convlstm_filters)
    for i, filters in enumerate(cfg.convlstm_filters):
        is_last = i == n_blocks - 1
        x = layers.ConvLSTM2D(
            filters=filters,
            kernel_size=cfg.kernel_size,
            padding="same",
            return_sequences=not is_last,
            dropout=cfg.dropout,
            recurrent_dropout=cfg.recurrent_dropout,
            kernel_regularizer=reg,
            name=convlstm_name(i),
        )(x)
        x = layers.BatchNormalization(momentum=config.BN_MOMENTUM, name=bn_name(i))(x)

    for j, filters in enumerate(cfg.head_filters):
        x = layers.Conv2D(
            filters,
            kernel_size=3,
            padding="same",
            activation="relu",
            kernel_regularizer=reg,
            name=head_name(j),
        )(x)

    # Bias inicial = logit(prior) -> la red arranca prediciendo ~prior en todas
    # las celdas en lugar de 0.5 (evita un primer gradiente enorme por el
    # desbalance fuego/no-fuego).
    prior = cfg.output_bias_prior
    outputs = layers.Conv2D(
        1,
        kernel_size=1,
        activation="sigmoid",
        bias_initializer=keras.initializers.Constant(math.log(prior / (1.0 - prior))),
        dtype="float32",  # salida estable incluso con mixed precision
        name=OUTPUT_NAME,
    )(x)

    return keras.Model(inputs, outputs, name=f"cata_c{cfg.num_channels}")


# Alias de compatibilidad
build_fire_model = build_cata_model


def extract_model_config(model: keras.Model) -> ModelConfig:
    """Reconstruye el `ModelConfig` de un modelo creado con `build_fire_model`.

    Permite re-instanciar la misma arquitectura (p. ej. con más canales) a
    partir únicamente de un archivo `.keras`/`.h5`, sin metadatos externos.
    """
    in_shape = model.input_shape  # (None, T, H, W, C)
    if len(in_shape) != 5:
        raise ValueError(f"Se esperaba entrada 5D (B,T,H,W,C), recibido {in_shape}")
    _, t, h, w, c = in_shape

    lstm_layers = sorted(
        (lyr for lyr in model.layers if lyr.name.startswith("convlstm_")),
        key=lambda lyr: int(lyr.name.rsplit("_", 1)[1]),
    )
    head_layers = sorted(
        (lyr for lyr in model.layers if lyr.name.startswith("head_conv_")),
        key=lambda lyr: int(lyr.name.rsplit("_", 1)[1]),
    )
    if not lstm_layers:
        raise ValueError(
            "El modelo no contiene capas 'convlstm_*'; ¿fue creado con build_fire_model?"
        )

    first = lstm_layers[0].get_config()
    kernel = first["kernel_size"]
    kernel = int(kernel[0] if isinstance(kernel, (list, tuple)) else kernel)

    reg_cfg = first.get("kernel_regularizer") or {}
    l2 = float((reg_cfg.get("config") or {}).get("l2", 0.0)) if isinstance(reg_cfg, dict) else 0.0

    return ModelConfig(
        num_channels=int(c),
        time_steps=int(t),
        height=int(h),
        width=int(w),
        convlstm_filters=tuple(int(lyr.get_config()["filters"]) for lyr in lstm_layers),
        kernel_size=kernel,
        head_filters=tuple(int(lyr.get_config()["filters"]) for lyr in head_layers),
        dropout=float(first.get("dropout", 0.0)),
        recurrent_dropout=float(first.get("recurrent_dropout", 0.0)),
        l2_reg=l2,
    )


# ===========================================================================
# 2. Pérdida, métricas y compilación
# ===========================================================================
@keras.saving.register_keras_serializable(package="cataclismo")
class BCEDiceLoss(keras.losses.Loss):
    """(1-w)·BCE ponderada + w·SoftDice.

    - La BCE con `pos_weight` > 1 penaliza más los falsos negativos (no avisar
      de fuego es más grave que una falsa alarma para un sistema de evacuación).
    - El término Dice optimiza el solapamiento del frente de fuego y es robusto
      al fuerte desbalance (la mayoría de los chunks no arden).
    """

    def __init__(
        self,
        dice_weight: float = config.DICE_WEIGHT,
        pos_weight: float = config.POS_WEIGHT,
        smooth: float = 1.0,
        name: str = "bce_dice",
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        self.dice_weight = float(dice_weight)
        self.pos_weight = float(pos_weight)
        self.smooth = float(smooth)

    def call(self, y_true, y_pred):
        y_true = ops.cast(y_true, y_pred.dtype)
        eps = keras.config.epsilon()
        p = ops.clip(y_pred, eps, 1.0 - eps)

        bce = -(self.pos_weight * y_true * ops.log(p) + (1.0 - y_true) * ops.log(1.0 - p))
        bce = ops.mean(bce, axis=(1, 2, 3))

        inter = ops.sum(y_true * y_pred, axis=(1, 2, 3))
        denom = ops.sum(y_true, axis=(1, 2, 3)) + ops.sum(y_pred, axis=(1, 2, 3))
        dice = 1.0 - (2.0 * inter + self.smooth) / (denom + self.smooth)

        return (1.0 - self.dice_weight) * bce + self.dice_weight * dice

    def get_config(self) -> dict:
        base = super().get_config()
        base.update(dice_weight=self.dice_weight, pos_weight=self.pos_weight, smooth=self.smooth)
        return base


def default_metrics(threshold: float = config.PREDICTION_THRESHOLD) -> list[keras.metrics.Metric]:
    return [
        keras.metrics.AUC(curve="PR", name="pr_auc"),
        keras.metrics.Precision(thresholds=threshold, name="precision"),
        keras.metrics.Recall(thresholds=threshold, name="recall"),
        keras.metrics.BinaryIoU(target_class_ids=[1], threshold=threshold, name="fire_iou"),
    ]


def compile_model(model: keras.Model, learning_rate: float = config.LEARNING_RATE) -> keras.Model:
    """(Re)compila el modelo. Llamar siempre tras cambiar `layer.trainable`."""
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate, clipnorm=config.CLIPNORM),
        loss=BCEDiceLoss(),
        metrics=default_metrics(),
    )
    return model


def create_cata_model(
    cfg: ModelConfig | None = None,
    learning_rate: float = config.LEARNING_RATE,
) -> keras.Model:
    """Atajo: construir + compilar un modelo CATA nuevo."""
    return compile_model(build_cata_model(cfg), learning_rate)


def load_cata_model(
    path: str,
    learning_rate: float | None = None,
    compile_model_flag: bool = True,
) -> keras.Model:
    """Carga un `.keras` o `.h5` del algoritmo CATA y lo recompila con un optimizador nuevo.

    Se carga con `compile=False` a propósito: en fine-tuning queremos un LR
    distinto y no arrastrar el estado del optimizador anterior. Así además la
    carga no depende de que los objetos de pérdida/métrica sean serializables.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe el modelo: {path}")
    model = keras.models.load_model(path, compile=False)
    if compile_model_flag:
        compile_model(model, learning_rate if learning_rate is not None else config.FINETUNE_LR)
    return model


# Aliases de compatibilidad
create_model = create_cata_model
load_fire_model = load_cata_model


# ===========================================================================
# 3. Channel surgery (expansión de canales de entrada)
# ===========================================================================
_SUPPORTED_INITS = ("zeros", "glorot_uniform", "he_normal")


def _init_new_slice(
    full_shape: Sequence[int],
    old_c: int,
    init: str,
    seed: int | None,
) -> np.ndarray:
    """Pesos para los canales nuevos [old_c:] de un kernel (kh, kw, C_in, C_out).

    Para Glorot/He se muestrea el kernel COMPLETO y se recorta el slice nuevo,
    de modo que la escala respete el fan-in real del kernel expandido.
    """
    if init == "zeros":
        shape = list(full_shape)
        shape[-2] = full_shape[-2] - old_c
        return np.zeros(shape, dtype=np.float32)
    initializer_cls = {
        "glorot_uniform": keras.initializers.GlorotUniform,
        "he_normal": keras.initializers.HeNormal,
    }[init]
    initializer = initializer_cls(seed=seed)
    full = keras.ops.convert_to_numpy(initializer(tuple(full_shape), dtype="float32"))
    return full[..., old_c:, :].astype(np.float32)


def _is_input_channel_expansion(old_shape, new_shape) -> bool:
    """True si sólo difiere el eje de canales de entrada (axis=-2) y crece."""
    if len(old_shape) != len(new_shape) or len(new_shape) < 2:
        return False
    diff = [i for i, (a, b) in enumerate(zip(old_shape, new_shape, strict=False)) if a != b]
    return diff == [len(new_shape) - 2] and new_shape[-2] > old_shape[-2]


def transfer_weights(
    old_model: keras.Model,
    new_model: keras.Model,
    new_channel_init: str = "zeros",
    seed: int | None = config.SEED,
) -> dict[str, str]:
    """Copia pesos capa a capa (emparejadas por nombre) de `old_model` a `new_model`.

    - Tensores de shape idéntica -> copia directa (ConvLSTM recurrentes, BN,
      cabeza Conv2D, salida...).
    - Kernel de entrada cuyo único cambio es el eje C_in -> se copian los
      canales antiguos y se inicializan los nuevos con `new_channel_init`.
    - Cualquier otra discrepancia -> error explícito (nunca se ignora en
      silencio).

    Devuelve un informe {nombre_capa: acción}.
    """
    if new_channel_init not in _SUPPORTED_INITS:
        raise ValueError(f"new_channel_init debe ser uno de {_SUPPORTED_INITS}")

    old_layers = {lyr.name: lyr for lyr in old_model.layers}
    report: dict[str, str] = {}

    for new_layer in new_model.layers:
        new_weights = new_layer.get_weights()
        if not new_weights:
            continue
        old_layer = old_layers.get(new_layer.name)
        if old_layer is None:
            report[new_layer.name] = "nueva (sin equivalente, se mantiene inicialización)"
            continue

        old_weights = old_layer.get_weights()
        if len(old_weights) != len(new_weights):
            raise ValueError(
                f"Capa '{new_layer.name}': nº de tensores distinto "
                f"({len(old_weights)} vs {len(new_weights)})"
            )

        merged, action = [], "copiada"
        for idx, (w_old, w_new) in enumerate(zip(old_weights, new_weights, strict=False)):
            if w_old.shape == w_new.shape:
                merged.append(w_old)
            elif _is_input_channel_expansion(w_old.shape, w_new.shape):
                old_c = w_old.shape[-2]
                new_slice = _init_new_slice(w_new.shape, old_c, new_channel_init, seed)
                merged.append(np.concatenate([w_old, new_slice], axis=-2))
                action = (
                    f"surgery: tensor[{idx}] {tuple(w_old.shape)} -> {tuple(w_new.shape)} "
                    f"(canales {old_c}..{w_new.shape[-2] - 1} = {new_channel_init})"
                )
            else:
                raise ValueError(
                    f"Capa '{new_layer.name}' tensor[{idx}]: shapes incompatibles "
                    f"{w_old.shape} -> {w_new.shape}"
                )
        new_layer.set_weights(merged)
        report[new_layer.name] = action

    return report


def expand_model_channels(
    old_model_path: str,
    new_num_channels: int,
    new_channel_init: str = "zeros",
    save_path: str | None = None,
    learning_rate: float = config.EXPAND_LR,
    verify: bool = True,
) -> keras.Model:
    """Crea un modelo con `new_num_channels` canales heredando el entrenamiento base.

    1. Carga el modelo antiguo y deduce su arquitectura (`extract_model_config`).
    2. Instancia la MISMA arquitectura con más canales de entrada.
    3. Copia todos los pesos compatibles. En el kernel de entrada del primer
       ConvLSTM2D, (kh, kw, C_old, 4F) -> (kh, kw, C_new, 4F): los C_old canales
       entrenados se conservan y sólo los nuevos se inicializan.

    Con `new_channel_init="zeros"` (recomendado) el modelo expandido es
    *funcionalmente idéntico* al original en el instante de la expansión.
    Hoy entrenamos con C=1 (`frp_sum_mw`) o los primeros C canales del contrato
    `11_ML_DATA_CONTRACT.md` (`cell_day`: FRP, conteos de observaciones,
    confianza, ratio día/noche, huella, product_mix, etc.), pudiendo expandir
    canales incrementalmente mediante `expand_model_channels` sin perder el
    entrenamiento previo.

    Returns: modelo expandido y compilado (guardado en `save_path` si se indica).
    """
    old_model = keras.models.load_model(old_model_path, compile=False)
    old_cfg = extract_model_config(old_model)

    if new_num_channels <= old_cfg.num_channels:
        raise ValueError(
            f"new_num_channels ({new_num_channels}) debe ser > canales actuales "
            f"({old_cfg.num_channels})"
        )

    new_cfg = replace(old_cfg, num_channels=new_num_channels)
    new_model = build_fire_model(new_cfg)
    report = transfer_weights(old_model, new_model, new_channel_init)

    logger.info(
        "Channel surgery %d -> %d canales %s -> %s",
        old_cfg.num_channels,
        new_num_channels,
        list(old_cfg.channel_names),
        list(new_cfg.channel_names),
    )
    for name, action in report.items():
        logger.info("  %-18s %s", name, action)

    if verify:
        diff = expansion_equivalence_error(old_model, new_model)
        tol = 1e-4
        if new_channel_init == "zeros" and diff > tol:
            raise RuntimeError(f"Expansión no equivalente: max|Δ|={diff:.3e} > {tol}")
        logger.info("Verificación (canales nuevos = 0): max|Δ salida| = %.3e", diff)

    compile_model(new_model, learning_rate)
    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        new_model.save(save_path)
        logger.info("Modelo expandido guardado en %s", save_path)
    return new_model


def expansion_equivalence_error(
    old_model: keras.Model,
    new_model: keras.Model,
    n_samples: int = 2,
    seed: int = 0,
) -> float:
    """max|f_old(x) - f_new([x, 0])| sobre entradas aleatorias.

    Con canales nuevos a cero la salida debe coincidir para cualquier
    inicialización; con init="zeros" coincide incluso con canales nuevos != 0.
    """
    rng = np.random.default_rng(seed)
    _, t, h, w, c_old = old_model.input_shape
    c_new = new_model.input_shape[-1]
    x_old = rng.random((n_samples, t, h, w, c_old), dtype=np.float32)
    x_new = np.concatenate(
        [x_old, np.zeros((n_samples, t, h, w, c_new - c_old), np.float32)], axis=-1
    )
    y_old = old_model.predict(x_old, verbose=0)
    y_new = new_model.predict(x_new, verbose=0)
    return float(np.max(np.abs(y_old - y_new)))


def set_expansion_warmup(model: keras.Model, warmup: bool) -> None:
    """Calentamiento tras channel surgery.

    warmup=True : sólo el primer ConvLSTM2D (el que contiene los pesos de los
                  canales nuevos) es entrenable; el resto queda congelado para
                  que el gradiente ruidoso inicial no destruya lo aprendido.
    warmup=False: todo entrenable de nuevo.
    Recordar recompilar (`compile_model`) después de llamar a esta función.
    """
    first = convlstm_name(0)
    for layer in model.layers:
        layer.trainable = (layer.name == first) if warmup else True


# ===========================================================================
# 4. Inferencia (Algoritmo CATA)
# ===========================================================================
def cata_predict(model: keras.Model, sequence: np.ndarray) -> np.ndarray:
    """Algoritmo CATA: predice la matriz de probabilidad de fuego en t+1.

    sequence: (T, H, W, C) o (B, T, H, W, C).
    Devuelve: (H, W) o (B, H, W) float32 en [0, 1] — la matriz que consume el
    sistema de rutas de evacuación.
    """
    x = np.asarray(sequence, dtype=np.float32)
    single = x.ndim == 4
    if single:
        x = x[None]
    expected = tuple(model.input_shape[1:])
    if x.shape[1:] != expected:
        raise ValueError(f"Entrada {x.shape[1:]} no coincide con el modelo {expected}")
    probs = model.predict(x, verbose=0)[..., 0]
    return probs[0] if single else probs


# Alias de compatibilidad
predict_next_fire = cata_predict
