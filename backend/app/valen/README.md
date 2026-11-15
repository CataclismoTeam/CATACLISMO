# VALEN (`valen`) — Algoritmo de Ingesta, Enriquecimiento Multi-Fuente y Validación de Datos

> **Contexto consolidado para IA / Generación de Documentación:**  
> Este documento unifica todas las notas técnicas de desarrollo de **VALEN** (`README.md`, `PIPELINE_SUMMARY.md`, `SESSION_LOG.md`, `update_phase1`, `update_phase2`, `update_meteomatics`, `update_vegetation_rainfall` y `update_scoring`), así como su integración directa con **CATA** (`backend/app/cata/`) y el futuro algoritmo de evacuación **LUCIA**.

---

## 1. Visión General y Rol en la Arquitectura (`VALEN` → `CATA` → `LUCIA`)

- **Identificador del algoritmo:** `ALGORITHM_NAME = "valen"` (`backend/app/valen/`).
- **Problema que resuelve:** Los satélites de la NASA (FIRMS: sensores **MODIS** en Terra/Aqua y **VIIRS** en SNPP/NOAA-20/21) detectan anomalías térmicas brutas (*hotspots*), que incluyen numerosos falsos positivos (chimeneas industriales, quemas agrícolas controladas, reflejos solares en paneles o láminas de agua, saturación de sensor).
- **Qué hace VALEN:**
  1. Ingiere y proyecta las detecciones satelitales a la rejilla europea métrica **ETRS89-LAEA (`EPSG:3035`)** con celdas tácticas de **1000 × 1000 m (`ES1K`)** y jerarquía anidada 2×2 (`L0` a `L3`).
  2. Agrega las observaciones por `(cell_id, date, sensor)` garantizando reconciliación exacta (`sum(n_obs) == len(observations)`).
  3. Enriquece cada celda-día con **3 fuentes ambientales externas** con caché SQLite persistente:
     - **Meteorología (`Meteomatics`):** 15 parámetros horarios (FWI, velocidad/dirección/rachas de viento, humedad relativa, temperatura a 2m, índices Haines y Fosberg, humedad/temperatura del suelo, radiación, precipitación).
     - **Combustible vegetal (`ESA WorldCover 10m` + `MITECO IFN3`):** Clase de cobertura del suelo (11 clases WorldCover) y especies forestales españolas (21 especies mapeadas en IFN3) convertidas a escala de inflamabilidad `1..5` (`combined_flammability`).
     - **Memoria hídrica y sequía (`NASA POWER`):** Ventana histórica de 90 días con días consecutivos sin lluvia ($\ge 1\text{ mm}$ y $\ge 10\text{ mm}$), precipitación acumulada a 7/30/90 días y racha seca máxima (`dry_spell_max_days`).
  4. Calcula mediante `valen_compute_score()` un **score ponderado `[0, 1]`** sobre 12 features normalizadas y emite una decisión con `valen_decide()`:
     - `ACEPTA` ($\ge 0.70$): Foco de incendio validado con alta confianza.
     - `REVISAR_MANUAL` ($0.30 - 0.70$): Anomalía térmica plausible que requiere seguimiento o carece de alguna fuente externa.
     - `RECHAZA` ($< 0.30$): Falso positivo descartado.
- **Conexión con CATA y LUCIA:**
  - **CATA (`backend/app/cata/`)** descarta automáticamente los registros `RECHAZA` de **VALEN** y consume un tensor de **22 canales** (`13` de `cell_day` + `4` de `meteo` + `3` de `rainfall` + `1` de `vegetation` + `1` de `valen_score`).
  - **CATA** genera el archivo `cata_predictions.json` con probabilidades en `t+1`, cuadrantes diferenciados (`SAFE`, `PREDICTED_FIRE`, `CONFIRMED_BURNED`, `CONFIRMED_AND_CONTINUES`), tiempos estimados de llegada del fuego y costes de paso diferenciados para **personas** y **animales**, listo para alimentar a **LUCIA**.

---

## 2. Estructura del Paquete (`backend/app/valen/`)

