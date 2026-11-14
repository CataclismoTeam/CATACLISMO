# Update — Fase 3a: Cliente Meteomatics con Cache Inteligente

**Rama**: `feat/meteomatics-enrichment`  
**Fecha**: 2026-11-14  
**Commit**: (pendiente)

---

## Qué se ha hecho

Implementado **cliente Meteomatics** (`backend/app/ingestion/meteomatics_client.py`) para enriquecer `cell_day` con variables meteorológicas y de riesgo de incendio, como base para la **Fase 3 extendida (Validación Inteligente)**.

### Características principales

| Feature | Detalle |
|---|---|
| **Autenticación** | Usuario/password hackathon (1,000 queries/día) |
| **Rate limiting** | Control interno + pausa automática al límite |
| **Cache persistente** | SQLite (`cache/meteomatics_cache.sqlite`) con TTL 24h |
| **Batch queries** | Múltiples parámetros en un solo request HTTP |
| **Parámetros fuego** | 15 parámetros clave (temperatura, viento, humedad, precipitación, FWI, Haines, Fosberg, humedad suelo) |
| **Interfaz cell_day** | `query_cell_day(cell_id, centroid, date)` → JSON estructurado |
| **Enriquecedor alto nivel** | `enrich_cell_day_with_meteomatics(cell_day.parquet, output.jsonl)` |

### Parámetros incluidos (15)

| Categoría | Parámetros Meteomatics |
|---|---|
| Temperatura | `t_2m:C` |
| Humedad | `relative_humidity_2m:p`, `dew_point_2m:C`, `vapour_pressure_deficit_2m:Pa` |
| Viento | `wind_speed_10m:ms`, `wind_dir_10m:d`, `wind_gusts_10m_1h:ms` |
| Precipitación | `precip_1h:mm`, `precip_24h:mm` |
| Radiación | `global_rad:W/m2` |
| Índices fuego | `fire_weather_index:idx`, `haines_index:idx`, `fosberg_index:idx` |
| Suelo | `soil_moisture_0_10cm:m3/m3`, `soil_temp_0_10cm:C` |

### Uso básico

```python
from meteomatics_client import MeteomaticsClient, MeteomaticsCache, enrich_cell_day_with_meteomatics
from pathlib import Path

cache = MeteomaticsCache(Path("cache/meteomatics_cache.sqlite"))
client = MeteomaticsClient("tu_usuario@hackathon", "tu_password", cache)

# Enriquecer cell_day completo
enrich_cell_day_with_meteomatics(
    Path("backend/app/ingestion/output/cell_day.parquet"),
    Path("backend/app/ingestion/output/cell_day_enriched.jsonl"),
    client,
    limit=100  # opcional, para prueba
)
```

### Uso directo (bajo nivel)

```python
# Consulta un parámetro para una celda-día
result = client.query_parameter(
    param="fire_weather_index:idx",
    lat=40.4168, lon=-3.7038,  # Madrid
    start="2026-07-15T00:00:00Z",
    end="2026-07-15T23:00:00Z",
    interval="PT1H"
)

# Batch múltiple parámetros
results = client.query_batch(
    params=["t_2m:C", "wind_speed_10m:ms", "relative_humidity_2m:p"],
    lat=40.4168, lon=-3.7038,
    start="2026-07-15T00:00:00Z",
    end="2026-07-15T23:00:00Z"
)

# Cell-day completa
cell_data = client.query_cell_day(
    cell_id="ES1K:L0:Y2033:X3258",
    centroid_lonlat=[-3.7038, 40.4168],
    date_str="2026-07-15"
)
```

### Cache inteligente

- **Clave**: hash SHA-256 de `(param, lat, lon, start, end, interval)`
- **TTL**: 24 horas (configurable)
- **Storage**: SQLite con índice compuesto para lookups rápidos
- **Stats**: `client.cache.stats()` → `{"entries": 123, "size_mb": 4.5}`

### Rate limiting

- Límite hackathon: **1,000 queries/día** (reset medianoche UTC)
- Control interno: `client.get_queries_remaining()` / `client.get_queries_used_today()`
- Lanza `RuntimeError` si se excede (no falla silenciosamente)

### CLI

```bash
python meteomatics_client.py \
  --username tu_usuario@hackathon \
  --password tu_password \
  --cell-day backend/app/ingestion/output/cell_day.parquet \
  --output backend/app/ingestion/output/cell_day_enriched.jsonl \
  --limit 50 \
  --cache-dir backend/app/ingestion/cache
```

---

## Integración con Fase 3 extendida

Este cliente es la **fuente de datos meteorológicos** para el algoritmo de scoring de la Fase 3b:

```
cell_day (MODIS + VIIRS)
    │
    ├─ Enriquecer con Meteomatics → cell_day_enriched.jsonl
    │   (temperatura, viento, humedad, FWI, Haines, precipitación, humedad suelo)
    │
    ├─ Enriquecer con vegetación (ESA WorldCover, IFN3) → + tipo_vegetación, inflamabilidad
    │
    └─ Algoritmo scoring → validated_cell_day.parquet
        score = f(sensores, confidence, FWI, viento, humedad, dias_sin_lluvia, vegetación, ...)
        decisión: ACEPTA / RECHAZA / REVISAR_MANUAL
```

---

## Próximos pasos (Fase 3b)

1. **Cliente vegetación**: ESA WorldCover (10m) + MITECO IFN3 (WMS/GeoJSON) → tipo vegetación + inflamabilidad por especie
2. **Histórico lluvia**: NASA POWER / ERA5 / CHIRPS → días desde última precipitación >10mm
3. **Algoritmo scoring**: Reglas heurísticas → umbrales configurables → decisión binaria
4. **Validación**: Comparar contra EFFIS / perímetros quemados reales

---

## Archivos nuevos

```
backend/app/ingestion/
├── meteomatics_client.py       # Cliente principal + cache + CLI
├── cache/
│   └── meteomatics_cache.sqlite  # Cache persistente (se crea al usar)
└── update_meteomatics.md       # Este archivo
```