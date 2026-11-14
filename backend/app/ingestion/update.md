# Update — Fase 1: Proyección EPSG:3035 + Asignación a celdas L0–L3 (GENÉRICO)

**Rama**: `feat/ingestion-projection-grid`  
**Fecha**: 2026-11-14  
**Commit**: `bc251fd` (versión 5 km) + commit actual (versión genérica + 1 km)

---

## Qué se ha hecho

Reescrita la **Fase 1** como script **genérico y parametrizable** (`phase1_projection.py`) que:
- Acepta cualquier JSON FIRMS (archivos o directorios) vía `--input`
- Permite configurar tamaño de celda L0 vía `--cell-size` (metros)
- Deriva automáticamente `grid_prefix` (ES5K, ES1K, ES2K, etc.)
- Escribe `observations.parquet` + `observations.jsonl` en `--output`
- Mantiene toda la lógica contractual: tipos, proyección EPSG:3035, celdas anidadas 2×2, `confidence_rank`, flags, trazabilidad

### Dos ejecuciones realizadas

| Ejecución | Cell size | Grid prefix | Output dir | Uso |
|---|---|---|---|---|
| 1 (commit `bc251fd`) | 5000 m | ES5K | `output/` | Contrato original (CATA compatible) |
| 2 (actual) | 1000 m | ES1K | `output_1km/` | Prueba/resolución fina |

---

## Entrada (ambas ejecuciones)
- 4 archivos JSON en `C:/Users/Gabriel/Documents/nasa space apps/DL_FIRE_*/`:
  - `fire_archive_M-C61_847836.json` (4,406 filas, MODIS SP)
  - `fire_nrt_M-C61_847836.json` (6 filas, MODIS NRT)
  - `fire_archive_SV-C2_847837.json` (9,952 filas, VIIRS SP)
  - `fire_nrt_SV-C2_847837.json` (4,149 filas, VIIRS NRT)
- **Total**: 18,513 detecciones

---

## Salida verificada (1 km — `output_1km/`)

| Métrica | Valor |
|---|---|
| Filas totales | 18,513 (entrada = salida) |
| `observation_id` únicos | 18,513 (0 duplicados) |
| Coordenadas válidas | 18,513 / 18,513 |
| Proyección válida | 18,513 / 18,513 |
| Con `cell_id_L0` (ES1K) | 18,513 / 18,513 |
| Por sensor | VIIRS 14,101 · MODIS 4,412 |
| Por producto | SP 14,358 · NRT 4,155 |
| FRP total | 950,130.31 MW |
| Rango fechas | 2026-06-01 → 2026-09-01 |
| `confidence_rank` | 0: 1,314 · 1: 12,681 · 2: 4,518 |

### Flags (1 km vs 5 km)
| Flag | 5 km (ES5K) | 1 km (ES1K) | Nota |
|---|---|---|---|
| `boundary_crossing` | 5,238 | **15,175** | MODIS 4.8 km cruza ~5 celdas de 1 km |
| `brightness_saturated` | 2,255 | 2,255 | Igual (umbral de sensor) |
| `nrt` | 4,155 | 4,155 | Igual |
| `frp_zero` | 39 | 39 | Igual |
| `island_domain` | 15 | 15 | Igual (umbral x_3035 fijo) |
| `partial_period` | 39 | 39 | Igual |

### Archivos generados (1 km)
```
backend/app/ingestion/output_1km/
├── observations.parquet  # 1.4 MB, 18,513 × 42 cols, zstd
└── observations.jsonl    # 20.6 MB, 18,513 líneas
```

---

## Uso genérico

```bash
# 5 km (contrato original)
python phase1_projection.py \
  --input /ruta/a/jsons/ \
  --output ./output_5km \
  --cell-size 5000

# 1 km (resolución fina)
python phase1_projection.py \
  --input /ruta/a/jsons/ \
  --output ./output_1km \
  --cell-size 1000

# 2 km
python phase1_projection.py \
  --input archivo1.json archivo2.json /directorio/ \
  --output ./output_2km \
  --cell-size 2000 \
  --grid-prefix ES2K  # opcional, por defecto ES{km}K
```

Parámetros:
- `--input`: uno o más archivos `.json` o directorios (recursivo)
- `--output`: directorio de salida (se crea si no existe)
- `--cell-size`: tamaño L0 en metros (default: 5000)
- `--grid-prefix`: prefijo para `cell_id` (default: `ES{cell_size/1000}K`)
- `--partial-period-start`: fecha inicio periodo incompleto (default: `2026-09-01`)

---

## Validaciones contractuales cumplidas (ambos tamaños)

- ✅ Contabilidad exacta: filas leídas = filas escritas
- ✅ `observation_id` determinista y único (`SENSOR:archivo:fila`)
- ✅ Proyección EPSG:3035 correcta
- ✅ Celdas L0–L3 con `floor(x/cell_size)` + anidamiento 2×2 exacto (`parent_ids`)
- ✅ `confidence_rank` unificado 0/1/2 entre sensores
- ✅ Catálogo de flags cerrado implementado
- ✅ `ingest_run_id` trazable (timestamp UTC + hash8)
- ✅ `acq_minute` entero 0–1439 (minutos UTC del día)
- ✅ `src_*` conserva todo campo original (auditoría completa)

---

## ⚠️ Impacto en CATA (importante)

El algoritmo CATA (`backend/app/fire_model/config.py`) está configurado para **celdas de 5 km**:

```python
GRID_ID: str = "ES-LAEA-5K-v1"
CHUNK_SIZE_M: float = 5000.0  # 5 km
GRID_SIZE: int = 64           # ventana 64×64 celdas = 320 km
```

Si se usa **1 km** (`ES-LAEA-1K-v1`):
- La misma `GRID_SIZE=64` cubriría solo **64 km** (no 320 km)
- Opciones:
  1. Aumentar `GRID_SIZE=320` para misma cobertura (más memoria/computo)
  2. Aceptar ventana espacial menor (64 km)
  3. Mantener 5 km para CATA y usar 1 km solo para análisis/visualización

**Recomendación**: Mantener **5 km (ES5K)** como versión canónica para CATA. La versión 1 km sirve para análisis de detalle, frontend, o futuros modelos de mayor resolución.

---

## Próximos pasos (Fase 2+)

1. **Fase 2** (`feat/aggregation-cell-day`): Agregar `observations` → `cell_day.parquet` (grano `cell_id + date + sensor`) con 15 campos contractuales. Debe ser parametrizable igual que Fase 1 (`--cell-size`, `--grid-prefix`).
2. **Fase 3** (`feat/comparison-cell-day`): `comparison_cell_day.parquet` (cocientes MODIS/VIIRS).
3. **Fase 4** (`feat/manifest-generation`): `manifest.json` con hashes, conteos, `schema_version`, `grid_id`, `invalid_periods`.

---

## Cómo ejecutar (versión 5 km canónica)

```bash
cd backend/app/ingestion
python phase1_projection.py \
  --input "C:/Users/Gabriel/Documents/nasa space apps/DL_FIRE_M-C61_847836" \
          "C:/Users/Gabriel/Documents/nasa space apps/DL_FIRE_SV-C2_847837" \
  --output ./output \
  --cell-size 5000
```

Salida esperada: `OK - FASE 1 completada correctamente` + archivos en `output/`.