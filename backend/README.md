# 🔥 CATACLISMO Backend — Arquitectura de Mando, Inteligencia y Evacuación de Incendios

> **Ecosistema Multi-Agente Táctico y Red Neuronal Espacio-Temporal**  
> *Diseñado para operar en tiempo real sobre Incendios Forestales de Alta Intensidad (GIF / Sexta Generación).*  
> *Cuadrícula Táctica Métrica Unificada `1000 × 1000 m` (`EPSG:3035` / `ES1K`) y Proyección `WGS84` (`EPSG:4326`).*

---

## 🧭 1. Manifiesto y Visión del Sistema

El backend de **CATACLISMO** es un motor integral de simulación predictiva, logística de evacuación y centro de mando táctico (C2). Integra modelos de aprendizaje profundo (Deep Learning espacio-temporal), heurísticas geoespaciales avanzadas, criptografía de extremo a extremo (E2EE), enlace con telecomunicaciones de radio de emergencia (TETRA PEI / BLE) e ingesta satelital Near Real-Time (NRT).

Para resolver el problema del fuego forestal sin fisuras arquitectónicas, el sistema delega sus responsabilidades en **4 Personalidades Especializadas** que colaboran en cadena o de manera concurrente:

```mermaid
flowchart TD
    subgraph SATELLITE_ENV["Fuentes Satelitales y Ambientales"]
        FIRMS["NASA FIRMS (MODIS / VIIRS)"]
        METEO["Meteomatics & Open-Meteo"]
        VEG["ESA WorldCover 10m + IFN3"]
        RAIN["NASA POWER (Histórico 90d)"]
        DEM["Open-Elevation & Carreteras OSM"]
    end

    subgraph PERSONALITIES["Las 4 Personalidades de CATACLISMO"]
        VALEN["🛡️ VALEN\n(Validador & Enriquecedor de Datos)\nFiltra falsos positivos y genera tensor 22 canales"]
        CATA["🔮 CATA\n(Oráculo de Propagación Neuronal)\nConvLSTM2D predice ignición en t+1 (6h)"]
        LUCIA["🧭 LUCIA\n(Estratega de Evacuación Segura)\nTensorFlow 15 canales + A* 3D + Tobler"]
        JULI["⚡ JULI\n(Comandante Táctica de Campo & C2)\nTracking GPS, Prueba de Vida, Chat E2EE & TETRA/BLE"]
    end

    subgraph CLIENTS["Frontend & First Responders"]
        MAP["Mapa Web / Deck.gl / CesiumJS"]
        CENTRAL["Puesto de Mando Avanzado (PMA)"]
        BRIGADES["Brigadistas y Unidades de Terreno"]
    end

    FIRMS & METEO & VEG & RAIN --> VALEN
    VALEN -->|validated_cell_day / 22 canales| CATA
    CATA -->|cata_predictions.json| LUCIA
    DEM --> LUCIA
    CATA -.->|Perímetro activo y avance| JULI
    LUCIA -->|lucia_routes.geojson / Puntos de Encuentro| MAP
    JULI <-->|REST + WS /ws/tracking, /ws/chat, /ws/radio| BRIGADES & CENTRAL
    JULI -->|Feedback de campo sin reentrenar| CONTINUAL["🧠 CONTINUAL ENGINE\n(Memoria Adaptativa EMA)"]
    CONTINUAL -.->|Calibración dinámica| CATA & LUCIA
```

---

## 🎭 2. Las 4 "Personalidades" de CATACLISMO

Cada personalidad posee un rol funcional estricto, una misión operativa, un pipeline algorítmico y una interfaz contractual definida.

---

### 2.1 🛡️ VALEN — El Cartógrafo Riguroso y Validador de Datos
*Módulo:* [`app/valen/`](app/valen/) • *Identificador:* `ALGORITHM_NAME = "valen"`

> *"No todo lo que brilla en el satélite es fuego. Antes de movilizar una brigada o alertar a una población, cada píxel térmico debe contrastarse contra la física de la atmósfera, la sequedad del suelo y el combustible vegetal."*

#### Perfil y Misión Operativa
VALEN es el primer eslabón de la cadena. Los sensores satelitales (MODIS en satélites Terra/Aqua y VIIRS en Suomi-NPP/NOAA-20/NOAA-21) capturan anomalías térmicas (*hotspots*), pero sufren de abundantes falsos positivos: chimeneas industriales, quemas agrícolas autorizadas, reflejos solares en láminas de agua o paneles fotovoltaicos y ruido de calibración. VALEN limpia, estandariza, enriquece y califica cada detección antes de que entre al pipeline de predicción.

#### Capacidades y Superpoderes Técnicos
1. **Streaming & Proyección LAEA (`phase1_projection.py`):**
   - Ingiere extractos masivos de NASA FIRMS en streaming (archivos `.json` de archivo y NRT).
   - Proyecta cada punto lat/lon a la cuadrícula europea estándar **ETRS89-LAEA (`EPSG:3035`)**, asignando la celda base métrica de 1 km² (`ES1K:L0:Y{iy}:X{ix}`).
2. **Agregación Reconciliada (`phase2_cell_day.py`):**
   - Agrupa detecciones por `(cell_id, date, sensor)` en ventanas de 6 horas (`cell_6h`) y días completos (`cell_day`), computando potencias radiativas (`frp_sum`, `frp_max`, `frp_mean`), dispersión espacial y recuento de plataformas.
