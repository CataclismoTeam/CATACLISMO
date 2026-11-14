"""
config.py — Configuración central del módulo de predicción de propagación de fuego.

Todos los hiperparámetros viven aquí para que `model.py`, `train.py` y
`export_tflite.py` compartan una única fuente de verdad. Los valores pueden
sobreescribirse desde la CLI de `train.py` sin tocar este archivo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Rejilla espacial y ventana temporal (alineado con 11_ML_DATA_CONTRACT.md)
# Grid ID: ES-LAEA-1K-v1 (EPSG:3035), celdas L0 = 1000 m, grano diario
# ---------------------------------------------------------------------------
GRID_ID: str = "ES-LAEA-1K-v1"
CRS: str = "EPSG:3035"
GRID_LEVEL: int = 0  # Nivel L0 = 1 km (L1=2km, L2=4km, L3=8km)
GRID_SIZE: int = 320  # Sub-grilla N x N celdas (ventana espacial 320km)
CHUNK_SIZE_M: float = 1000.0  # Tamaño de celda L0 en metros (1 km)
TIME_STEPS: int = 5  # T: nº de pasos temporales (días) de entrada

# ---------------------------------------------------------------------------
# Registro ordenado de canales de entrada (100% basado en 11_ML_DATA_CONTRACT.md).
# Todos los canales provienen exclusivamente de `cell_day` (MODIS/VIIRS).
# El canal i del tensor SIEMPRE corresponde a CHANNEL_REGISTRY[i]. Un modelo con
# C canales consume los primeros C nombres. Para añadir más canales del contrato
# (o futuros sensores), usa `expand_model_channels`.
# ---------------------------------------------------------------------------
CHANNEL_REGISTRY: tuple[str, ...] = (
    "frp_sum_mw",  # 0: log1p(frp_sum_mw) / norm, energía radiativa integrada [0, 1]
    "frp_max_mw",  # 1: log1p(frp_max_mw) / norm, pico de FRP en la celda-día [0, 1]
    "frp_mean_mw",  # 2: log1p(frp_mean_mw) / norm, FRP medio por detección [0, 1]
    "frp_p50_mw",  # 3: log1p(frp_p50_mw) / norm, mediana de FRP [0, 1]
    "n_obs",  # 4: log1p(n_obs) / norm, conteo total de detecciones [0, 1]
    "n_high_conf",  # 5: log1p(n_high_conf) / norm, detecciones de alta confianza [0, 1]
    "confidence_rank_max",  # 6: confidence_rank_max / 2.0 (0=low, 0.5=nominal, 1.0=high)
    "n_day_ratio",  # 7: n_day / max(n_obs, 1), fracción de detecciones diurnas [0, 1]
    "n_night_ratio",  # 8: n_night / max(n_obs, 1), fracción de detecciones nocturnas [0, 1]
    "footprint_max_km",  # 9: clip(footprint_max_km / 1.0, 0, 1), huella máxima del píxel [0, 1]
    "n_platforms",  # 10: clip(n_platforms / 3.0, 0, 1), diversidad de plataformas [0, 1]
    "product_mix",  # 11: fracción NRT (0.0=todo SP, 1.0=todo NRT) [0, 1]
    "viirs_obs_share",  # 12: n_obs_viirs / max(n_obs_total, 1), peso del sensor VIIRS [0, 1]
)
NUM_CHANNELS: int = 1  # Base inicial: sólo frp_sum_mw
EXPANDED_NUM_CHANNELS: int = 7  # Expansión por defecto con variables clave de cell_day

# Constantes de normalización logarítmica: log1p(x) / LOG1P_SCALE -> clip [0, 1]
FRP_LOG1P_SCALE: float = 8.0  # log1p(2980 MW) ≈ 8.0
OBS_LOG1P_SCALE: float = 5.0  # log1p(147 obs) ≈ 5.0

# ---------------------------------------------------------------------------
# Arquitectura
# ---------------------------------------------------------------------------
CONVLSTM_FILTERS: tuple[int, ...] = (32, 32)  # Un bloque ConvLSTM2D+BN por elemento
CONVLSTM_KERNEL: int = 3
HEAD_FILTERS: tuple[int, ...] = (16,)  # Capas Conv2D intermedias de la cabeza
DROPOUT: float = 0.0
RECURRENT_DROPOUT: float = 0.0
L2_REG: float = 1e-5
# Momentum de BatchNorm. 0.9 (en vez del 0.99 por defecto de Keras) hace que las
# estadísticas móviles usadas en inferencia converjan en pocas épocas; con
# 0.99 y datasets/entrenamientos incrementales cortos la validación colapsa.
BN_MOMENTUM: float = 0.9
# Probabilidad a priori de fuego por celda: inicializa el bias de salida a
# logit(p) para estabilizar el arranque con clases muy desbalanceadas.
OUTPUT_BIAS_PRIOR: float = 0.02

# ---------------------------------------------------------------------------
# Entrenamiento
# ---------------------------------------------------------------------------
LEARNING_RATE: float = 1e-3  # Desde cero
FINETUNE_LR: float = 3e-4  # Continuar entrenando un checkpoint
EXPAND_WARMUP_LR: float = 1e-3  # Fase de calentamiento tras channel surgery
EXPAND_LR: float = 2e-4  # Ajuste fino completo tras channel surgery
BATCH_SIZE: int = 8
EPOCHS: int = 10
VALIDATION_SPLIT: float = 0.15
EARLY_STOPPING_PATIENCE: int = 5
REDUCE_LR_PATIENCE: int = 2
CLIPNORM: float = 1.0

# Pérdida: (1 - DICE_WEIGHT) * BCE_ponderada + DICE_WEIGHT * SoftDice
DICE_WEIGHT: float = 0.5
POS_WEIGHT: float = 3.0  # Peso extra de los píxeles en llamas en la BCE
PREDICTION_THRESHOLD: float = 0.5

SEED: int = 42

# ---------------------------------------------------------------------------
# Datos sintéticos (sólo para pruebas / smoke tests)
# ---------------------------------------------------------------------------
SYNTH_NUM_SAMPLES: int = 512
SYNTH_EPISODE_EXTRA_STEPS: int = 10  # Pasos simulados adicionales por episodio

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
ALGORITHM_NAME: str = "cata"
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR: str = os.path.join(BASE_DIR, "artifacts")
MODEL_DIR: str = os.path.join(ARTIFACTS_DIR, "models")
LOG_DIR: str = os.path.join(ARTIFACTS_DIR, "logs")
DEFAULT_MODEL_PATH: str = os.path.join(MODEL_DIR, "cata_c1.keras")
DEFAULT_TFLITE_PATH: str = os.path.join(MODEL_DIR, "cata.tflite")


@dataclass(frozen=True)
class ModelConfig:
    """Hiperparámetros que definen UNÍVOCAMENTE una instancia de la arquitectura.

    Es inmutable: para variar algo (p. ej. nº de canales) usar
    `dataclasses.replace(cfg, num_channels=7)`.
    """

    num_channels: int = NUM_CHANNELS
    time_steps: int = TIME_STEPS
    height: int = GRID_SIZE
    width: int = GRID_SIZE
    convlstm_filters: tuple[int, ...] = field(default_factory=lambda: CONVLSTM_FILTERS)
    kernel_size: int = CONVLSTM_KERNEL
    head_filters: tuple[int, ...] = field(default_factory=lambda: HEAD_FILTERS)
    dropout: float = DROPOUT
    recurrent_dropout: float = RECURRENT_DROPOUT
    l2_reg: float = L2_REG
    output_bias_prior: float = OUTPUT_BIAS_PRIOR

    def __post_init__(self) -> None:
        if self.num_channels < 1:
            raise ValueError("num_channels debe ser >= 1")
        if self.num_channels > len(CHANNEL_REGISTRY):
            raise ValueError(
                f"num_channels={self.num_channels} excede CHANNEL_REGISTRY "
                f"({len(CHANNEL_REGISTRY)}). Registra el nuevo canal en config.py."
            )
        if self.time_steps < 1 or self.height < 1 or self.width < 1:
            raise ValueError("time_steps, height y width deben ser >= 1")
        if not self.convlstm_filters:
            raise ValueError("Se requiere al menos un bloque ConvLSTM2D")
        if not 0.0 < self.output_bias_prior < 1.0:
            raise ValueError("output_bias_prior debe estar en (0, 1)")

    @property
    def channel_names(self) -> tuple[str, ...]:
        return CHANNEL_REGISTRY[: self.num_channels]

    @property
    def input_shape(self) -> tuple[int, int, int, int]:
        """Shape sin batch: (T, H, W, C)."""
        return (self.time_steps, self.height, self.width, self.num_channels)
