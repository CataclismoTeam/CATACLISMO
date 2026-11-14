# Nota para el Agente de IA de Frontend (Integración GeoJSON 3D de LUCIA + Open-Elevation + Puntos de Encuentro)

> [!IMPORTANT]
> **Contexto para el Agente de IA de Frontend:**
> Este documento especifica el contrato exacto de salida de la pipeline **VALEN -> CATA -> LUCIA** para que puedas integrarlo directamente en el visor 3D/2D del frontend (`CesiumJS` y/o `@deck.gl/layers`, ambos ya instalados en `frontend/package.json`).

---

## 1. Resumen de la Pipeline (`VALEN -> CATA -> LUCIA`)

1. **VALEN (`backend/app/valen/`)**: Valida las detecciones satelitales (MODIS/VIIRS) sobre la rejilla europea `ES1K` (1 km × 1 km) y las enriquece con:
   - Meteorología (FWI, viento, humedad, temperatura), sequía/precipitación y vegetación (ESA WorldCover + IFN3).
   - **Carreteras y caminos (`roads_client.py` — OpenStreetMap Overpass API)**.
   - **Elevación y pendiente topográfica (`elevation_client.py` — Open-Elevation API)**.
2. **CATA (`backend/app/cata/`)**: Red neuronal **ConvLSTM** de 22 canales que predice la propagación del fuego en `t+1` y distingue entre zonas **ya quemadas** (`F`), **quemándose activamente** (`B`), **predicción de nuevo fuego** (`P`) y **sin quemar** (`.`).
3. **LUCIA (`backend/app/lucia/`)**: Modelo neuronal modular en **TensorFlow/Keras** (`lucia_c15.keras`, 15 canales) + planificador **A\* espacio-temporal con pendiente direccional ($\Delta z$, función de Tobler)** que calcula el camino más corto y seguro hacia un **Punto de Encuentro explícito (`meeting_point`)**, respetando un **threshold seguro al fuego (`safe_fire_threshold = 0.25`)** y exportando geometrías **GeoJSON 3D (`[lon, lat, elevation_m]`)**.

---

## 2. Endpoints API REST disponibles (`backend/app/main.py`)

### 1. `GET /api/lucia/routes`
Devuelve el `FeatureCollection` GeoJSON completo con todas las rutas seguras, orígenes, **Puntos de Encuentro (`meeting_point`)** y polígonos de fuego:
- Query params opcionales:
  - `zone_id`: filtra una zona específica (ej. `ES1K_block_110_179_2026-08-12`).
  - `profile`: `"human"` | `"animal"` | `"both"` (por defecto `"both"`).
  - `safe_fire_threshold`: `float` en `[0.05, 0.95]` (por defecto `0.25`).
  - `include_fire_polygons`: `bool` (por defecto `true`).

### 2. `GET /api/lucia/meeting-points`
Devuelve únicamente los `Feature` de tipo **`"meeting_point"`** (Puntos de Encuentro oficiales seguros con su altitud, acceso por carretera y capacidad).

### 3. `POST /api/lucia/route`
Calcula en tiempo real la ruta de escape desde cualquier punto `[lon, lat]` clicado en el mapa hacia el **Punto de Encuentro** más seguro (permitiendo además enviar Puntos de Encuentro personalizados):
```json
{
  "lon": -6.5412,
  "lat": 37.4521,
  "profile": "human",
  "safe_fire_threshold": 0.25,
  "meeting_points": [
    {
      "id": "pe_polideportivo",
      "name": "Punto de Encuentro Polideportivo Municipal",
      "lon": -6.582,
      "lat": 37.512,
      "kind": "official_assembly_point",
      "capacity": 600
    }
  ]
}
```
*(El campo `meeting_points` es opcional; si no se envía, LUCIA dirige la ruta hacia los Puntos de Encuentro oficiales seguros de la zona).*

---

## 3. Estructura del GeoJSON (`FeatureCollection` 3D)

Todas las coordenadas están en **WGS84 (`EPSG:4326`)** e incluyen altitud en metros sobre el nivel del mar: **`[longitud, latitud, elevation_m]`** (ej. `[-6.567192, 37.450927, 298.5]`).

Cada elemento de `features[]` se discrimina mediante **`feature.properties.feature_type`**:

| `properties.feature_type` | `geometry.type` | Qué representa | Propiedades clave de Elevación y Punto de Encuentro |
|---|---|---|---|
| **`"evacuation_route"`** | `LineString` (3D) | Vía de escape más corta y segura hacia un Punto de Encuentro | `target_type` (`"meeting_point"`), `target_meeting_point_id`, `target_meeting_point_name`, `target_meeting_point_kind`, `target_meeting_point_lonlat`, `target_meeting_point_elevation_m`, `start_elevation_m`, `end_elevation_m`, `net_elevation_change_m`, `total_ascent_m`, `total_descent_m`, `max_slope_pct`, `elevation_profile_m` (`number[]`), `road_cells_used`, `road_share_ratio`, `highway_classes_used`, `distance_km`, `estimated_time_minutes` |
| **`"meeting_point"`** | `Point` (3D) | **Punto de Encuentro explícito** (finalidad de la ruta de evacuación) | `meeting_point_id`, `name`, `kind` (`"road_junction_assembly"` \| `"rural_track_assembly"` \| `"flat_clearing_assembly"` \| `"official_assembly_point"`), `status` (`"SAFE_ACTIVE"` \| `"COMPROMISED_BY_FIRE"`), `is_assigned_destination`, `capacity`, `elevation_m`, `slope_pct`, `best_highway_class`, `has_road_access`, `fill_color` (`#22c55e`) |
| **`"evacuation_origin"`** | `Point` (3D) | Punto de partida amenazado cerca del frente de fuego | `zone_id`, `cell_id`, `elevation_m`, `fire_probability_t1`, `distance_to_fire_km`, `stroke_color` (`#f59e0b`) |
| **`"safe_haven"`** | `Point` (3D) | Alias retrocompatible del Punto de Encuentro alcanzado | `meeting_point_id`, `meeting_point_name`, `elevation_m`, `safe_haven_score`, `fill_color` (`#22c55e`) |
| **`"fire_cell"`** | `Polygon` | Celda 1 km × 1 km quemada, quemándose o en el buffer del threshold | `fire_zone_category` (`"BURNING_ACTIVE"` \| `"ALREADY_BURNED"` \| `"THRESHOLD_BUFFER_UNSAFE"`), `elevation_m`, `fire_probability_t1`, `fill_color`, `fill_opacity` |