3. **Enriquecimiento Multi-Fuente con Caché SQLite Persistente:**
   - **Meteorología Horaria ([`meteomatics_client.py`](app/valen/meteomatics_client.py)):** 15 parámetros (Fire Weather Index - FWI, velocidad/dirección/rachas de viento, humedad relativa, temperatura a 2m, índices Haines y Fosberg, radiación solar).
   - **Inflamabilidad Vegetal ([`vegetation_client.py`](app/valen/vegetation_client.py)):** Cruce espacial con ESA WorldCover 10m (11 coberturas) y el Tercer Inventario Forestal Nacional de España (MITECO IFN3, 21 especies arbóreas), transformado en una escala unificada de inflamabilidad `1..5`.
   - **Historial Hídrico y Sequía ([`rainfall_client.py`](app/valen/rainfall_client.py)):** Ventana histórica de 90 días de NASA POWER con conteo de días consecutivos sin lluvia ($\ge 1\text{ mm}$ y $\ge 10\text{ mm}$), precipitación acumulada a 7/30/90 días y racha seca máxima (`dry_spell_max_days`).
   - **Topografía y Pendientes ([`elevation_client.py`](app/valen/elevation_client.py)):** Consultas a Open-Elevation para altitud y gradiente.
   - **Red de Accesibilidad ([`roads_client.py`](app/valen/roads_client.py)):** Densidad de viales primarios, secundarios y pistas forestales de OpenStreetMap.
4. **Scoring Ponderado y Decisión Automática ([`scoring_client.py`](app/valen/scoring_client.py)):**
   - Evalúa 12 variables normalizadas mediante pesos configurables y emite una decisión estricta:
     - `ACEPTA` ($\ge 0.70$): Foco real confirmado de alta virulencia.
     - `REVISAR_MANUAL` ($0.30 - 0.70$): Anomalía térmica plausible sujeta a validación o falta de variables secundarias.
     - `RECHAZA` ($< 0.30$): Falso positivo descartado automáticamente.

#### Contrato de Salida
Genera `validated_cell_day.parquet` / `.json` con el tensor contractual de **22 canales** que consume CATA.

---

### 2.2 🔮 CATA — El Oráculo Predictivo de Propagación Neuronal
*Módulo:* [`app/cata/`](app/cata/) • *Identificador:* `ALGORITHM_NAME = "cata"`

> *"Comprendo la inercia del fuego. Leyendo la atmósfera, el combustible seco y el viento sobre las montañas, anticipo dónde morderán las llamas en las próximas 6 horas."*

#### Perfil y Misión Operativa
CATA es el cerebro predictivo profundo de CATACLISMO. Modela la propagación del frente de fuego a través del espacio y el tiempo mediante redes neuronales convolucionales recurrentes (`ConvLSTM2D`), generando mapas de probabilidad de avance, tiempos estimados de llegada y costes de paso diferenciados.

#### Capacidades y Superpoderes Técnicos
1. **Núcleo `ConvLSTM2D` (`model.py`, `cata_c22.keras`):**
   - Recibe una ventana temporal táctica de **5 pasos de 6 horas** ($5 \times 6\text{h} = 30\text{h}$ de contexto) en turnos tácticos (`00:00`, `06:00`, `12:00`, `18:00` UTC).
   - Tensor de entrada: `(Batch, Time=5, Height=64, Width=64, Channels=22)`.
2. **Los 22 Canales de Entrada (`CHANNEL_REGISTRY`):**
   - `0..12` (13): Métricas satelitales (`frp_sum`, `frp_max`, `n_obs`, `n_high_conf`, `footprint_max`, `confidence_rank`, etc.).
   - `13..16` (4): Meteorología VALEN (`meteo_fwi`, `meteo_wind_speed`, `meteo_humidity_inv`, `meteo_temp`).
   - `17..19` (3): Sequía y lluvia (`rain_days_since_1mm`, `rain_dry_spell_max`, `rain_precip_30d_inv`).
   - `20..21` (2): Combustible vegetal (`veg_flammability`) y `valen_score`.
3. **Discriminación Cuadrante a Cuadrante (Real vs Predicho):**
   Para evitar que el personal de emergencia confunda observaciones reales de satélite con hipótesis del modelo, CATA clasifica cada cuadrante en 4 estados unívocos:
   - `0` (`SAFE` / `.`): Cuadrante seguro, sin fuego observado ni predicho.
   - `1` (`PREDICTED_FIRE` / `P`): **Cuadrante PREDICT**. Predicho por CATA en $t+1$ (ignición inminente, no quemado de verdad aún).
   - `2` (`CONFIRMED_BURNED` / `F`): **Quemado de verdad**. Confirmado por satélite en $\le t$.
   - `3` (`CONFIRMED_AND_CONTINUES` / `B`): **Quemado de verdad** que persiste ardiendo activamente en $t+1$.
4. **Channel Surgery y Fine-Tuning en Caliente:**
   - Permite expandir modelos entrenados con menos canales ($C=1 \rightarrow C=22$) preservando pesos previos mediante `expand_model_channels()`.

#### Contrato de Salida
Exporta `cata_predictions.json`, que contiene las matrices 2D por zona (`fire_probability_grid`, `estimated_fire_arrival_hours`, `human_traversal_cost_grid`, `animal_traversal_cost_grid`) y la lista georreferenciada de cuadrantes activos y predichos.

---

### 2.3 🧭 LUCIA — La Estratega de Evacuación Segura y Vías de Salvamento
*Módulo:* [`app/lucia/`](app/lucia/) • *Identificador:* `ALGORITHM_NAME = "lucia"`

