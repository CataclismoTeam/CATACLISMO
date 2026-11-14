# CATA (`fire_model`) — Algoritmo de predicción de propagación de fuego (1000 × 1000 m)

Algoritmo **CATA** (ConvLSTM) ubicado en `backend/app/fire_model/`, configurado con cuadrículas
tácticas de **1000 × 1000 m** (`GRID_ID = "ES-LAEA-1K-v1"`, `CHUNK_SIZE_M = 1000.0`, celdas
`ES1K:L0:Y{iy}:X{ix}` de 1 km²). Predice exclusivamente con las variables existentes en
`cell_day` / `parsed_data.csv.gz` (MODIS + VIIRS), sin depender de variables externas, y
**marca de forma diferenciada los cuadrantes predichos (`PREDICT`) frente a lo quemado de verdad**.

- **Entrada:** `(B, T, H, W, C)` → últimos `T` pasos temporales de la cuadrícula de 1000 × 1000 m.
- **Salida:**
  - `cata_predict`: `(B, H, W)` → probabilidad `[0, 1]` de celda activa en `t+1`.
  - `cata_predict_quadrants`: diccionario con matrices y cuadrícula de símbolos que distinguen
    explícitamente **lo quemado de verdad** de **los cuadrantes predichos (`predict`)**:
    - `0` (`SAFE` / `.`): Cuadrante seguro.
    - `1` (`PREDICTED_FIRE` / `P`): **Cuadrante PREDICT** (no quemado de verdad aún, predicho por CATA en `t+1`).
    - `2` (`CONFIRMED_BURNED` / `F`): **Quemado de verdad** (confirmado por satélite en `<= t`).
    - `3` (`CONFIRMED_AND_CONTINUES` / `B`): **Quemado de verdad** que además persiste ardiendo en `t+1`.

| Archivo | Contenido |
|---|---|
| `config.py` | `CHUNK_SIZE_M = 1000.0`, `GRID_ID = "ES-LAEA-1K-v1"`, códigos/símbolos `QUADRANT_*`, `CHANNEL_REGISTRY` |
| `model.py` | `build_cata_model`, `expand_model_channels`, `cata_predict`, `classify_cata_quadrants`, `cata_predict_quadrants` |
| `train.py` | Modos `scratch` / `finetune` / `expand` / `demo`, soporte para `parsed_data.csv.gz` y `cell_day.parquet` a 1000 m |
| `export_tflite.py` | Exportación `none` / `dynamic` / `float16` / `int8` + verificación |

## Ejecución

```bash
cd backend/app/fire_model

# Smoke test completo del algoritmo CATA (1000x1000m)
../../.venv/bin/python train.py --mode demo --grid 32

# Entrenar directamente desde los datos reales parseados a 1000x1000m
../../.venv/bin/python train.py --mode scratch --channels 7 --data ../../parser/output/parsed_data.csv.gz
```