```text
backend/app/valen/
├── __init__.py               # ALGORITHM_NAME = "valen"
├── phase1_projection.py      # Fase 1: Parser streaming FIRMS + proyección EPSG:3035 + celdas L0-L3
├── phase2_cell_day.py        # Fase 2: Agregación por (cell_id_L0, date, sensor) — 15 bloques contractuales
├── meteomatics_client.py     # Fase 3a: Cliente Meteomatics (15 parámetros horarios + caché SQLite)
├── vegetation_client.py      # Fase 3b: Cliente Vegetación (ESA WorldCover 10m + MITECO IFN3 + caché SQLite)
├── rainfall_client.py        # Fase 3b: Cliente Sequía/Lluvia (NASA POWER 90d lookback + caché SQLite)
├── scoring_client.py         # Fase 3b: Motor de puntuación VALEN (12 features -> score -> ACEPTA/REVISAR/RECHAZA)
├── json_output.py            # Utilidad transversal: escritura de JSON array en streaming (JSONArrayWriter)
├── cache/                    # Cachés SQLite persistentes
│   ├── meteomatics_cache.sqlite
│   ├── rainfall_cache.sqlite
│   └── vegetation_cache.sqlite
└── output/                   # Artefactos generados por VALEN (consumidos por CATA)
    ├── observations.parquet / .json       # 18,513 detecciones individuales proyectadas
    ├── cell_day.parquet / .json           # 8,665 celdas-día-sensor (L0 = 1 km²)
    ├── cell_day_meteo.json                # Enriquecimiento meteorológico (Meteomatics)
    ├── cell_day_vegetation.json           # Enriquecimiento de inflamabilidad vegetal (WorldCover + IFN3)
    ├── cell_day_rainfall.json             # Enriquecimiento de sequía y precipitación (NASA POWER)
    └── validated_cell_day.parquet / .json # 8,665 registros puntuados y clasificados por VALEN
```

---

## 3. Detalle Técnico por Fase

### Fase 1: Parser Streaming y Proyección Geoespacial (`phase1_projection.py`)
- **Entrada:** Extractos JSON de NASA FIRMS (`fire_archive_M-C61_*.json`, `fire_nrt_M-C61_*.json`, `fire_archive_SV-C2_*.json`, `fire_nrt_SV-C2_*.json`).
- **Procesamiento:**
  - Lectura en streaming por bloques (`STREAMING_CHUNK_SIZE = 10_000`) para bajo consumo de memoria.
  - Identificación determinista de `sensor` (`MODIS` vs `VIIRS`) y `source_product` (`SP` vs `NRT`).
  - Generación de `observation_id` único y determinista (`{SENSOR}:{archivo}:{fila}`) y `ingest_run_id` con hash SHA-256.
  - Conversión de coordenadas `WGS84 (EPSG:4326)` a `ETRS89-LAEA Europe (EPSG:3035)` en metros (`x_3035`, `y_3035`).
  - Asignación de celdas multirresolución con anidamiento 2×2 exacto (`cell_size` por defecto = `1000 m`, prefijo `ES1K`):
    - `L0`: 1 km (`ES1K:L0:Y{iy}:X{ix}`)
    - `L1`: 2 km (`ES1K:L1:Y{iy//2}:X{ix//2}`)
    - `L2`: 4 km (`ES1K:L2:Y{iy//4}:X{ix//4}`)
    - `L3`: 8 km (`ES1K:L3:Y{iy//8}:X{ix//8}`)
  - Armonización de confianza entre sensores (`confidence_rank`: `0=low`, `1=nominal`, `2=high`).
  - Catálogo cerrado de flags de calidad:
    - `boundary_crossing`: huella del píxel (`max(scan, track)`) mayor que la distancia al borde de la celda.
    - `brightness_saturated`: saturación térmica (`VIIRS >= 367 K` o `<= 208 K`; `MODIS >= 500 K`).
    - `nrt`: dato Near Real-Time.
    - `frp_zero`: potencia radiativa `<= 0`.
    - `island_domain`: Canarias (`x_3035 < 2_500_000`).
    - `partial_period`: fecha posterior al corte de periodo incompleto (`2026-09-01`).
- **Métricas verificadas sobre dataset real (1 km):**
  - `18.513` observaciones totales (`14.101` VIIRS + `4.412` MODIS; `14.358` SP + `4.155` NRT).
  - Rango temporal: `2026-06-01` → `2026-09-01`.
  - FRP total integrado: `950.130,31 MW`.

---