> *"Bajo el fuego y el pánico no hay lugar para la improvisación. Calculo el camino más rápido y seguro hacia un refugio antes de que el humo o las llamas corten las vías de escape, distinguiendo el paso de personas del de los animales."*

#### Perfil y Misión Operativa
LUCIA es el motor de logística, supervivencia y cálculo de itinerarios de evacuación. Combina una red neuronal convolucional de 15 canales en TensorFlow (`lucia_c15.keras`) con un algoritmo **A\* tridimensional ponderado** que respeta la topografía real, el comportamiento convectivo del fuego y las restricciones de la red de caminos.

#### Capacidades y Superpoderes Técnicos
1. **Red Neuronal de 15 Canales (`model.py`):**
   - Fusiona la probabilidad de fuego de CATA con la inflamabilidad vegetal, viento, FWI, accesibilidad viaria de OSM y gradientes de elevación.
   - Genera tensores normalizados de riesgo: `human_risk_field`, `animal_risk_field` y `safe_haven_score`.
2. **Dinámica Física y Función de Marcha de Tobler Modificada:**
   - En cada transición entre cuadrantes vecinos $(r, c) \rightarrow (nr, nc)$, calcula el desnivel $\Delta z = z_{nr,nc} - z_{r,c}$ (en metros, vía Open-Elevation).
   - Aplica la función de Tobler para velocidad de marcha a pie penalizando ascensos y descensos escarpados.
   - **Penalización Convectiva por "Efecto Chimenea":** Si la evacuación sube pendiente arriba ($\Delta z > 5\text{ m}$) en las inmediaciones de un frente de fuego activo, aplica un factor de coste exponencial debido al ascenso acelerado del aire caliente y gases tóxicos.
3. **Perfiles Diferenciados de Evacuación:**
   - `human`: Prioriza pistas transitables y carreteras OSM, penaliza densidades de maleza y pendientes elevadas.
   - `animal` (fauna y ganado): Capaz de transitar campo a través, tolera menores anchos de vía pero evita barrancos abruptos y focos ruidosos.
4. **Puntos de Encuentro Explícitos (`meeting_points`):**
   - Cada ruta tiene un objetivo táctico claro: alcanzar un punto seguro catalogado (albergues, helisuperficies, polideportivos, cruces viarios despejados), autodesignado por el sistema o suministrado interactivamente por el usuario (`POST /api/lucia/route`).
5. **Filtrado Térmico y Threshold de Seguridad (`SAFE_FIRE_THRESHOLD = 0.25`):**
   - Bloqueo total intransitable de celdas `BURNING_ACTIVE` (estados 1 y 3).
   - Bloqueo por defecto de celdas `ALREADY_BURNED` (estado 2) por brasas, humo denso y riesgo de caída de arbolado.
   - Bloqueo de zonas no quemadas que superen el threshold seguro de radiación (`THRESHOLD_BUFFER_UNSAFE`).

#### Contrato de Salida
Genera `lucia_routes.geojson` con coordenadas 3D `[lon, lat, elevation_m]`, perfiles longitudinales de altimetría (`total_ascent_m`, `total_descent_m`, `max_slope_pct`) y geometrías poligonales de áreas de peligro.

---

### 2.4 ⚡ JULI — La Comandante Táctica de Campo, Mando y Control (C2)
*Módulo:* [`app/juli/`](app/juli/) • *Identificador:* `ALGORITHM_NAME = "juli"`

> *"Tengo ojos sobre cada brigadista, cada autobomba y cada dron en el frente. Si un operario deja de moverse o las llamas lo cercan, la alarma suena en el acto. Las órdenes van cifradas de extremo a extremo y la frecuencia de radio cambia con un solo clic."*

#### Perfil y Misión Operativa
JULI es el sistema de control táctico de operaciones de campo para **First Responders** (bomberos, sanitarios, pilotos de drones y UME). Es completamente independiente del pipeline predictivo (puede correr en modo *standalone*), pero se acopla a CATA para monitorizar el peligro inminente sobre las unidades desplegadas.

#### Capacidades y Superpoderes Técnicos
1. **Sistema de Coordenadas Dual (Macro-Cuadrante + Subcoordenadas Métricas):**
   - Localiza a cada efectivo en el cuadrante unificado de 1 km² (`ES1K:L0:Y{iy}:X{ix}`) y simultáneamente computa su posición submétrica: `offset_x_m`, `offset_y_m` $\in [0, 1000)\text{ m}$, subcoordenadas normalizadas `sub_x_norm`, `sub_y_norm` $\in [0, 1)$, subrejilla de 100 m (`sub_100m_rc`) y subcelda de 10 m (`sub_10m_rc`).
   - Permite representar en pantalla formaciones tácticas, centroides de cuadrilla y vectores de movimiento con precisión de decímetros.
2. **Prueba de Vida Inteligente (*Dead-Man Sentinel*):**
   - Supervisor asíncrono en segundo plano (`_proof_of_life_monitor`) que audita a cada operario activo cada 30 segundos.
   - **Disparo de Alerta Inmediata:** Si un operario permanece inmóvil $\ge 15\text{ minutos}$ (distancia recorrida $< 5\text{ m}$) o si el cuadrante en el que se encuentra entra en ignición/fuego persistente según CATA (`states 1, 2, 3`).
   - **Emisión Multicanal:** Emite de inmediato el evento `proof_of_life_alert` por WebSocket a **Central** y al **canal de chat de su escuadrón**, destacando su `last_location` exacta, estado biométrico y nivel de batería.
