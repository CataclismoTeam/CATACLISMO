# Update — Fase 3b: Clientes Vegetación (WorldCover + IFN3) + Lluvia (NASA POWER)

**Rama**: `feat/vegetation-enrichment` (vegetación) + `feat/rainfall-history` (lluvia)  
**Fecha**: 2026-11-14  
**Commits**: (pendientes)

---

## 1. Cliente Vegetación (`vegetation_client.py`)

**Fuentes**:
- **ESA WorldCover 2021 v100**: 10m, 11 clases, COG público en AWS S3
- **MITECO IFN3**: WMS GetFeatureInfo, especies forestales España

### Características
| Feature | Detalle |
|---|---|
| **WorldCover** | 11 clases, inflamabilidad 1-5 por clase, tile URL |
| **IFN3** | Especies principales (21 mapeadas), inflamabilidad por especie |
| **Combinado** | `combined_flammability = max(WC, IFN3)` |
| **Cache** | SQLite persistente, clave por coordenada |
| **IFN3 WMS** | GetFeatureInfo en `Masa_Forestal,Especie_Principal` |

### Clases WorldCover + Inflamabilidad
| ID | Clase | Flam. |
|---|---|---|
| 10 | Tree cover | 4 |
| 20 | **Shrubland** | **5** |
| 30 | Grassland | 3 |
| 40 | Cropland | 2 |
| 50 | Built-up | 1 |
| 60 | Bare/sparse | 2 |
| 70 | Snow/ice | 1 |
| 80 | Water | 1 |
| 90 | Wetland | 2 |
| 95 | Mangroves | 3 |
| 100 | Moss/lichen | 1 |

### Especies IFN3 clave (21 mapeadas)
| Especie | Flam. | Nota |
|---|---|---|
| *Pinus halepensis* (carrasco) | 5 | Muy inflamable |
| *Pinus pinaster* (rodeno) | 5 | Muy inflamable |
| *Eucalyptus sp.* | 5 | Muy inflamable |
| *Quercus ilex* (encina) | 4 | |
| *Cistus sp.* (jara) | 5 | Matorral |
| *Ulex sp.* (aulaga) | 5 | Matorral |

### Uso
```python
from vegetation_client import VegetationClient, VegetationCache
from pathlib import Path

cache = VegetationCache(Path("cache/vegetation_cache.sqlite"))
client = VegetationClient(cache)

# Perfil individual
profile = client.get_vegetation_profile(-3.7038, 40.4168)
# {'worldcover': {'class_id': 20, 'class_name': 'Shrubland', 'flammability': 5},
#  'ifn3': {'species_list': ['Quercus ilex'], 'dominant_species': 'Quercus ilex', 'max_flammability': 4},
#  'combined_flammability': 5}

# Enriquecer cell_day completo
client.enrich_cell_day(
    Path("backend/app/ingestion/output/cell_day.parquet"),
    Path("backend/app/ingestion/output/cell_day_vegetation.jsonl"),
    limit=100
)
```

### CLI
```bash
python vegetation_client.py \
  --cell-day backend/app/ingestion/output/cell_day.parquet \
  --output backend/app/ingestion/output/cell_day_vegetation.jsonl \
  --limit 50
```

---

## 2. Cliente Lluvia (`rainfall_client.py`)

**Fuente**: **NASA POWER API** (gratis, sin key, sin límite, histórico 1983-presente, 0.5° ~50km)

### Parámetros POWER (8)
| Parámetro | Unidad | Uso |
|---|---|---|
| `PRECTOTCORR` | mm/day | Precipitación corregida |
| `T2M`, `T2M_MAX`, `T2M_MIN` | °C | Temperatura |
| `RH2M` | % | Humedad relativa |
| `WS2M`, `WD2M` | m/s, ° | Viento |
| `ALLSKY_SFC_SW_DWN` | kWh/m²/d | Radiación solar |

