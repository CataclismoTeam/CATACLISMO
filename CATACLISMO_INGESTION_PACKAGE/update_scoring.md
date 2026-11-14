# Update — Fase 3b: Algoritmo Scoring Multi-fuente

**Rama**: `feat/validation-scoring`  
**Fecha**: 2026-11-14  
**Commit**: (pendiente)

---

## Qué se ha hecho

Implementado **algoritmo de scoring multi-fuente** (`scoring_client.py`) que combina todas las fuentes de datos de la Fase 3 y produce `validated_cell_day.parquet` con decisión **ACEPTA / REVISAR_MANUAL / RECHAZA**.

---

## Arquitectura del Scoring

```
cell_day (8,665 filas, sensores separados)
    │
    ├─ Meteomatics (meteo.jsonl)     → FWI, viento, humedad, índices
    ├─ Vegetación (veg.jsonl)        → combined_flammability (1-5)
    ├─ Lluvia (rain.jsonl)           → days_since_rain, precip, dry_spell
    │
    ▼ merge_enrichments()
    │
    ▼ extract_features() → 12 features normalizadas (0-1)
    │
    ▼ compute_score() → score ponderado (0-1)
    │
    ▼ decide() → ACEPTA (≥0.70) / REVISAR_MANUAL (0.30-0.70) / RECHAZA (<0.30)
    │
    ▼ validated_cell_day.parquet
```

---

## 12 Features Normalizadas (0-1)

| Feature | Fuente | Normalización | Peso |
|---|---|---|---|
| `sensor_count` | cell_day (MODIS+VIIRS) | 1=MODIS, 2=VIIRS, 3=BOTH | 0.20 |
| `confidence_rank_max` | cell_day | 0/1/2 → minmax | 0.15 |
| `n_high_conf_ratio` | cell_day | n_high/n_obs | 0.05 |
| `fwi` | Meteomatics | minmax 0-50 | 0.15 |
| `wind_speed` | Meteomatics | minmax 0-20 m/s | 0.10 |
| `humidity` | Meteomatics | **inverso** minmax 10-90% | 0.10 |
| `days_since_rain_1mm` | NASA POWER | minmax 0-30 días | 0.10 |
| `dry_spell_max` | NASA POWER | minmax 0-30 días | 0.05 |
| `precip_30d` | NASA POWER | **inverso** minmax 0-100mm | 0.05 |
| `vegetation_flammability` | WorldCover+IFN3 | minmax 1-5 | 0.10 |
| `boundary_crossing` | cell_day flags | binary (0/1) | 0.05 |
| `product_mix_nrt` | cell_day | direct 0-1 | 0.05 |

**Total pesos**: 1.00

---

## Normalización

| Tipo | Descripción |
|---|---|
| `minmax` | `(value - min) / (max - min)` → clip [0,1] |
| `inverse_minmax` | `1 - (value - min) / (max - min)` → menos valor = más riesgo |
| `binary` | 0/1 directo |
| `direct` | clip [0,1] directo |

Valores `None`/NaN → 0.0 (conservador: sin dato = riesgo mínimo)

---

## Umbrales de Decisión

| Decisión | Rango Score | Acción |
|---|---|---|
| **ACEPTA** | ≥ 0.70 | Fuego confirmado, pasa a CATA/Rutas |
| **REVISAR_MANUAL** | 0.30 - 0.70 | Requiere validación humano/operador |
| **RECHAZA** | < 0.30 | Probable falso positivo, descartar |

---

## Ejemplo de Cálculo

```python
features = {
    'sensor_count': 1.0,        # BOTH sensors
    'confidence_rank_max': 1.0, # rank=2
    'n_high_conf_ratio': 0.5,
    'fwi': 0.6,                 # FWI=30
    'wind_speed': 0.5,          # 10 m/s
    'humidity': 0.75,           # 30% RH (inverso)
    'days_since_rain_1mm': 0.4, # 12 días
    'dry_spell_max': 0.3,
    'precip_30d': 0.8,          # 20mm (inverso)
    'vegetation_flammability': 0.75,  # clase 4
    'boundary_crossing': 0.0,
    'product_mix_nrt': 0.0,
}

score = 0.6609  # REVISAR_MANUAL
```

---

## Uso

```bash
python scoring_client.py \
  --cell-day backend/app/ingestion/output/cell_day.parquet \
  --output backend/app/ingestion/output/validated_cell_day.parquet \
  --meteo backend/app/ingestion/output/cell_day_meteo.jsonl \
  --veg backend/app/ingestion/output/cell_day_vegetation.jsonl \
  --rain backend/app/ingestion/output/cell_day_rainfall.jsonl \
  --accept-threshold 0.70 \
  --review-threshold 0.30
```

### Pesos personalizados
```bash
--weights '{"fwi": 0.25, "wind_speed": 0.15, "sensor_count": 0.15}'
```

---

## Salida: `validated_cell_day.parquet`

| Columna | Tipo | Descripción |
|---|---|---|
| `cell_id` | string | ES1K:L0:Y{iy}:X{ix} |
| `date` | date | YYYY-MM-DD |
| `sensor` | string | MODIS / VIIRS |
| `score` | float32 | 0.0 - 1.0 |
| `decision` | string | ACEPTA / REVISAR_MANUAL / RECHAZA |
| `features` | json | 12 features normalizadas |
| `scored_at` | timestamp | UTC ISO |

---

## Integración con CATA

CATA puede filtrar `validated_cell_day` por `decision == "ACEPTA"` para entrenar solo con fuegos validados:

```python
validated = pd.read_parquet("validated_cell_day.parquet")
accepted = validated[validated["decision"] == "ACEPTA"]
# Agregar accepted por (cell_id, date) → cell_day limpio para CATA
```

---

## Archivos nuevos

```
backend/app/ingestion/
├── scoring_client.py        # Algoritmo scoring + merge + CLI
├── update_scoring.md        # Este archivo
```

---

## Próximos pasos

1. **Ejecutar pipeline completo** Fase 1→2→3a→3b→3b_scoring
2. **Validar contra EFFIS/perímetros reales** para calibrar pesos/umbrales
3. **Exportar `cell_day_validated.parquet`** para CATA (solo ACEPTA)
4. **Generar `manifest.json`** final con conteos por decisión