3. **Chat Táctico Cifrado E2EE con Supervisión "Gran Hermano" para Central:**
   - **Criptografía Real:** Intercambio de claves ECDH sobre curva NIST P-256, huellas de clave RFC 7638, códigos de verificación visual (`safety_code`), sobres cifrados en AES-256-GCM y derivación PBKDF2. Rechazo absoluto de claves privadas en el servidor.
   - **Topología de Canales:** Canales directos (`dm:a:b`), canales de escuadrón (`team:{id}`) y canal general por defecto (`global:operativo`).
   - **Modo Central Orwelliano:** El Puesto de Mando (`central`) tiene acceso criptográfico y auditoría en tiempo real sobre la totalidad de los canales de la operación.
4. **Antivirus & Sanitización Binaria de Adjuntos (CDR - *Content Disarm & Reconstruction*):**
   - Inspección rigurosa de imágenes (`PNG`, `JPEG`, `WEBP`, `GIF`) y documentos `PDF` antes de su distribución:
     - Verificación estricta de **Magic Bytes** y rechazo de extensiones engañosas.
     - Bloqueo de ejecutables embebidos, polyglots, zip-bombs y formatos vulnerables (`SVG`, `HTML`).
     - Análisis estructural de PDFs bloqueando tags maliciosos (`/JS`, `/JavaScript`, `/Launch`, `/OpenAction`, `/EmbeddedFiles`, `/Encrypt`), incluso si están ofuscados en hexadecimal (`#2f4a53`) o dentro de flujos comprimidos `FlateDecode`.
     - Recodificación completa de imágenes en memoria con Pillow eliminando metadatos EXIF sensibles antes de guardarlas en disco.
5. **Pasarela Walkie-Talkie BLE GATT + TETRA PEI (`ETSI TS 100 392-5`):**
   - Enlace entre terminales móviles y walkie-talkies profesionales (SIRDEE / TETRA / DMR).
   - Decodifica comandos AT estándar: `AT+CTGS=` (selección de talkgroup), `AT+CFREQ=` (cambio de frecuencia RF), `AT+CTSG=`, `AT+CNUMF?`, `AT+CTGLIST?`, `AT+CSCAN`.
   - **Sincronización Atómica de Escuadrón:** Cuando un operario conmuta de frecuencia/canal en su walkie (o mediante simulación en la app), JULI reasigna **automáticamente y en un único paso atómico** al operario a su nuevo escuadrón en la base de datos, actualizando su GeoJSON, sus grupos de chat E2EE y su supervisor de prueba de vida sin requerir intervención manual de Central.

---

## 🏗️ 3. Módulos Satélite y Conectividad Transversal

### 🧠 Continual Learning Engine (`app/continual/`)
Permite calibrar y adaptar en caliente las predicciones de CATA y los costes de LUCIA sin incurrir en reentrenamientos costosos de redes neuronales:
- **Feedback de Campo Directo:** Las brigadas o Central pueden enviar reportes (`POST /api/continual/feedback`) confirmando fuego real no detectado (`confirmed_fire`) o desestimando falsas alarmas (`false_alarm`).
- **Memoria Adaptativa EMA:** Ajusta multiplicadores de calibración por bloque espacial (`ES1K_block_...`) mediante medias móviles exponenciales y gestiona un búfer de repetición (*replay buffer*) para prevenir el olvido catastrófico.

### 🛰️ Live NRT Ingestion Engine (`app/live_nrt.py`)
Automatiza el flujo continuo de datos en tiempo real:
- Consulta a la API Near Real-Time de NASA FIRMS sobre la Península Ibérica y el sur de Europa.
- Descarga en directo la meteorología de Open-Meteo para las coordenadas detectadas.
- Ensambla el feed `cell_day_live.json`, ejecuta la inferencia en CATA y genera automáticamente las rutas de evacuación actualizadas en LUCIA, notificando a los clientes mediante el evento WebSocket `live_nrt_updated`.

### 🌐 WebSocket Event Nexus (`app/ws.py` + `app/juli/main.py`)
Hub de comunicación bidireccional asíncrona:
- `/ws`: Eventos de sistema, avisos de prueba de vida, actualizaciones NRT y alertas globales de cambio de escuadrón.
- `/ws/tracking`: Telemetría viva de operarios y unidades sobre el perímetro activo cada 2 segundos.
- `/ws/chat`: Mensajería táctica cifrada E2EE, entrega de claves y acuses de recibo (`delivered`, `read`).
- `/ws/radio`: Eventos de telecomunicaciones, conmutación de frecuencias TETRA y telemetría de batería/cobertura RF.

---

## 🗺️ 4. La Cuadrícula Táctica Unificada: `EPSG:3035` (`ES1K`)

Trabajar directamente en coordenadas angulares geográficas (`WGS84`, grados de latitud/longitud) introduce deformaciones inaceptables al calcular distancias euclidianas, velocidad de frentes de llama y áreas de cuadrícula en latitudes europeas (un grado de longitud en España no mide lo mismo que en el ecuador).

Por ello, todo el backend de CATACLISMO opera sobre la proyección métrica oficial de la Unión Europea:

$$\text{Proyección: } \mathbf{EPSG:3035} \quad (\text{ETRS89 / LAEA Europe})$$

### Estándar del Cuadrante L0 (`1000 × 1000 m`)
- **Tamaño de celda:** $1000.0\text{ m} \times 1000.0\text{ m}$ ($1\text{ km}^2$, `CELL_SIZE_M = 1000.0`).
- **Nivel jerárquico base:** Nivel `L0`.
- **Formato canónico del Identificador de Cuadrante:**
  $$\mathbf{ES1K:L0:Y\{iy:05d\}:X\{ix:05d\}}$$
  donde:
  $$ix = \lfloor x_{3035} / 1000.0 \rfloor, \quad iy = \lfloor y_{3035} / 1000.0 \rfloor$$
