# Update — Fase 1: Proyección EPSG:3035 + Asignación a celdas L0–L3

**Rama**: `feat/ingestion-projection-grid`  
**Fecha**: 2026-11-14  
**Commit**: (pendiente)

---

## Qué se ha hecho

Implementada la **Fase 1** del pipeline de datos: transformación de los 4 JSON originales de FIRMS (MODIS + VIIRS, SP + NRT) en la tabla maestra `observations.parquet` / `observations.jsonl` lista para que la consuman los módulos de **Predicción (CATA)**, **Rutas** y **Frontend**.

### Entrada
- 4 archivos JSON en `C:/Users/Gabriel/Documents/nasa space apps/DL_FIRE_*/`:
  - `fire_archive_M-C61_847836.json` (4,406 filas, MODIS SP)
  - `fire_nrt_M-C61_847836.json` (6 filas, MODIS NRT)
  - `fire_archive_SV-C2_847837.json` (9,952 filas, VIIRS SP)
  - `fire_nrt_SV-C2_847837.json` (4,149 filas, VIIRS NRT)
- **Total**: 18,513 detecciones

### Proceso (script: `backend/app/ingestion/phase1_projection.py`)
1. **Lectura directa de JSON** (sin CSV intermedio)
2. **Tipado real**: `frp`, `lat`, `lon`, `brightness`, `scan`, `track` → float; `acq_time` → `acq_minute` (int 0–1439); `acq_date` → `date`
3. **Proyección EPSG:3035** (ETRS89-LAEA Europe, metros) via `pyproj` → `x_3035`, `y_3035`
4. **Celdas L0–L3** (anidamiento 2×2 exacto):
   - L0 = 5 km → `cell_id_L0` = `ES5K:L0:Y{iy}:X{ix}` con `iy=floor(y/5000)`, `ix=floor(x/5000)`
   - L1 = 10 km, L2 = 20 km, L3 = 40 km → `cell_id_L1`..`cell_id_L3`
   - `parent_ids` dict con IDs padre L1/L2/L3 (`iy//2`, `ix//2` por nivel)
5. **Control de calidad**:
   - `confidence_rank` (0/1/2 unificado): MODIS `<30/30-79/≥80`; VIIRS `l/n/h`
   - `flags` (lista): `frp_zero`, `brightness_saturated`, `nrt`, `boundary_crossing`, `island_domain`, `partial_period`
6. **Trazabilidad**:
   - `observation_id` determinista: `SENSOR:archivo:fila` (ej. `MODIS:fire_archive_M-C61_847836:0`)
   - `ingest_run_id` único por corrida: `YYYYMMDDTHHMMSSZ-{hash8}`
   - Conserva **todos** los campos originales con prefijo `src_*`
7. **Escritura**:
   - `observations.parquet` (schema tipado, compresión zstd, 1.3 MB)
   - `observations.jsonl` (línea por observación, UTF-8, 20.4 MB)

### Salida verificada
| Métrica | Valor |
|---|---|
| Filas totales | 18,513 (entrada = salida) |
| `observation_id` únicos | 18,513 (0 duplicados) |
| Coordenadas válidas | 18,513 / 18,513 |
| Proyección válida | 18,513 / 18,513 |
| Con `cell_id_L0` | 18,513 / 18,513 |
| Por sensor | VIIRS 14,101 · MODIS 4,412 |
| Por producto | SP 14,358 · NRT 4,155 |
| FRP total | 950,130.31 MW |
| Rango fechas | 2026-06-01 → 2026-09-01 |
| Rango x_3035 | 1,693,587 → 3,755,218 m |
| Rango y_3035 | 952,449 → 2,453,359 m |
| `confidence_rank` | 0: 1,314 · 1: 12,681 · 2: 4,518 |
| `daynight` | N: 10,248 · D: 8,265 |
| `type_code` | 0: 13,724 · 2: 630 · 3: 4 |

### Flags detectados
| Flag | Conteo |
|---|---|
| `boundary_crossing` | 5,238 |
| `brightness_saturated` | 2,255 |
| `partial_period` | 39 |
| `frp_zero` | 39 |
| `island_domain` | 15 |

### Archivos nuevos en el repo
```
backend/app/ingestion/
├── phase1_projection.py      # Script principal Fase 1
├── update.md                 # Este archivo
└── output/
    ├── observations.parquet  # 1.3 MB, 18,513 × 42 cols
    └── observations.jsonl    # 20.4 MB, 18,513 líneas
```

---

## Validaciones contractuales cumplidas

- ✅ Contabilidad exacta: filas leídas = filas escritas
- ✅ `observation_id` determinista y único
- ✅ Proyección EPSG:3035 correcta (coincide con specs 03/04/05)
- ✅ Celdas L0–L3 con fórmula `floor(x/5000)`, `floor(y/5000)` y anidamiento 2×2
- ✅ `confidence_rank` unificado 0/1/2 entre sensores
- ✅ Catálogo de flags cerrado implementado
- ✅ `ingest_run_id` trazable (timestamp UTC + hash8)
- ✅ `parent_ids` con jerarquía L1/L2/L3
- ✅ `acq_minute` entero 0–1439 (minutos UTC del día)
- ✅ `src_*` conserva todo campo original (auditoría completa)

---

## Próximos pasos (Fase 2+)

1. **Fase 2** (`feat/aggregation-cell-day`): Agregar `observations` → `cell_day.parquet` (grano `cell_id + date + sensor`, 3,303 filas) con 15 campos contractuales
2. **Fase 3** (`feat/comparison-cell-day`): `comparison_cell_day.parquet` (519 filas, cocientes MODIS/VIIRS solo donde ambos observaron)
3. **Fase 4** (`feat/manifest-generation`): `manifest.json` con hashes, conteos, `schema_version`, `grid_id`, `invalid_periods`

---

## Cómo ejecutar

```bash
cd backend/app/ingestion
python phase1_projection.py
```

Salida esperada: `OK - FASE 1 completada correctamente` + archivos en `output/`.