# CATA (`cata`) — Algoritmo de predicción de propagación de fuego (1000 × 1000 m)

Algoritmo **CATA** (ConvLSTM) ubicado en `backend/app/cata/`, configurado con cuadrículas
tácticas de **1000 × 1000 m** (`GRID_ID = "ES-LAEA-1K-v1"`, `CHUNK_SIZE_M = 1000.0`, celdas
`ES1K:L0:Y{iy}:X{ix}` de 1 km²).

## Flujo de integración: `VALEN` → `CATA` → `LUCIA`

1. **Entrada validada y enriquecida desde `VALEN` (`backend/app/valen/output/`):**
   CATA filtra el ruido descartado por VALEN (`decision != "RECHAZA"`) y consume **22 canales** (`CHANNEL_REGISTRY`) agrupados en 4 bloques:
   - **Cell Day (`0..12`, 13 canales MODIS + VIIRS):** `frp_sum_mw`, `frp_max_mw`, `frp_mean_mw`, `frp_p50_mw`, `n_obs`, `n_high_conf`, `confidence_rank_max`, `n_day_ratio`, `n_night_ratio`, `footprint_max_km`, `n_platforms`, `product_mix`, `viirs_obs_share`.
   - **Meteo (`13..16`, 4 canales Meteomatics):** `meteo_fwi`, `meteo_wind_speed`, `meteo_humidity_inv`, `meteo_temp`.
   - **Rainfall (`17..19`, 3 canales NASA POWER):** `rain_days_since_1mm`, `rain_dry_spell_max`, `rain_precip_30d_inv`.
   - **Vegetation & Validación (`20..21`, 2 canales WorldCover/IFN3 + VALEN):** `veg_flammability`, `valen_score`.

2. **Predicción y diferenciación Real vs Predict (`CATA`):**
   - `cata_predict`: `(B, H, W)` → probabilidad `[0, 1]` de celda activa en `t+1`.
   - `cata_predict_quadrants`: distingue explícitamente **lo quemado de verdad** de **los cuadrantes predichos (`predict`)**:
     - `0` (`SAFE` / `.`): Cuadrante seguro.
     - `1` (`PREDICTED_FIRE` / `P`): **Cuadrante PREDICT** (no quemado de verdad aún, predicho por CATA en `t+1`).
     - `2` (`CONFIRMED_BURNED` / `F`): **Quemado de verdad** (confirmado por satélite en `<= t`).
     - `3` (`CONFIRMED_AND_CONTINUES` / `B`): **Quemado de verdad** que además persiste ardiendo en `t+1`.

3. **Archivo de salida de predicciones para `LUCIA` (`artifacts/predictions/cata_predictions.json`):**
   - Exportado mediante `export_cata_predictions_for_lucia` (o `--mode predict` / `--predictions-output`).
   - Incluye las matrices 2D por zona (`symbol_grid`, `state_matrix`, `fire_probability_grid`, `estimated_fire_arrival_hours`, `human_traversal_cost_grid`, `animal_traversal_cost_grid`) y la lista georreferenciada `active_and_predicted_cells` para que en un futuro **LUCIA** calcule las vías de escape de **personas y animales**.

## Archivos del módulo

| Archivo | Contenido |
|---|---|
| `config.py` | `CHANNEL_REGISTRY` (22 canales VALEN), `VALEN_ACCEPTED_DECISIONS`, rutas hacia `VALEN` y `DEFAULT_PREDICTIONS_PATH` para `LUCIA` |
| `model.py` | `build_cata_model`, `expand_model_channels`, `cata_predict`, `cata_predict_quadrants`, `export_cata_predictions_for_lucia` |
| `train.py` | Modos `scratch` / `finetune` / `expand` / `predict` / `demo`, fusión automática de `cell_day`, `meteo`, `rainfall`, `vegetation` y `validated_cell_day` |
| `export_tflite.py` | Exportación `none` / `dynamic` / `float16` / `int8` + verificación |

## Ejecución

```bash
cd backend/app/cata

# 1. Entrenar CATA con los 22 canales reales validados por VALEN y generar cata_predictions.json para LUCIA
../../.venv/bin/python train.py --mode scratch --channels 22 --data ../valen/output --epochs 3

# 2. Ejecutar solo predicción sobre los datos de VALEN hacia otro archivo para LUCIA
../../.venv/bin/python train.py --mode predict --data ../valen/output --predictions-output artifacts/predictions/cata_predictions.json

# 3. Smoke test completo (C=1 -> finetune -> expand C=22 -> exporta predicciones para LUCIA)
../../.venv/bin/python train.py --mode demo --grid 32
```
