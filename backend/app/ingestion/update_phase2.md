# Update — Fase 2: Agregación cell_day (1 km)

**Rama**: `feat/aggregation-cell-day`  
**Fecha**: 2026-11-14  
**Commit**: (pendiente)

---

## Qué se ha hecho

Implementada la **Fase 2** del pipeline: agregación de `observations.parquet` (18,513 filas) a `cell_day.parquet` / `cell_day.jsonl` con grano `(cell_id_L0, date, sensor)`.

### Entrada
- `backend/app/ingestion/output/observations.parquet` (18,513 filas, ES1K, 1 km)
- Generada por Fase 1 con `--cell-size 1000`

### Proceso (script: `backend/app/ingestion/phase2_cell_day.py`)
1. **Carga observations** con todas las columnas contractuales
2. **Groupby** `(cell_id_L0, acq_date, sensor)` — sensores **separados** (no se suman)
3. **Calcula 15 campos contractuales** por grupo:
   - `row_id`: `{cell_id}|{date}|{sensor}`
   - Geometría: `cell_id`, `level` (0), `parent_ids` (L1/L2/L3), `cell_centroid_lonlat` (inverso EPSG:3035→4326), `cell_area_km2` (1.0)
   - Tiempo: `date`, `iso_year`, `iso_week`, `year_month`
   - Sensor: `sensor` (MODIS/VIIRS)
   - Conteos: `n_obs`, `n_day`, `n_night`, `n_platforms` (nunique platform), `n_high_conf` (rank=2), `confidence_rank_max`
   - FRP: `frp_sum_mw`, `frp_mean_mw`, `frp_max_mw`, `frp_p50_mw` (mediana)
   - `footprint_max_km`: `max(max(scan, track))`
   - `product_mix`: fracción NRT (`n_nrt / n_obs`, 4 decimales)
   - `sensor_day_observed`: **siempre `null`**
   - `coverage_fraction`: **siempre `null`**
   - `flags`: unión flags del grupo + `sp_nrt_hybrid` si `0.05 < product_mix < 0.95`
4. **Validaciones obligatorias**:
   - Reconciliación: `sum(cell_day.n_obs) == len(observations)` **por sensor** ✅
   - `row_id` único ✅
   - `sensor_day_observed` y `coverage_fraction` siempre `null` ✅
5. **Escritura**: Parquet (zstd) + JSONL

### Salida verificada (1 km)

| Métrica | Valor |
|---|---|
| Cell-days totales | **8,665** (3,564 MODIS + 5,101 VIIRS) |
| Reconciliación MODIS | 4,412 = 4,412 ✅ |
| Reconciliación VIIRS | 14,101 = 14,101 ✅ |
| `row_id` únicos | 8,665 (0 duplicados) |
| `cell_area_km2` | 1.0 |
| Rango fechas | 2026-06-01 → 2026-09-01 |
| `sensor_day_observed` null | 8,665/8,665 ✅ |
| `coverage_fraction` null | 8,665/8,665 ✅ |

### Flags detectados
| Flag | Conteo |
|---|---|
| `boundary_crossing` | 8,098 |
| `nrt` | 1,559 |
| `brightness_saturated` | 1,136 |
| `partial_period` | 29 |
| `frp_zero` | 21 |
| `island_domain` | 14 |

### Diferencia con contrato 5 km (documentado en 11_DATA_STRUCTURE_EXAMPLES.md)

| Resolución | Cell-days MODIS | Cell-days VIIRS | Total | Nota |
|---|---|---|---|---|
| **5 km (contrato original)** | 1,119 | 2,184 | 3,303 | Cada celda 5×5 km agrupa más detecciones |
| **1 km (actual)** | **3,564** | **5,101** | **8,665** | Cada celda 5 km = 25 celdas 1 km; más granularidad |

La agregación es correcta: a 1 km hay más celdas ocupadas porque la rejilla es 25× más fina. Los conteos de observaciones se conservan exactos (reconciliación ✅).

### Archivos generados
```
backend/app/ingestion/output/
├── cell_day.parquet      # 366.8 KB, 8,665 × 22 cols, zstd
├── cell_day.jsonl        # 6.1 MB, 8,665 líneas
├── observations.parquet  # 1.5 MB (Fase 1)
└── observations.jsonl    # 20.6 MB (Fase 1)
```

---

## Uso genérico

```bash
python phase2_cell_day.py \
  --input backend/app/ingestion/output/observations.parquet \
  --output backend/app/ingestion/output \
  --cell-size 1000
```

Parámetros:
- `--input`: observations.parquet de Fase 1
- `--output`: directorio de salida
- `--cell-size`: tamaño L0 en metros (default: 1000) — deriva `grid_prefix` ES1K

---

## Validaciones contractuales cumplidas

- ✅ Grano: `(cell_id, date, sensor)` — sensores separados
- ✅ 15 campos exactos según especificación
- ✅ Reconciliación exacta: `sum(n_obs) == len(observations)` por sensor
- ✅ `sensor_day_observed` y `coverage_fraction` siempre `null`
- ✅ `cell_centroid_lonlat` calculado por inversa EPSG:3035→4326
- ✅ `parent_ids` con anidamiento 2×2 (L1/L2/L3)
- ✅ `product_mix` con 4 decimales
- ✅ `flags` incluye `sp_nrt_hybrid` cuando corresponde

---

## Próximos pasos (Fase 3)

**Fase 3** (`feat/comparison-cell-day`): `comparison_cell_day.parquet` — inner join MODIS+VIIRS por `(cell_id, date)` solo donde ambos observaron, con cocientes `ratio_count`, `ratio_frp`, `ratio_defined`, `min_abs_time_gap_min`, `product_mix_max`, flags de divergencia.