### Métricas calculadas
| Métrica | Descripción |
|---|---|
| `days_since_rain_1mm` | Días desde última lluvia ≥ 1mm |
| `days_since_rain_10mm` | Días desde última lluvia ≥ 10mm |
| `precip_7d_mm` | Precipitación acumulada 7 días |
| `precip_30d_mm` | Precipitación acumulada 30 días |
| `precip_90d_mm` | Precipitación acumulada 90 días (lookback) |
| `dry_spell_max_days` | Máxima racha seca consecutiva (<1mm) |
| `rain_days_30d` | Días con lluvia ≥1mm en últimos 30 días |

### Uso
```python
from rainfall_client import RainfallClient, RainfallCache
from pathlib import Path

cache = RainfallCache(Path("cache/rainfall_cache.sqlite"))
client = RainfallClient(cache)

# Métricas individuales
metrics = client.calculate_rainfall_metrics(-3.7038, 40.4168, '2026-07-15', lookback_days=90)
# {'days_since_rain_1mm': 8, 'days_since_rain_10mm': 31, 'precip_30d_mm': 8.51, ...}

# Enriquecer cell_day completo
client.enrich_cell_day(
    Path("backend/app/ingestion/output/cell_day.parquet"),
    Path("backend/app/ingestion/output/cell_day_rainfall.jsonl"),
    limit=100,
    lookback_days=90
)
```

### CLI
```bash
python rainfall_client.py \
  --cell-day backend/app/ingestion/output/cell_day.parquet \
  --output backend/app/ingestion/output/cell_day_rainfall.jsonl \
  --limit 50 \
  --lookback 90
```

---

## Integración Fase 3b (Scoring Multi-fuente)

```
cell_day (MODIS + VIIRS, 8,665 filas)
    │
    ├─ Meteomatics (viento, humedad, FWI, Haines, suelo) → cell_day_meteo.jsonl
    │
    ├─ Vegetación (WorldCover + IFN3) → cell_day_veg.jsonl
    │   combined_flammability (1-5)
    │
    ├─ Lluvia (NASA POWER) → cell_day_rain.jsonl
    │   days_since_rain_1mm, precip_30d_mm, dry_spell_max_days
    │
    └─ Algoritmo Scoring → validated_cell_day.parquet
        score = w1*sensores + w2*confidence + w3*FWI + w4*viento
              + w5*humedad + w6*dias_sin_lluvia + w7*vegetación
              + w8*boundary_crossing + w9*product_mix
        decisión: ACEPTA (≥0.7) / RECHAZA (<0.3) / REVISAR_MANUAL (0.3-0.7)
```

### Pesos sugeridos (heurísticos, ajustables)
| Factor | Peso | Rationale |
|---|---|---|
| Sensores presentes (MODIS+VIIRS=3, solo VIIRS=2, solo MODIS=1) | 0.20 | Corroboración multi-sensor |
| Confidence rank max | 0.15 | Calidad detección |
| FWI (Meteomatics) | 0.15 | Riesgo meteorológico |
| Viento (>30 km/h) | 0.10 | Propagación |
| Humedad relativa (<30%) | 0.10 | Sequedad combustible |
| Días sin lluvia >15 | 0.10 | Combustible seco |
| Vegetación inflamabilidad (4-5) | 0.10 | Tipo combustible |
| Boundary crossing | 0.05 | Incertidumbre geométrica |
| Product mix (NRT) | 0.05 | Calidad producto |

---

## Archivos nuevos

```
backend/app/ingestion/
├── vegetation_client.py       # WorldCover + IFN3
├── rainfall_client.py         # NASA POWER
├── cache/
│   ├── vegetation_cache.sqlite
│   └── rainfall_cache.sqlite
└── update_vegetation_rainfall.md
```

---

## Próximo paso: Algoritmo Scoring (`feat/validation-scoring`)

Implementar `validated_cell_day.parquet` combinando todas las fuentes con umbrales configurables y salida ACEPTA/RECHAZA/REVISAR.