### Fase 2: Agregación Espaciotemporal `cell_day` (`phase2_cell_day.py`)
- **Entrada:** `observations.parquet`.
- **Grano:** `(cell_id_L0, date, sensor)` — mantiene los sensores separados para trazabilidad y cálculo de cocientes inter-sensor.
- **Campos generados (22 columnas / 15 bloques contractuales):**
  - `row_id` (`{cell_id}|{date}|{sensor}`), `cell_id`, `level` (`0`), `parent_ids` (`L1`, `L2`, `L3`), `cell_centroid_lonlat` (`[lon, lat]` inverso `EPSG:3035 -> EPSG:4326`), `cell_area_km2` (`1.0`).
  - `date`, `iso_year`, `iso_week`, `year_month`, `sensor`.
  - Conteos: `n_obs`, `n_day`, `n_night`, `n_platforms`, `n_high_conf`, `confidence_rank_max`.
  - Estadísticos térmicos FRP: `frp_sum_mw`, `frp_mean_mw`, `frp_max_mw`, `frp_p50_mw`.
  - Geometría y mezcla de producto: `footprint_max_km`, `product_mix` (`n_nrt / n_obs`), `flags` (incluyendo `sp_nrt_hybrid` cuando `0.05 < product_mix < 0.95`).
- **Métricas verificadas (1 km vs 5 km):**
  - A **1 km (`ES1K`)**: `8.665` registros `cell_day` (`3.564` MODIS + `5.101` VIIRS).
  - A **5 km (`ES5K`)**: `3.303` registros `cell_day` (`1.119` MODIS + `2.184` VIIRS).
  - Reconciliación matemática exacta en ambos: $\sum \text{n\_obs}_{\text{MODIS}} = 4.412$ y $\sum \text{n\_obs}_{\text{VIIRS}} = 14.101$.

---

### Fase 3a: Enriquecimiento Meteorológico (`meteomatics_client.py`)
- **Fuente:** API Meteomatics (límite de cuenta hackathon: 1.000 consultas/día, control de cuota integrado).
- **Caché:** `cache/meteomatics_cache.sqlite` (clave SHA-256 de `(param, lat, lon, start, end, interval)`, TTL 24h).
- **15 parámetros consultados en batch horario (`PT1H`):**
  - Temperatura y humedad: `t_2m:C`, `relative_humidity_2m:p`, `dew_point_2m:C`, `vapour_pressure_deficit_2m:Pa`.
  - Viento: `wind_speed_10m:ms`, `wind_dir_10m:d`, `wind_gusts_10m_1h:ms`.
  - Precipitación y radiación: `precip_1h:mm`, `precip_24h:mm`, `global_rad:W/m2`.
  - Índices de peligro de incendio: `fire_weather_index:idx` (FWI), `haines_index:idx`, `fosberg_index:idx`.
  - Suelo: `soil_moisture_0_10cm:m3/m3`, `soil_temp_0_10cm:C`.

---

### Fase 3b (Parte 1): Enriquecimiento de Vegetación y Combustible (`vegetation_client.py`)
- **Fuentes combinadas:**
  1. **ESA WorldCover 2021 v100 (10 m):** Cloud-Optimized GeoTIFF (COG) público en AWS S3 (`s3://esa-worldcover/v100/2020/map/`). Mapea 11 clases de cobertura a inflamabilidad `1..5`:
     - `20 Shrubland` (matorral): **5** (muy alta)
     - `10 Tree cover` (bosque): **4** (alta)
     - `30 Grassland` / `95 Mangroves`: **3** (media)
     - `40 Cropland` / `60 Bare/sparse` / `90 Wetland`: **2** (baja)
     - `50 Built-up` / `70 Snow/ice` / `80 Water` / `100 Moss/lichen`: **1** (nula/muy baja)
  2. **MITECO IFN3 (Inventario Forestal Nacional 3, WMS):** Consulta `GetFeatureInfo` con 21 especies forestales mapeadas (*Pinus halepensis*=5, *Pinus pinaster*=5, *Eucalyptus sp.*=5, *Cistus sp.*=5, *Ulex sp.*=5, *Quercus ilex*=4, *Quercus suber*=4, etc.).
- **Métrica combinada:** `combined_flammability = max(worldcover_flammability, ifn3_max_flammability)` en escala `1..5`.
- **Caché:** `cache/vegetation_cache.sqlite`.

