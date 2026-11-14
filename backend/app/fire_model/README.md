# CATA (`fire_model`) — Algoritmo de predicción de propagación de fuego (`11_ML_DATA_CONTRACT.md`)

Algoritmo **CATA** (ConvLSTM) ubicado en `backend/app/fire_model/`, alineado con el contrato de datos
`11_ML_DATA_CONTRACT.md` (grilla `ES-LAEA-1K-v1`, EPSG:3035, celdas `ES1K:L0:Y{iy}:X{ix}` de 1 km).
Predice exclusivamente con las variables existentes en `cell_day` (MODIS + VIIRS),
sin depender de viento, pendiente ni variables externas, manteniendo arquitectura
100% modular y expandible en canales.

- **Entrada:** `(B, T, H, W, C)` → últimos `T` pasos temporales de la grilla (T=5, H=W=320).
- **Salida:** `(B, H, W, 1)` → probabilidad `[0, 1]` de celda activa en `t+1`.

| Archivo | Contenido |
|---|---|
| `config.py` | Hiperparámetros (`ALGORITHM_NAME = "cata"`), `ModelConfig`, `CHANNEL_REGISTRY` |
| `model.py` | `build_cata_model`, pérdida BCE+Dice, `expand_model_channels`, `cata_predict` |
| `train.py` | Modos `scratch` / `finetune` / `expand` / `demo`, lector `load_contract_cell_day` y `SyntheticContractGenerator` |
| `export_tflite.py` | Exportación `none` / `dynamic` / `float16` / `int8` + verificación |

## Ejecución (desde `backend/app/fire_model/` o como paquete `app.fire_model`)

```bash
cd backend/app/fire_model

# Smoke test completo del algoritmo CATA: scratch (C=1) -> finetune -> expand (C=1 -> C=7)
../../.venv/bin/python train.py --mode demo --grid 32

# Entrenar con datos reales del contrato (cell_day.parquet o cell_day.jsonl)
../../.venv/bin/python train.py --mode scratch --channels 1 --data /ruta/a/cell_day.parquet
../../.venv/bin/python train.py --mode expand --checkpoint artifacts/models/cata_c1.keras \
    --new-channels 7 --data /ruta/a/cell_day.parquet

# Exportar a TensorFlow Lite
../../.venv/bin/python export_tflite.py --model artifacts/models/demo/cata_c7.keras --quantization float16
```
