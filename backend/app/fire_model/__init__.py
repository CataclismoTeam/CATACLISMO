"""CATA — Algoritmo de predicción de propagación de fuego ConvLSTM.

Se alimenta de los datos validados y enriquecidos por VALEN:
- Cell Day (MODIS/VIIRS)
- Meteo (FWI, velocidad del viento, humedad relativa, temperatura)
- Rainfall (días sin lluvia, racha seca, déficit de precipitación 30d)
- Vegetation (inflamabilidad combinada WorldCover + IFN3)
- Validación VALEN (`valen_score`, descartando falsos positivos `RECHAZA`)

Y exporta las predicciones (`cata_predictions.json`) listas para que el futuro
algoritmo LUCIA calcule las vías de escape de personas y animales.
"""

from .config import (
    ALGORITHM_NAME,
    CELL_DAY_NUM_CHANNELS,
    CHANNEL_REGISTRY,
    DEFAULT_PREDICTIONS_PATH,
    EXPANDED_NUM_CHANNELS,
    NUM_CHANNELS,
    SOURCE_VALIDATION_ALGORITHM,
    TARGET_ROUTING_ALGORITHM,
    VALEN_NUM_CHANNELS,
    ModelConfig,
)
from .model import (
    build_cata_model,
    cata_predict,
    cata_predict_quadrants,
    classify_cata_quadrants,
    create_cata_model,
    expand_model_channels,
    export_cata_predictions,
    export_cata_predictions_for_lucia,
    load_cata_model,
)

__all__ = [
    "ALGORITHM_NAME",
    "SOURCE_VALIDATION_ALGORITHM",
    "TARGET_ROUTING_ALGORITHM",
    "CHANNEL_REGISTRY",
    "CELL_DAY_NUM_CHANNELS",
    "VALEN_NUM_CHANNELS",
    "NUM_CHANNELS",
    "EXPANDED_NUM_CHANNELS",
    "DEFAULT_PREDICTIONS_PATH",
    "ModelConfig",
    "build_cata_model",
    "create_cata_model",
    "load_cata_model",
    "expand_model_channels",
    "cata_predict",
    "classify_cata_quadrants",
    "cata_predict_quadrants",
    "export_cata_predictions_for_lucia",
    "export_cata_predictions",
]