---

### Fase 3b (Parte 2): Memoria Hídrica y Sequía (`rainfall_client.py`)
- **Fuente:** **NASA POWER API** (`https://power.larc.nasa.gov/api/temporal/daily/point`), gratuita, sin API key, cobertura global desde 1983.
- **Parámetros descargados (ventana de 90 días previos a la fecha del incendio):**
  - `PRECTOTCORR` (mm/día), `T2M`, `T2M_MAX`, `T2M_MIN`, `RH2M`, `WS2M`, `WD2M`, `ALLSKY_SFC_SW_DWN`.
- **7 métricas hidrometeorológicas calculadas por celda-día:**
  - `days_since_rain_1mm`: Días consecutivos desde la última lluvia $\ge 1\text{ mm}$.
  - `days_since_rain_10mm`: Días consecutivos desde la última lluvia significativa $\ge 10\text{ mm}$.
  - `precip_7d_mm`, `precip_30d_mm`, `precip_90d_mm`: Precipitación acumulada en 7, 30 y 90 días.
  - `dry_spell_max_days`: Mayor racha seca consecutiva ($< 1\text{ mm}$) en los últimos 90 días.
  - `rain_days_30d`: Número de días con lluvia $\ge 1\text{ mm}$ en el último mes.
- **Caché:** `cache/rainfall_cache.sqlite`.

---

### Fase 3b (Parte 3): Algoritmo de Puntuación y Decisión (`scoring_client.py`)
- **Funciones principales:** `valen_compute_score(features, weights)` y `valen_decide(score, thresholds)`.
- **12 Features normalizadas en `[0, 1]` y sus pesos:**

| Feature | Fuente | Normalización | Peso |
|---|---|---|---|
| `sensor_count` | `cell_day` | `minmax(1..3)` (`1=MODIS`, `2=VIIRS`, `3=BOTH`) | **0.20** |
| `confidence_rank_max` | `cell_day` | `minmax(0..2)` | **0.15** |
| `fwi` | `meteomatics` | `minmax(0..50)` | **0.15** |
| `wind_speed` | `meteomatics` | `minmax(0..20 m/s)` | **0.10** |
| `humidity` | `meteomatics` | `inverse_minmax(10..90 %)` | **0.10** |
| `days_since_rain_1mm` | `rainfall` | `minmax(0..30 días)` | **0.10** |
| `vegetation_flammability` | `vegetation` | `minmax(1..5)` | **0.10** |
| `n_high_conf_ratio` | `cell_day` | `minmax(0..1)` (`n_high_conf / n_obs`) | **0.05** |
| `dry_spell_max` | `rainfall` | `minmax(0..30 días)` | **0.05** |
| `precip_30d` | `rainfall` | `inverse_minmax(0..100 mm)` | **0.05** |
| `boundary_crossing` | `cell_day` | `binary(0/1)` | **0.05** |
| `product_mix_nrt` | `cell_day` | `direct(0..1)` | **0.05** |

- **Regla de decisión:**
  - `score >= 0.70` → `ACEPTA`
  - `0.30 <= score < 0.70` → `REVISAR_MANUAL`
  - `score < 0.30` → `RECHAZA`

### Fase 3d: Red Viaria de Carreteras y Caminos con OpenStreetMap (`roads_client.py` + `laea.py`)
- **Fuente oficial:** **OpenStreetMap (Overpass API)** — consulta vectorial `way["highway"]` sobre el *bounding box* WGS84 de cada bloque de `32 × 32 km` de la rejilla `ES1K`.
- **Proyección y rasterización (`laea.py`):** Proyecta la geometría de cada carretera/camino a `EPSG:3035` mediante fórmulas elipsoidales GRS80 exactas (sin depender de librerías C externas) y muestrea cada segmento cada `50 m` para asignar la longitud exacta en kilómetros a cada celda `ES1K:L0:Y{iy:05d}:X{ix:05d}`.
- **Jerarquía de vías y factores de velocidad para LUCIA (`HIGHWAY_CLASSES`):**
  - `major` (`motorway`, `trunk`, `primary`): factor humano `0.40–0.50` (avance rápido); `motorway`/`trunk` marcan `motorway_barrier = True` para fauna/ganado (factor animal `1.20–1.40` por vallado perimetral).
  - `secondary` (`secondary`, `tertiary`): factor humano `0.50–0.58`, factor animal `0.90–0.95`.
  - `local` (`unclassified`, `residential`, `service`): factor humano `0.60–0.65`, factor animal `0.85–1.00`.
  - `track` (pistas forestales y caminos agrícolas): factor humano `0.72`, factor animal `0.78`.
  - `path` (`path`, `footway`, `bridleway`, `cycleway`): factor humano `0.82–0.85`, factor animal `0.78–0.85`.