- **Centroide de la celda:**
  $$x_{\text{center}} = (ix + 0.5) \times 1000.0, \quad y_{\text{center}} = (iy + 0.5) \times 1000.0$$
  El centroide se proyecta a `WGS84` (`lon, lat`) en todas las respuestas GeoJSON hacia el Frontend.

### Subcoordenadas Métricas de Precisión (JULI)
Dentro de cada cuadrante de $1\text{ km}^2$, un efectivo u operario se desglosa en:
- `offset_x_m`, `offset_y_m`: Distancia euclidiana en metros $[0, 1000)\text{ m}$ desde la esquina inferior izquierda del cuadrante.
- `sub_x_norm`, `sub_y_norm`: Coordenadas normalizadas $[0.0, 1.0)$.
- `sub_100m_rc`: Fila y columna $[0..9, 0..9]$ en una subrejilla interna de $100\text{ m}$.
- `sub_10m_rc`: Fila y columna $[0..99, 0..99]$ en una subrejilla métrica de $10\text{ m}$.

---

## 📡 5. Catálogo Completo de la API REST y WebSockets

### 5.1 Pipeline Central, Predicciones y Evacuación (CATA & LUCIA)

| Método | Endpoint | Descripción | Parámetros / Body |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Chequeo de salud del backend, versión de PostGIS y estado del pipeline. | Ninguno |
| `GET` | `/api/cata/predictions` | Devuelve `cata_predictions.json` completo (matrices de fuego, tiempos de llegada y costes). | Ninguno |
| `GET` | `/api/lucia/routes` | GeoJSON (`FeatureCollection`) con rutas de evacuación seguras y polígonos de fuego. | `zone_id`, `profile` (`human`\|`animal`\|`both`), `safe_fire_threshold` |
| `POST` | `/api/lucia/route` | Calcula al vuelo una ruta segura interactiva hacia un Punto de Encuentro. | `LuciaRouteRequest` (`lon`/`lat` o `quadrant_id`, `profile`, `meeting_points`) |
| `GET` | `/api/lucia/meeting-points` | Lista los Puntos de Encuentro activos y refugios seguros de la zona. | `zone_id` opcional |
| `GET` | `/api/continual/status` | Estado del motor de aprendizaje continuo (bloques espaciales y calibraciones). | Ninguno |
| `POST` | `/api/continual/feedback` | Registra confirmación de fuego o falsa alarma desde el terreno. | `ContinualFeedbackInput` (`zone_or_block_id`, `feedback_type`, `intensity`) |
| `GET` | `/api/live/status` | Estado de la última sincronización con NASA FIRMS NRT. | Ninguno |
| `POST` | `/api/live/refresh` | Dispara ciclo NRT en vivo (descarga FIRMS, infiere CATA, actualiza LUCIA). | `days` (1..10, default 2) |

---

### 5.2 Mando, Unidades y Prueba de Vida (JULI Tracker)

| Método | Endpoint | Descripción | Parámetros / Body |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/units` | Unidades de primera intervención simuladas sobre el perímetro de CATA. | Ninguno |
| `POST` | `/api/units/sync-fire` | Reancla las unidades activas tras un cambio de fecha/frente en CATA. | Ninguno |
| `POST` | `/api/units/{unit_id}/sos` | Fuerza el estado de SOS sobre una unidad táctica. | Path `unit_id` |
| `GET` | `/api/juli/geojson` | GeoJSON completo de operarios, centroides de equipo y líneas de formación táctica. | `team_id`, `status`, `include_team_features` |
| `GET` | `/api/juli/teams` | Listado estructurado de equipos, canales de radio asignados y sus miembros. | Ninguno |
| `POST` | `/api/juli/teams` | Crea o actualiza un equipo de intervención en JULI. | `JuliTeamInput` |
| `POST` | `/api/juli/operators` | Añade o actualiza un operario (por WGS84 o por `quadrant_id` + subcoordenadas). | `JuliOperatorInput` |
| `PATCH` | `/api/juli/operators/{id}/location` | Actualiza la posición GPS/biométrica en tiempo real y emite por WebSocket. | `JuliLocationPatchInput` |
| `DELETE` | `/api/juli/operators/{id}` | Da de baja a un operario de la operación. | Path `operator_id` |
| `GET` | `/api/juli/proof-of-life` | Estado de Prueba de Vida de todos los operarios (inmovilidad, cuadrante ardiendo). | Ninguno |
| `POST` | `/api/juli/operators/{id}/proof-of-life` | Resolución o confirmación manual de prueba de vida enviada por el operario. | `ProofOfLifeConfirmInput` |
| `POST` | `/api/juli/proof-of-life/check` | Fuerza una auditoría inmediata de prueba de vida y difunde alertas nuevas. | `immobile_seconds` (default 900) |

---

### 5.3 Mensajería Táctica Cifrada E2EE y Sanitización de Adjuntos (JULI Chat)

| Método | Endpoint | Descripción | Parámetros / Body |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/juli/chat/crypto-spec` | Especificación criptográfica del sistema (curvas NIST P-256, esquemas AES-GCM). | Ninguno |
| `POST` | `/api/juli/chat/keys` | Registra la clave pública ECDH/ECDSA P-256 de un participante (`central` u operario). | `ChatIdentityKeyInput` |
| `GET` | `/api/juli/chat/keys` | Directorio de claves públicas de todos los participantes activos. | Ninguno |
| `GET` | `/api/juli/chat/keys/{id}` | Clave pública activa y huella digital RFC 7638 de un participante. | Path `participant_id` |
| `GET` | `/api/juli/chat/safety-code` | Código visual de seguridad numérico para verificación fuera de banda entre dos claves. | `key1`, `key2` |
| `GET` | `/api/juli/chat/channels` | Lista de canales accesibles por el participante (`global:operativo`, escuadrones, DMs). | `participant_id` |
| `POST` | `/api/juli/chat/channels/direct` | Abre o recupera un canal directo 1-a-1 cifrado entre dos miembros. | `ChatDirectChannelInput` |
| `POST` | `/api/juli/chat/attachments` | Sube y desinfecta (CDR) un adjunto (imagen o PDF), validando magic bytes y eliminando malware. | `UploadFile` (multipart/form-data) |
| `GET` | `/api/juli/chat/attachments/{id}` | Descarga un adjunto previamente sanitizado. | Path `attachment_id` |
| `POST` | `/api/juli/chat/messages` | Envía un mensaje cifrado E2EE con soporte de acuse e idempotencia `client_msg_id`. | `ChatMessageInput` |
| `GET` | `/api/juli/chat/messages` | Recupera el historial de mensajes cifrados de un canal. | `channel_id`, `since_seq`, `limit` |
| `POST` | `/api/juli/chat/messages/ack` | Emite acuse de entrega o de lectura (`delivered` / `read`). | `ChatAckInput` |

