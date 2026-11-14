"""Algoritmo LUCIA — Modelo modular en TensorFlow/Keras para evaluación espacial
de riesgo, coste de evacuación (personas y animales) y detección de zonas libres de peligro.

Arquitectura modular análoga a CATA (`backend/app/cata/model.py`):
  - Entrada: tensor espacial `(H, W, C)` construido a partir del output de CATA
    (`cata_predictions.json`), que incluye el estado de quemado (`SAFE`, `PREDICTED_FIRE`,
    `CONFIRMED_BURNED`, `CONFIRMED_AND_CONTINUES`), probabilidades `t+1`, tiempos de llegada,
    costes base y variables ambientales de VALEN (`meteo`, `rainfall`, `vegetation`).
  - Bloques Conv2D multi-escala (dilated + residual) con `BatchNormalization` y `SpatialDropout2D`
    que capturan el radio de radiación térmica, humo y corredores seguros.
  - Salida `(H, W, 3)` con activación sigmoide:
      * Canal `0`: `human_risk_field` in `[0, 1]` (penalización neuronal de paso para personas).
      * Canal `1`: `animal_risk_field` in `[0, 1]` (penalización neuronal de paso para animales).
      * Canal `2`: `safe_haven_score` in `[0, 1]` (idoneidad de cada celda como **zona libre de peligro**).
  - Soporta **Channel Surgery** (`expand_lucia_channels`) para añadir nuevos canales
    (p. ej. pendiente DEM, red de carreteras OSM, refugios civiles) sin perder pesos entrenados.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import replace

os.environ.setdefault("KERAS_BACKEND", "tensorflow")

import keras
import numpy as np
from keras import layers

from . import config
from .config import LuciaModelConfig

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. Nombres de capas deterministas (clave para channel surgery)
# ===========================================================================
def conv_block_names(idx: int) -> tuple[str, str, str]:
    return (f"lucia_conv_{idx}", f"lucia_bn_{idx}", f"lucia_drop_{idx}")


INPUT_LAYER_NAME = "lucia_spatial_input"
DILATED_CONV_NAME = "lucia_dilated_context"
DILATED_BN_NAME = "lucia_dilated_bn"
HEAD_CONV_NAME = "lucia_head_conv"
OUTPUT_LAYER_NAME = "lucia_routing_fields_out"


# ===========================================================================
# 2. Construcción, compilación y carga del modelo TensorFlow de LUCIA
# ===========================================================================
def build_lucia_model(cfg: LuciaModelConfig = LuciaModelConfig()) -> keras.Model:
    """Construye la red convolucional espacial de LUCIA (sin compilar).

    Entrada: `(B, H, W, C)`
    Salida : `(B, H, W, 3)` -> `[human_risk_field, animal_risk_field, safe_haven_score]`
    """
    if not cfg.conv_filters:
        raise ValueError("conv_filters debe contener al menos un bloque")

    inputs = keras.Input(shape=cfg.input_shape, name=INPUT_LAYER_NAME)
    x = inputs

    for idx, filters in enumerate(cfg.conv_filters):
        c_name, bn_name, drop_name = conv_block_names(idx)
        x = layers.Conv2D(
            filters=filters,
            kernel_size=cfg.kernel_size,
            padding="same",
            activation="relu",
            name=c_name,
        )(x)
        x = layers.BatchNormalization(name=bn_name)(x)
        if cfg.dropout_rate > 0:
            x = layers.SpatialDropout2D(cfg.dropout_rate, name=drop_name)(x)

    # Contexto dilatado (radio 2 celdas = 2 km) para percibir frentes de fuego cercanos
    x_dilated = layers.Conv2D(
        filters=cfg.conv_filters[-1],
        kernel_size=cfg.kernel_size,
        dilation_rate=(2, 2),
        padding="same",
        activation="relu",
        name=DILATED_CONV_NAME,
    )(x)
    x_dilated = layers.BatchNormalization(name=DILATED_BN_NAME)(x_dilated)

    # Fusión residual del contexto local + dilatado
    x = layers.Add(name="lucia_context_residual")([x, x_dilated])

    x = layers.Conv2D(
        filters=24,
        kernel_size=(3, 3),
        padding="same",
        activation="relu",
        name=HEAD_CONV_NAME,
    )(x)

    outputs = layers.Conv2D(
        filters=config.OUTPUT_HEAD_CHANNELS,
        kernel_size=(1, 1),
        padding="same",
        activation="sigmoid",
        dtype="float32",
        name=OUTPUT_LAYER_NAME,
    )(x)

    return keras.Model(
        inputs=inputs,
        outputs=outputs,
        name=f"lucia_router_c{cfg.num_channels}",
    )


def compile_lucia_model(
    model: keras.Model,
    learning_rate: float = config.LEARNING_RATE,
) -> keras.Model:
    """Compila el modelo de LUCIA con pérdida Huber + métricas de precisión espacial."""
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss=keras.losses.Huber(delta=0.15),
        metrics=[
            keras.metrics.MeanAbsoluteError(name="mae"),
            keras.metrics.RootMeanSquaredError(name="rmse"),
        ],
    )
    return model


def create_lucia_model(
    grid_size: int = config.GRID_SIZE,
    num_channels: int = config.DEFAULT_NUM_CHANNELS,
    conv_filters: Sequence[int] = config.CONV_FILTERS,
    kernel_size: tuple[int, int] = config.KERNEL_SIZE,
    dropout_rate: float = config.DROPOUT_RATE,
    learning_rate: float = config.LEARNING_RATE,
) -> keras.Model:
    """Crea y compila un modelo TensorFlow de LUCIA listo para entrenar o inferir."""
    cfg = LuciaModelConfig(
        grid_size=grid_size,
        num_channels=num_channels,
        conv_filters=tuple(conv_filters),
        kernel_size=kernel_size,
        dropout_rate=dropout_rate,
    )
    return compile_lucia_model(build_lucia_model(cfg), learning_rate=learning_rate)


def extract_lucia_model_config(model: keras.Model) -> LuciaModelConfig:
    """Reconstruye `LuciaModelConfig` inspeccionando un `keras.Model` cargado."""
    _, h, w, c = model.input_shape
    if h != w:
        raise ValueError(f"Se esperaba rejilla cuadrada, recibido {h}x{w}")

    conv_layers = [
        lyr
        for lyr in model.layers
        if isinstance(lyr, layers.Conv2D) and lyr.name.startswith("lucia_conv_")
    ]
    conv_layers.sort(key=lambda lyr: int(lyr.name.rsplit("_", 1)[-1]))
    drop_layers = [lyr for lyr in model.layers if isinstance(lyr, layers.SpatialDropout2D)]

    return LuciaModelConfig(
        grid_size=int(h),
        num_channels=int(c),
        conv_filters=tuple(int(lyr.filters) for lyr in conv_layers),
        kernel_size=tuple(conv_layers[0].kernel_size),
        dropout_rate=float(drop_layers[0].rate) if drop_layers else 0.0,
    )


def load_lucia_model(
    path: str = config.DEFAULT_MODEL_PATH,
    compile_model_flag: bool = True,
    learning_rate: float | None = None,
) -> keras.Model:
    """Carga un modelo `.keras` de LUCIA desde disco."""
    model = keras.models.load_model(path, compile=False)
    if compile_model_flag:
        compile_lucia_model(
            model,
            learning_rate if learning_rate is not None else config.FINETUNE_LR,
        )
    return model


# ===========================================================================
# 3. Channel Surgery (expansión modular de canales de entrada)
# ===========================================================================
_SUPPORTED_INITS = ("zeros", "glorot_uniform", "he_normal")


def _init_new_slice(
    full_shape: Sequence[int],
    old_c: int,
    init: str,
    seed: int | None,
) -> np.ndarray:
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
    if len(old_shape) != len(new_shape) or len(new_shape) < 2:
        return False
    diff = [i for i, (a, b) in enumerate(zip(old_shape, new_shape, strict=False)) if a != b]
    return diff == [len(new_shape) - 2] and new_shape[-2] > old_shape[-2]


def transfer_lucia_weights(
    old_model: keras.Model,
    new_model: keras.Model,
    new_channel_init: str = "zeros",
    seed: int | None = config.SEED,
) -> dict[str, str]:
    """Transfiere pesos capa a capa de `old_model` a `new_model` expandiendo canales."""
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
            report[new_layer.name] = "nueva (sin equivalente)"
            continue

        old_weights = old_layer.get_weights()
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


def expand_lucia_channels(
    old_model_path: str,
    new_num_channels: int,
    new_channel_init: str = "zeros",
    save_path: str | None = None,
    learning_rate: float = config.EXPAND_LR,
) -> keras.Model:
    """Expande un modelo de LUCIA a `new_num_channels` conservando los pesos previos."""
    old_model = keras.models.load_model(old_model_path, compile=False)
    old_cfg = extract_lucia_model_config(old_model)

    if new_num_channels <= old_cfg.num_channels:
        raise ValueError(
            f"new_num_channels ({new_num_channels}) debe ser > canales actuales ({old_cfg.num_channels})"
        )

    new_cfg = replace(old_cfg, num_channels=new_num_channels)
    new_model = build_lucia_model(new_cfg)
    transfer_lucia_weights(old_model, new_model, new_channel_init=new_channel_init)
    compile_lucia_model(new_model, learning_rate=learning_rate)

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        new_model.save(save_path)
    return new_model


# ===========================================================================
# 4. Extracción de tensores de entrada desde el output de CATA + Inferencia
# ===========================================================================
def compute_distance_to_hazard(hazard_mask: np.ndarray) -> np.ndarray:
    """Calcula la distancia euclídea exacta (en celdas) desde cada punto al foco más cercano."""
    h, w = hazard_mask.shape
    hazard_pts = np.argwhere(hazard_mask)
    if len(hazard_pts) == 0:
        return np.full((h, w), float(h + w), dtype=np.float32)

    grid_r, grid_c = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    # Vectorizado sobre los puntos de peligro
    dr = grid_r[:, :, None] - hazard_pts[:, 0][None, None, :]
    dc = grid_c[:, :, None] - hazard_pts[:, 1][None, None, :]
    dist = np.sqrt(dr * dr + dc * dc, dtype=np.float32)
    return np.min(dist, axis=-1)


def extract_lucia_features_from_zone(
    zone: dict,
    active_cells_for_zone: Sequence[dict] | None = None,
    safe_fire_threshold: float = config.SAFE_FIRE_THRESHOLD,
    num_channels: int = config.DEFAULT_NUM_CHANNELS,
    road_grids: dict[str, np.ndarray] | None = None,
    elevation_grids: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    """Construye el tensor `(H, W, C)` de LUCIA a partir de una zona de `cata_predictions.json`.

    Integra explícitamente:
      - Zonas sin quemar seguras (`is_safe_unburned`: estado `0` y `prob_t1 < safe_fire_threshold`).
      - Zonas quemándose activamente o que arderán (`is_burning_active`: estado `3='B'` o `1='P'`).
      - Zonas ya quemadas (`is_already_burned`: estado `2='F'`).
      - Probabilidad continua `prob_t1` de CATA, proximidad al fuego y urgencia temporal.
      - Costes base (humano/animal) y variables ambientales de VALEN (`veg_flammability`,
        `meteo_wind_speed`, `meteo_fwi` + `meteo_temp`).
      - Red viaria OSM de VALEN (`road_grids["road_access"]`, canal 12).
      - Elevación y pendiente topográfica Open-Elevation de VALEN (`elevation_norm` canal 13
        y `slope_steepness` canal 14).
    """
    state_2d = np.asarray(zone["state_matrix"], dtype=np.int8)
    probs_2d = np.asarray(zone["fire_probability_grid"], dtype=np.float32)
    arrival_2d = np.asarray(zone["estimated_fire_arrival_hours"], dtype=np.float32)
    human_cost_2d = np.asarray(zone["human_traversal_cost_grid"], dtype=np.float32)
    animal_cost_2d = np.asarray(zone["animal_traversal_cost_grid"], dtype=np.float32)

    h, w = state_2d.shape

    # 1. Máscaras de estados de quemado con threshold seguro al fuego
    is_already_burned = (state_2d == config.QUADRANT_STATE_BURNED_REAL).astype(np.float32)
    is_burning_active = (
        (state_2d == config.QUADRANT_STATE_PERSISTENT)
        | (state_2d == config.QUADRANT_STATE_PREDICTED)
        | (probs_2d >= safe_fire_threshold)
    ).astype(np.float32)
    is_safe_unburned = (
        (state_2d == config.QUADRANT_STATE_SAFE) & (probs_2d < safe_fire_threshold)
    ).astype(np.float32)

    # 2. Proximidad espacial a cualquier foco (quemado o ardiendo)
    hazard_mask = (is_already_burned > 0.5) | (is_burning_active > 0.5)
    dist_to_fire = compute_distance_to_hazard(hazard_mask)
    fire_proximity_risk = np.exp(-dist_to_fire / 3.5).astype(np.float32)

    # 3. Urgencia temporal de llegada del frente
    arrival_urgency = np.clip(1.0 - np.clip(arrival_2d, 0.0, 24.0) / 24.0, 0.0, 1.0).astype(
        np.float32
    )

    # 4. Costes base normalizados a [0, 1]
    human_base_norm = np.clip((human_cost_2d - 1.0) / 3.6, 0.0, 1.0).astype(np.float32)
    animal_base_norm = np.clip((animal_cost_2d - 0.85) / 3.9, 0.0, 1.0).astype(np.float32)

    # 5. Variables ambientales de VALEN por celda (reconstruidas desde active_and_predicted_cells + grids)
    veg_grid = np.clip((human_cost_2d - 1.0 - 2.5 * probs_2d) / 0.7, 0.0, 1.0).astype(np.float32)
    wind_grid = np.clip(
        (animal_cost_2d - 0.85 - 0.3 * veg_grid - 3.0 * probs_2d) / 0.6, 0.0, 1.0
    ).astype(np.float32)
    fwi_temp_grid = np.zeros((h, w), dtype=np.float32)

    if active_cells_for_zone:
        for cell in active_cells_for_zone:
            r = int(cell.get("grid_row", -1))
            c = int(cell.get("grid_col", -1))
            if 0 <= r < h and 0 <= c < w:
                vf = cell.get("valen_features_norm") or {}
                veg_grid[r, c] = float(vf.get("veg_flammability", veg_grid[r, c]))
                wind_grid[r, c] = float(vf.get("meteo_wind_speed", wind_grid[r, c]))
                fwi_temp_grid[r, c] = float(
                    0.6 * vf.get("meteo_fwi", 0.0) + 0.4 * vf.get("meteo_temp", 0.0)
                )

    # 6. Afinidad de salida hacia bordes despejados (lejos del centro del incendio)
    rr, cc = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    dist_to_border = np.minimum(np.minimum(rr, h - 1 - rr), np.minimum(cc, w - 1 - cc)).astype(
        np.float32
    )
    max_border_dist = max(1.0, float(min(h, w) / 2.0))
    border_escape_affinity = (
        (1.0 - dist_to_border / max_border_dist) * is_safe_unburned * (1.0 - fire_proximity_risk)
    ).astype(np.float32)

    road_access = np.zeros((h, w), dtype=np.float32)
    if road_grids is not None and "road_access" in road_grids:
        road_access = np.clip(np.asarray(road_grids["road_access"], dtype=np.float32), 0.0, 1.0)

    elevation_norm = np.zeros((h, w), dtype=np.float32)
    slope_steepness = np.zeros((h, w), dtype=np.float32)
    if elevation_grids is not None:
        if "elevation_norm" in elevation_grids:
            elevation_norm = np.clip(
                np.asarray(elevation_grids["elevation_norm"], dtype=np.float32), 0.0, 1.0
            )
        if "slope_steepness" in elevation_grids:
            slope_steepness = np.clip(
                np.asarray(elevation_grids["slope_steepness"], dtype=np.float32), 0.0, 1.0
            )

    channels = [
        is_safe_unburned,       # 0
        is_burning_active,      # 1
        is_already_burned,      # 2
        probs_2d,               # 3
        fire_proximity_risk,    # 4
        arrival_urgency,        # 5
        human_base_norm,        # 6
        animal_base_norm,       # 7
        veg_grid,               # 8
        wind_grid,              # 9
        fwi_temp_grid,          # 10
        border_escape_affinity, # 11
        road_access,            # 12
        elevation_norm,         # 13
        slope_steepness,        # 14
    ]

    tensor = np.stack(channels, axis=-1).astype(np.float32)
    if num_channels <= tensor.shape[-1]:
        return tensor[..., :num_channels]
    pad = np.zeros((h, w, num_channels - tensor.shape[-1]), dtype=np.float32)
    return np.concatenate([tensor, pad], axis=-1)


def compute_analytic_target_fields(features: np.ndarray) -> np.ndarray:
    """Calcula el campo objetivo de supervisión `(H, W, 3)` a partir de `features (H, W, C)`.

    Se utiliza tanto para entrenar el modelo TensorFlow de LUCIA como de referencia física:
      - Canal 0 (`human_risk_field`): coste/riesgo normalizado `[0, 1]` para personas.
      - Canal 1 (`animal_risk_field`): coste/riesgo normalizado `[0, 1]` para animales.
      - Canal 2 (`safe_haven_score`): idoneidad `[0, 1]` como zona libre de peligro.
    """
    is_safe = features[..., 0]
    is_burning = features[..., 1]
    is_burned = features[..., 2]
    prob_t1 = features[..., 3]
    prox_risk = features[..., 4]
    urgency = features[..., 5]
    human_base = features[..., 6] if features.shape[-1] > 6 else np.zeros_like(is_safe)
    animal_base = features[..., 7] if features.shape[-1] > 7 else np.zeros_like(is_safe)
    veg = features[..., 8] if features.shape[-1] > 8 else np.zeros_like(is_safe)
    wind = features[..., 9] if features.shape[-1] > 9 else np.zeros_like(is_safe)
    border_aff = features[..., 11] if features.shape[-1] > 11 else np.zeros_like(is_safe)
    road = features[..., 12] if features.shape[-1] > 12 else np.zeros_like(is_safe)
    elev_norm = features[..., 13] if features.shape[-1] > 13 else np.zeros_like(is_safe)
    slope = features[..., 14] if features.shape[-1] > 14 else np.zeros_like(is_safe)

    # Efecto chimenea en ladera: laderas empinadas y cotas altas cercanas al fuego aceleran la convección
    chimney_risk = slope * prox_risk + 0.35 * elev_norm * prox_risk

    # Personas: bloqueo total (1.0) en ardiendo/quemado; penaliza proximidad, urgencia, vegetación densa y pendiente.
    # Las carreteras/pistas (OSM) reducen el riesgo: paso rápido, sin combustible y accesibles a rescate.
    human_risk = np.clip(
        0.95 * is_burning
        + 0.88 * is_burned
        + 0.42 * prox_risk
        + 0.33 * prob_t1
        + 0.22 * urgency
        + 0.18 * human_base
        + 0.14 * veg
        + 0.20 * slope
        + 0.15 * chimney_risk
        - 0.18 * road * is_safe,
        0.0,
        1.0,
    )

    # Animales: bloqueo total en ardiendo/quemado; menor penalización por matorral/pendiente moderada pero mayor por viento/humo.
    animal_risk = np.clip(
        0.98 * is_burning
        + 0.90 * is_burned
        + 0.48 * prox_risk
        + 0.38 * prob_t1
        + 0.22 * urgency
        + 0.14 * animal_base
        + 0.20 * wind
        + 0.12 * slope
        + 0.15 * chimney_risk
        - 0.06 * road * is_safe,
        0.0,
        1.0,
    )

    # Zona libre de peligro / Punto de Encuentro (Safe Haven): alta sólo en celdas sin quemar, lejos del fuego,
    # con terreno llano (1 - slope), baja inflamabilidad y acceso por carretera.
    safe_haven = np.clip(
        is_safe
        * (1.0 - prox_risk)
        * (1.0 - np.clip(prob_t1 * 4.0, 0.0, 1.0))
        * (0.42 + 0.22 * border_aff + 0.10 * (1.0 - veg) + 0.14 * road + 0.12 * (1.0 - slope)),
        0.0,
        1.0,
    )

    return np.stack([human_risk, animal_risk, safe_haven], axis=-1).astype(np.float32)


def lucia_predict_fields(
    model: keras.Model,
    features: np.ndarray,
) -> dict[str, np.ndarray]:
    """Ejecuta el modelo TensorFlow de LUCIA sobre `(H, W, C)` o `(B, H, W, C)`.

    Devuelve diccionario con:
      - `human_risk_field`: `(H, W)` float32 en `[0, 1]`
      - `animal_risk_field`: `(H, W)` float32 en `[0, 1]`
      - `safe_haven_score`: `(H, W)` float32 en `[0, 1]`
    """
    x = np.asarray(features, dtype=np.float32)
    single = x.ndim == 3
    if single:
        x = x[None]

    expected_c = int(model.input_shape[-1])
    if x.shape[-1] < expected_c:
        pad = np.zeros((*x.shape[:-1], expected_c - x.shape[-1]), dtype=np.float32)
        x = np.concatenate([x, pad], axis=-1)
    elif x.shape[-1] > expected_c:
        x = x[..., :expected_c]

    preds = model.predict(x, verbose=0)
    if single:
        preds = preds[0]
    return {
        "human_risk_field": preds[..., 0],
        "animal_risk_field": preds[..., 1],
        "safe_haven_score": preds[..., 2],
    }