- **Caché y salida:**
  - Caché SQLite persistente por *bounding box*: `cache/roads_cache.sqlite`.
  - Artefacto de salida consumido por **LUCIA**: `output/cell_roads.json` (`road_length_km`, `road_access_score` $\in [0, 1]$, `best_highway_class`, `human_speed_factor`, `animal_speed_factor`, `motorway_barrier`).

### Fase 3e: Elevación y Pendiente Topográfica con Open-Elevation (`elevation_client.py`)
- **Fuente oficial:** **Open-Elevation API** (`https://api.open-elevation.com/api/v1/lookup`) — consulta por lotes (`POST`, 256 centroides WGS84 por petición) la altitud sobre el nivel del mar (`elevation_m`) de cada celda `ES1K`.
- **Resiliencia hipsométrica:** Si Open-Elevation está temporalmente inaccesible o sin red, utiliza un modelo hipsométrico continuo $C^1$ de las cordilleras ibéricas (`estimate_iberian_elevation_m`) para garantizar pendientes suaves y realistas entre celdas vecinas.
- **Métricas de pendiente y función de Tobler para LUCIA:**
  - `elevation_m`: Altitud sobre el nivel del mar (metros).
  - `slope_deg` y `slope_pct`: Pendiente media respecto a las 8 celdas vecinas.
  - `max_delta_elev_m` y `max_uphill_delta_m`: Mayor desnivel absoluto y de subida en las 8 direcciones.
  - `tobler_hiking_speed_kmh(slope_ratio)` y `compute_slope_cost_multiplier(delta_z, dist_m, profile)`: Multiplicador físico direccional ($\Delta z$) aplicado en cada transición del A\* de **LUCIA**.
- **Caché y salida:**
  - Caché SQLite persistente por celda: `cache/elevation_cache.sqlite`.
  - Artefacto de salida consumido por **LUCIA**: `output/cell_elevation.json`.

---

## 4. Comandos de Ejecución del Pipeline VALEN

```bash
cd backend/app/valen

# 1. Fase 1: Proyección EPSG:3035 y asignación de celdas L0-L3 (1000 m)
../../.venv/bin/python phase1_projection.py \
  --input /ruta/a/firms_jsons \
  --output output --cell-size 1000

# 2. Fase 2: Agregación por celda-día-sensor
../../.venv/bin/python phase2_cell_day.py \
  --input output/observations.parquet \
  --output output --cell-size 1000

# 3a. Enriquecimiento meteorológico (Meteomatics)
../../.venv/bin/python meteomatics_client.py \
  --username USUARIO --password PASSWORD \
  --cell-day output/cell_day.parquet \
  --output output/cell_day_meteo.json

# 3b. Enriquecimiento de vegetación (ESA WorldCover + IFN3)
../../.venv/bin/python vegetation_client.py \
  --cell-day output/cell_day.parquet \
  --output output/cell_day_vegetation.json

# 3c. Enriquecimiento de lluvia y sequía (NASA POWER)
../../.venv/bin/python rainfall_client.py \
  --cell-day output/cell_day.parquet \
  --output output/cell_day_rainfall.json --lookback 90

# 3d. Enriquecimiento de carreteras y caminos (OpenStreetMap Overpass API)
../../.venv/bin/python roads_client.py \
  --from-cata ../cata/artifacts/predictions/cata_predictions.json \
  --output output/cell_roads.json

# 4. Puntuación y validación final (VALEN)
../../.venv/bin/python scoring_client.py \
  --cell-day output/cell_day.parquet \
  --output output/validated_cell_day.parquet \
  --json-output output/validated_cell_day.json \
  --meteo output/cell_day_meteo.json \
  --veg output/cell_day_vegetation.json \
  --rain output/cell_day_rainfall.json
```