---

### 5.4 Pasarela Walkie-Talkie BLE GATT y TETRA PEI (JULI Radio)

| Método | Endpoint | Descripción | Parámetros / Body |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/juli/radio/protocol` | Especificación del protocolo BLE GATT (UUIDs de servicio/características) y comandos AT TETRA. | Ninguno |
| `GET` | `/api/juli/radio/frequencies` | Plan de frecuencias de radio asignadas por equipo (VHF, TETRA, Talkgroup ID, CTCSS). | Ninguno |
| `GET` | `/api/juli/radio/operators/{id}` | Estado de radiofrecuencia actual del operario (frecuencia, canal, escuadrón, señal). | Path `operator_id` |
| `GET` | `/api/juli/radio/history` | Historial de conmutaciones de radio y comandos PEI procesados. | `limit` (1..100) |
| `POST` | `/api/juli/radio/switch` | Solicita cambio de canal de radio y reasigna automáticamente al operario a ese escuadrón. | `RadioSwitchRequest` |
| `POST` | `/api/juli/radio/simulate-switch` | Simula una conmutación de canal RF desde la terminal móvil o walkie emulado. | `RadioSwitchRequest` |
| `POST` | `/api/juli/radio/pei` | Decodifica un comando crudo AT / hexadecimal PEI (`AT+CTGS=...`, etc.) y ejecuta la conmutación. | `RadioPeiCommandInput` |

---

### 5.5 Canales en Tiempo Real (WebSockets)

- **`ws://localhost:8000/ws`**: Bus de eventos broadcast general (alertas de prueba de vida, eventos de sincronización NRT, cambios de frecuencia de radio).
- **`ws://localhost:8000/ws/tracking`**: Streaming periódico de alta frecuencia (cada 2 segundos) con las posiciones cinemáticas de las unidades sobre el mapa.
- **`ws://localhost:8000/ws/chat`**: Bus de mensajería táctica E2EE en tiempo real con soporte de presencia, typing, entrega de sobres cifrados y resolución de prueba de vida.
- **`ws://localhost:8000/ws/radio`**: Telemetría de enlace de radiofrecuencia y notificaciones de conmutación de canales.

---

## 🚀 6. Guía Rápida de Instalación y Uso (Quickstart)

### Requisitos Previos
- **Linux / macOS / WSL2**.
- **Python 3.11** o superior (entorno probado exhaustivamente en Python 3.11 - 3.14).
- Opcional: Base de datos **PostGIS** (el backend arranca y opera en modo autónomo mediante SQLite y archivos JSON/Parquet si PostGIS no está disponible).

### Paso 1: Configurar el Entorno Virtual
```bash
cd backend

# Si no existe .venv, créalo
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias principales
pip install -r app/juli/requirements.txt
```

### Paso 2: Variables de Entorno (`.env`)
Crea un archivo `.env` en la raíz de `backend/`:
```env
# Clave API de NASA FIRMS (Requerida para ingesta de datos satelitales en vivo)
# Si no dispones de una, puedes solicitarla gratis en https://firms.modaps.eosdis.nasa.gov/api/map_key/
FIRMS_MAP_KEY=tu_clave_de_nasa_firms

# Configuración opcional de CORS y Base de Datos
ALLOWED_ORIGINS=*
DATABASE_URL=postgresql+asyncpg://cataclismo:cataclismo@localhost:5432/cataclismo
```

