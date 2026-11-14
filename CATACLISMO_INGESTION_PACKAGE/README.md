# CATACLISMO Ingestion Pipeline - Complete Package

Single folder with entire data pipeline (Phases 1-3b + training) ready to run.

## 📦 Package Contents

```
CATACLISMO_INGESTION_PACKAGE/
├── phase1_projection.py      # Fase 1: Parser + proyección EPSG:3035 + celdas L0-L3
├── phase2_cell_day.py        # Fase 2: Agregación cell_day (15 campos)
├── meteomatics_client.py     # Fase 3a: Meteomatics (15 params, cache)
├── vegetation_client.py      # Fase 3b: Vegetación (WorldCover + IFN3)
├── rainfall_client.py        # Fase 3b: Lluvia (NASA POWER)
├── scoring_client.py         # Fase 3b: Scoring (12 features → ACEPTA/REVISAR/RECHAZA)
├── json_output.py            # Utilidad: JSON array único (streaming)
├── train_offline.py          # Entrenamiento CATA offline + TFLite export
├── PIPELINE_SUMMARY.md       # Resumen técnico del pipeline
├── SESSION_LOG.md            # Log completo de la sesión
├── update_*.md               # Documentación por fase
├── cache/                    # Caches SQLite (meteo, lluvia, vegetación)
│   ├── meteomatics_cache.sqlite
│   ├── rainfall_cache.sqlite
│   └── vegetation_cache.sqlite
└── output/                   # Outputs pre-generados (100 muestras)
    ├── observations.json/.parquet      # 18,513 observaciones
    ├── cell_day.json/.parquet          # 8,665 cell-days
    ├── cell_day_meteo.json             # 100 muestras meteo
    ├── cell_day_vegetation.json        # 100 muestras vegetación
    ├── cell_day_rainfall.json          # 100 muestras lluvia
    ├── validated_cell_day.json/.parquet # 8,665 scored (ACEPTA/REVISAR/RECHAZA)
```

---

## 🚀 Quick Start

### Prerequisites
```bash
pip install pandas numpy pyproj requests
# For Meteomatics (optional):
# pip install requests
```

### Run Full Pipeline (100 samples each)

```bash
# 1. Observations (18,513 filas → JSON + Parquet)
python phase1_projection.py \
  --input "C:\ruta\DL_FIRE_M-C61_847836" "C:\ruta\DL_FIRE_SV-C2_847837" \
  --output output --cell-size 1000

# 2. Cell day aggregation (8,665 cell-days)
python phase2_cell_day.py \
  --input output/observations.parquet \
  --output output --cell-size 1000

# 3a. Meteomatics (requiere credenciales hackathon)
python meteomatics_client.py \
  --username TU_USUARIO --password TU_PASSWORD \
  --cell-day output/cell_day.parquet \
  --output output/cell_day_meteo.json \
  --limit 100

# 3b. Vegetación (WorldCover + IFN3)
python vegetation_client.py \
  --cell-day output/cell_day.parquet \
  --output output/cell_day_vegetation.json \
  --limit 100

# 3b. Lluvia (NASA POWER - gratis, sin límite)
python rainfall_client.py \
  --cell-day output/cell_day.parquet \
  --output output/cell_day_rainfall.json \
  --limit 100 --lookback 90

# Scoring final
python scoring_client.py \
  --cell-day output/cell_day.parquet \
  --output output/validated_cell_day.parquet \
  --json-output output/validated_cell_day.json \
  --meteo output/cell_day_meteo.json \
  --veg output/cell_day_vegetation.json \
  --rain output/cell_day_rainfall.json
```

### Entrenamiento CATA + TFLite

```bash
python train_offline.py \
  --data output/validated_cell_day.parquet \
  --output artifacts/models/cata_c13.keras \
  --epochs 50 --channels 13 --grid 320 \
  --export-tflite --tflite-modes dynamic float16
```

---

## 📊 Output para ML (tu compañero)

**Archivo principal**: `output/validated_cell_day.json` (JSON array, 8,665 registros)

```python
import json, pandas as pd
with open("output/validated_cell_day.json") as f:
    data = json.load(f)

df = pd.DataFrame(data)
train_df = df[df["decision"] == "ACEPTA"].copy()
features_df = pd.json_normalize(train_df["features"])
train_df = pd.concat([train_df.drop("features", axis=1), features_df], axis=1)

# Luego agrupar por (cell_id, date) → 13 canales → tensores (B,5,320,320,13)
```

---

## 🔧 Configuración

| Parámetro | Default | Descripción |
|---|---|---|
| `--cell-size` | 1000 | Tamaño celda L0 en metros (1000=1km, 5000=5km) |
| `--grid-prefix` | auto | Prefijo grid (ES1K, ES5K, etc.) |
| `--limit` | None | Limitar registros para pruebas |
| `--lookback` | 90 | Días hacia atrás para métricas lluvia |

---

## 📁 Branch Git

Todo el código está en branch: `backend/feat/integration-pipeline`

```bash
git fetch origin
git switch backend/feat/integration-pipeline
```

---

## 📚 Documentación

- `PIPELINE_SUMMARY.md` - Resumen técnico completo
- `SESSION_LOG.md` - Log completo de desarrollo
- `update_*.md` - Detalles por fase

---

**Todo en una carpeta. Copia, pega, ejecuta.** 🚀