> [!IMPORTANT]
> La clave **`FIRMS_MAP_KEY`** necesaria para la API NRT de NASA FIRMS reside en **GitHub Secrets** (para inyectarse como `${{ secrets.FIRMS_MAP_KEY }}` en workflows/despliegues que ejecuten ingesta en vivo) y en `backend/.env` en desarrollo local (`cp ../.env.example .env`). Sin ella, NASA FIRMS responde `Invalid MAP_KEY` y `POST /api/live/refresh` devuelve HTTP 400. Nunca commitees claves reales en texto plano.
>
> **Contrato hacia el Frontend:** `GET /api/cata/predictions` expone íntegro `app/cata/artifacts/predictions/cata_predictions.json` (incluyendo las matrices 2D y `valen_features_norm`). En cambio, `GET /api/lucia/routes` (`lucia_routes.geojson`) devuelve una proyección GeoJSON en WGS84 con las rutas, Puntos de Encuentro y polígonos `fire_cell` de riesgo (`cata_quadrant_state` y `fire_probability_t1`), omitiendo las matrices 2D completas y `valen_features_norm`; el build estático actual de `frontend/` lee datos offline de `frontend/public/data/` hasta conectarse a estos endpoints.

### Paso 3: Levantar el Servidor Completo
```bash
# Levantar el backend con FastAPI + Uvicorn (Puerto 8000)
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
La documentación interactiva Swagger estará accesible de inmediato en:
👉 **`http://localhost:8000/docs`**

### Paso 4: Levantar JULI en Modo Independiente (Standalone)
Si estás desarrollando únicamente el Frontend de seguimiento o la interfaz de comunicaciones tácticas y no necesitas los modelos pesados de CATA o TensorFlow:
```bash
cd app/juli
../../.venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8001
```
Swagger de JULI Standalone:
👉 **`http://localhost:8001/docs`**

---

## 🧪 7. Suite de Pruebas Automatizadas (QA & Verification)

El backend cuenta con una suite completa de **51 tests automatizados** (`unittest`) que cubren el 100% de los componentes críticos, divididos por perfil de complejidad:

```
backend/tests/
├── test_valen_pipeline.py          # [Hydrogen xHigh] Ingesta, proyección LAEA, agregación 6h y SQLite
├── test_cata_lucia_continual_nrt.py # [Hydrogen xHigh] Predicciones CATA, rutas LUCIA, memoria Continual y Live NRT
├── test_juli_standard_and_api.py   # [Hydrogen xHigh] Subcoordenadas, tracking, prueba de vida y APIs REST
├── test_argon_security_crypto.py   # [Argon High] Seguridad criptográfica E2EE, sanitización CDR y Magic Bytes
└── test_argon_concurrency_state.py # [Argon High] Concurrencia WebSocket, tolerancia a sockets rotos y TETRA
```

### Ejecución de la Suite Completa de Tests
```bash
cd backend
TF_CPP_MIN_LOG_LEVEL=3 .venv/bin/python -m unittest -v \
  tests/test_valen_pipeline.py \
  tests/test_cata_lucia_continual_nrt.py \
  tests/test_juli_standard_and_api.py \
  tests/test_argon_security_crypto.py \
  tests/test_argon_concurrency_state.py
```

*Resultado verificado de la suite:* **`50 OK, 0 FAILED, 0 ERRORS, 1 SKIPPED`** (el test de endpoint live FastAPI se omite de forma limpia si `fastapi` no está instalado en el `.venv` base).

---

## 📂 8. Estructura del Directorio `backend/`

```text
backend/
├── app/
│   ├── main.py                     # Punto de entrada unificado FastAPI + Lifespan + Endpoints centrales
│   ├── config.py                   # Pydantic Settings y configuración global
│   ├── db.py                       # Conector asíncrono SQLAlchemy + PostGIS (opcional)
│   ├── ws.py                       # Gestor de WebSockets central con tolerancia a fallos
│   ├── live_nrt.py                 # Ciclo continuo de ingesta NASA FIRMS NRT + Open-Meteo
│   ├── valen/                      # 🛡️ PERSONALIDAD 1: VALEN (Ingesta, Scoring y Enriquecimiento)
│   │   ├── phase1_projection.py    # Proyección a EPSG:3035 y celdas ES1K
│   │   ├── phase2_cell_day.py      # Agregación temporal por celda y sensor
│   │   ├── meteomatics_client.py   # Cliente meteorológico (15 variables horarias + caché SQLite)
│   │   ├── vegetation_client.py    # Cliente de combustible (WorldCover + IFN3 + caché SQLite)
│   │   ├── rainfall_client.py      # Cliente de sequía y lluvias (NASA POWER + caché SQLite)
│   │   ├── elevation_client.py     # Cliente de altimetría (Open-Elevation + caché SQLite)
│   │   ├── roads_client.py         # Cliente de red viaria (OpenStreetMap + caché SQLite)
│   │   ├── scoring_client.py       # Algoritmo de decisión (valen_compute_score: ACEPTA/REVISA/RECHAZA)
│   │   ├── laea.py                 # Conversor matemático WGS84 <-> EPSG:3035 sin librerías C
│   │   └── json_output.py          # Utilidad streaming para JSON masivos
│   ├── cata/                       # 🔮 PERSONALIDAD 2: CATA (Predicción Espacio-Temporal)
│   │   ├── model.py                # Red ConvLSTM2D (22 canales) + discriminación cuadrantes (0..3)
│   │   ├── train.py                # Pipeline de entrenamiento, inferencia y evaluación
│   │   ├── config.py               # CHANNEL_REGISTRY (22 canales) e hiperparámetros de rejilla
│   │   └── export_tflite.py        # Exportador TFLite (Float16, Int8 cuantizado)
│   ├── lucia/                      # 🧭 PERSONALIDAD 3: LUCIA (Evacuación Segura y Logística)
│   │   ├── model.py                # Red neuronal TensorFlow (15 canales) para campos de riesgo
│   │   ├── router.py               # Motor A* 3D ponderado con Tobler y efecto chimenea
│   │   ├── config.py               # LUCIA_CHANNEL_REGISTRY y umbrales de seguridad al fuego
│   │   └── train.py                # Entrenamiento y validación del enrutador de evacuación
│   ├── juli/                       # ⚡ PERSONALIDAD 4: JULI (C2, Tracking, Chat E2EE & Walkie TETRA)
│   │   ├── main.py                 # Servidor FastAPI/WebSocket de JULI + simulador en vivo
│   │   ├── coords.py               # Sistema dual Cuadrante 1000m + Subcoordenadas métricas
│   │   ├── tracker.py              # Gestor de equipos, operarios y Prueba de Vida (Dead-Man)
│   │   ├── chat.py                 # Motor de mensajería táctica E2EE multicanal
│   │   ├── chat_crypto.py          # Validación de claves ECDH/ECDSA P-256 y cifrado AES-256-GCM
│   │   ├── attachment_security.py  # Inspección antimalware CDR y sanitización de imágenes/PDFs
│   │   ├── walkie_radio.py         # Pasarela Walkie-Talkie BLE GATT + comandos AT TETRA PEI
│   │   └── config.py               # Constantes de radio, tiempos de inmovilidad y paletas
│   └── continual/                  # 🧠 MEMORIA ADAPTATIVA CONTINUA
│       └── adapter.py              # Calibración online EMA por bloque territorial sin reentrenar
├── checkpoints/                    # Modelos Keras entrenados (best_model.keras)
├── tests/                          # Suite completa de tests automatizados (51 tests)
├── Dockerfile                      # Despliegue en contenedor Docker
├── pyproject.toml                  # Metadatos del proyecto y dependencias
└── README.md                       # Este documento
```

---

## 🧩 9. Contratos de Datos y Ejemplos de Payloads

### 9.1 Alerta Automática de Prueba de Vida (JULI WebSocket `/ws`)
```json
{
  "event": "proof_of_life_alert",
  "alert_type": "burning_quadrant",
  "operator_id": "op_hu_02",
  "operator_name": "Carlos Ruiz",
  "team_id": "team_brif_huelva",
  "callsign": "BR-202",
  "severity": "critical",
  "reason": "El cuadrante ES1K:L0:Y02209:X02996 en el que se encuentra el operario ha entrado en estado de fuego activo (3='B').",
  "immobile_seconds": 960,
  "last_location": {
    "lon": -6.9482,
    "lat": 37.2654,
    "elevation_m": 142.5,
    "quadrant_id": "ES1K:L0:Y02209:X02996",
    "offset_x_m": 420.5,
    "offset_y_m": 780.2,
    "sub_cell_id": "ES1K:L0:Y02209:X02996:s10m_78_42"
  },
  "battery_pct": 82,
  "heart_rate_bpm": 138,
  "timestamp": "2026-11-15T09:30:00Z"
}
```

### 9.2 Conmutación Atómica de Canal Walkie TETRA PEI (`POST /api/juli/radio/pei`)
```json
// Request (Comando AT emitido por el walkie-talkie vía Bluetooth LE)
{
  "operator_id": "op_hu_01",
  "raw_command": "AT+CTGS=2002\r"
}

// Response (Sincronización atómica instantánea)
{
  "status": "ok",
  "operator_id": "op_hu_01",
  "operator_name": "María García",
  "previous_team_id": "team_brif_huelva",
  "new_team_id": "team_ume_zamora",
  "previous_frequency_mhz": 154.525,
  "new_frequency_mhz": 154.625,
  "new_talkgroup_id": "2002",
  "new_radio_channel": "VHF-02",
  "atomic_sync_applied": true,
  "message": "Operario 'op_hu_01' reasignado atómicamente a 'team_ume_zamora' tras conmutar a talkgroup 2002."
}
```

---

## ❓ 10. Preguntas Frecuentes y Resolución de Problemas

### P: ¿Por qué no reentrenar CATA o LUCIA cada vez que un bombero reporta una discrepancia en el terreno?
**R:** Reentrenar una red recurrente profunda `ConvLSTM2D` durante una emergencia en curso consume minutos u horas de GPU y corre el riesgo de sufrir *olvido catastrófico*. En su lugar, el **Continual Learning Engine** (`app/continual/`) ajusta al instante un multiplicador adaptativo local sobre el bloque territorial afectado, corrigiendo la inferencia en milisegundos sin tocar los pesos del modelo base.

### P: ¿Puede ejecutarse JULI sin conexión a internet ni acceso a satélites?
**R:** Sí. JULI fue concebido para puestos de mando aislados. Su base de datos local JSON/SQLite, su servidor FastAPI standalone (`port 8001`), su chat táctico E2EE y su pasarela BLE/TETRA funcionan íntegramente en red local (LAN / Wi-Fi táctico / malla DMR) sin requerir servicios externos.

### P: ¿Cómo maneja el chat táctico la inspección de archivos sin comprometer el cifrado E2EE?
**R:** El cifrado E2EE protege los mensajes de texto y claves privadas entre los participantes. Para evitar que un actor malicioso o un dispositivo comprometido distribuya troyanos, exploits PDF o imágenes bomba al resto de cuadrillas, los adjuntos pasan por una tubería de desinfección binaria en el servidor (`attachment_security.py`) que valida magic bytes reales, elimina metadatos y recodifica los píxeles antes de generar el token seguro de descarga.

---

*Desarrollado con dedicación para proteger vidas humanas, fauna y ecosistemas forestales frente a la catástrofe del fuego.*
