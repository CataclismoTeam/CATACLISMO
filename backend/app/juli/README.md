# JULI — Guía completa para el desarrollador / agente de Frontend

Este directorio (`backend/app/juli/`) contiene el módulo **JULI**, independiente del pipeline `VALEN -> CATA -> LUCIA`, unificado para gestionar **equipos y operarios persistentes** y **tracking GPS/biométrico en tiempo real** sobre las zonas de incendio predichas por **CATA**.

---

## 1. Qué te vas a encontrar en esta carpeta

| Archivo | Qué hace |
| :--- | :--- |
| **`main.py`** | **Servidor FastAPI + WebSocket unificado**. Despliega 3 unidades tácticas (`unit-bombero-01`, `unit-paramedico-02`, `unit-dron-03`) directamente sobre el perímetro real del incendio de `cata_predictions.json`, emite updates cada 2 s por `WS /ws/tracking` y se sincroniza automáticamente con `juli_tracker` (`team_first_response_live`). |
| **`coords.py`** | **Sistema dual Cuadrante 1000×1000m + Subcoordenadas de precisión**. Conversión bidireccional exacta entre `(lon, lat)` WGS84, coordenadas métricas `EPSG:3035`, cuadrante `ES1K:L0:Y{iy:05d}:X{ix:05d}` (`CELL_SIZE_M = 1000.0`) y subcoordenadas dentro del cuadrante (`offset_x_m`, `offset_y_m`, `sub_x_norm`, `sub_y_norm`, `sub_100m_rc`, `sub_10m_rc`, `sub_cell_id`). |
| **`tracker.py`** | Gestor persistente en disco (`artifacts/state/juli_state.json`) y exportador GeoJSON `EPSG:4326` con metadata `quadrant_grid` (`1000×1000 m`), equipos (`team_brif_huelva`, `team_ume_zamora`, `team_first_response_live`), centroides con cuadrante (`field_team_centroid`), líneas de formación (`field_team_formation`) y supervisor de **Prueba de Vida**. |
| **`chat.py`** | **Motor de mensajería táctica E2EE** (`artifacts/state/juli_chat_state.json`): canales directos (`dm:a:b`), de escuadrón (`team:{id}`), general (`global:operativo`) y de incidente, directorio de claves públicas, rotación por `key_epoch`, idempotencia `client_msg_id`, acuses `delivered`/`read` y gestor WebSocket (`/ws/chat`). |
| **`chat_crypto.py`** | Validación en servidor de claves **ECDH/ECDSA P-256** (curva NIST P-256), huellas **RFC 7638**, **códigos de seguridad (`safety_code`)**, sobres **AES-256-GCM** y rechazo automático de claves privadas o texto plano. |
| **`attachment_security.py`** | Inspección antimalware y sanitización CDR antes de reenviar adjuntos: valida firmas binarias reales (`PNG`, `JPEG`, `WEBP`, `GIF`, `PDF`), bloquea SVG/HTML/ejecutables/polyglots/zip-bombs/PDFs con `/JS`/`/Launch`/`/OpenAction`/`/EmbeddedFile`/`/Encrypt` (incluso dentro de streams comprimidos u ofuscados `#XX`) y recodifica imágenes con Pillow limpiando metadatos. |
| **`walkie_radio.py`** | **Puente Walkie-Talkie BLE GATT + TETRA PEI (`ETSI TS 100 392-5`)**: decodifica comandos AT/hex (`AT+CTGS=`, `AT+CFREQ=`, `AT+CTSG=`, `AT+CNUMF?`, `AT+CTGLIST?`, `AT+CSCAN`), simula conmutaciones RF y reasigna atómicamente al operario a su nuevo escuadrón en `juli_tracker`, GeoJSON, chat y Prueba de Vida en un único paso. |
| **`config.py`** | Constantes de cuadrícula unificada (`GRID_CRS = "EPSG:3035"`, `CELL_PREFIX = "ES1K"`, `CELL_SIZE_M = 1000.0`), parámetros de Prueba de Vida y esquema del chat E2EE. |
| **`requirements.txt`** | Dependencias mínimas (`fastapi`, `uvicorn[standard]`, `pydantic`) para levantar `main.py` de forma aislada. |
| **`artifacts/`** | Estado persistido (`artifacts/state/juli_state.json`) y GeoJSON pregenerado (`artifacts/geojson/juli_operators.geojson`). |

---

## 2. Cómo arrancarlo

Tiene **CORS abierto (`*`)** para todos los orígenes.

- **Opción A — Completo (VALEN/CATA/LUCIA + todo JULI)** desde `backend/`:
  ```bash
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  ```
- **Opción B — Standalone (solo JULI: simulador live + GeoJSON de equipos)** desde `backend/app/juli/`:
  ```bash
  pip install -r requirements.txt
  uvicorn main:app --reload --host 0.0.0.0 --port 8001
  ```

---

## 3. Endpoints de Simulación en Tiempo Real (Live Perimeter)

Disponibles tanto en `app.main` (`:8000`) como en `juli/main.py` (`:8001`):

- **`GET /api/units`**: Carga inicial del mapa. Devuelve un GeoJSON `FeatureCollection` (`features`) y el array plano `units` con: `id`, `role` (`paramédico` | `bombero` | `dron`), `lat`, `lon`, `status` (`activo` | `en_camino` | `sos`), `battery`, `heart_rate`.
- **`WS /ws/tracking`**: Emite el mismo payload actualizado cada **2 segundos** manteniendo a las unidades patrullando dentro de un radio operativo de `~1 km` alrededor del frente activo del incendio.
- **`POST /api/units/{unit_id}/sos`**: Fuerza en vivo el estado `"sos"` (`#EF4444`) de una unidad durante la demo (ej. `unit-bombero-01`).
- **`POST /api/units/sync-fire`**: Recalcula los anclajes sobre `cata_predictions.json` tras cambiar la fecha de simulación en CATA.

---

## 4. Endpoints de Equipos y Operarios Persistentes (`tracker.py`)

Disponibles en `app.main` (`:8000`) *(y los `GET` también en `:8001`)*:

- **`GET /api/juli/geojson`**: Devuelve el `FeatureCollection` completo (`EPSG:4326`) con coordenadas 3D `[lon, lat, elevation_m]` y tres tipos de `feature_type`:
  1. `field_operator` (`Point`): cada operario/unidad con `marker_color`, `team_color`, `role`, `status`, `battery_pct`, `heart_rate_bpm`, `callsign` y `assigned_task`.
  2. `field_team_centroid` (`Point`): centroide del equipo y resumen de efectivos.
  3. `field_team_formation` (`LineString`): línea táctica conectando a los miembros de cada equipo.
  - Filtros query opcionales: `?team_id=...`, `?status=...`, `?include_team_features=true|false`.
- **`GET /api/juli/teams`**: Lista estructurada de equipos y sus miembros.
- **`POST /api/juli/teams`**: Crea o actualiza un equipo (`team_id`, `name`, `code`, `sector`, `color`, `radio_channel`).
- **`POST /api/juli/operators`**: Añade o actualiza una persona dentro de un equipo (emite evento por `WS /ws`).
- **`PATCH /api/juli/operators/{operator_id}/location`**: Actualiza posición GPS/estado/batería en tiempo real (emite evento por `WS /ws`).
- **`DELETE /api/juli/operators/{operator_id}`**: Da de baja a un operario.

- **`GET /api/juli/proof-of-life`**: Evalúa la **Prueba de Vida** de todos los operarios desplegados (`?immobile_seconds=900` por defecto). Dispara `proof_of_life_alert` cuando:
  1. Un operario activo no se ha desplazado al menos `5 m` en **15 minutos (`900 s`)**, **o**
  2. El **cuadrante `1000 × 1000 m`** (`ES1K:L0:...`) donde se encuentra está **ardiendo o con fuego inminente** (`quadrant_state` en `(1, 2, 3)` según `cata_predictions.json`).
  - Cada alerta prioriza **`last_location`** (coordenadas absolutas WGS84 + EPSG:3035, cuadrante, subcoordenadas y tiempo inmóvil) e incluye los destinatarios **`recipients.central`** y **`recipients.squadron`** (todos los compañeros de su `team_id`).
- **`POST /api/juli/operators/{operator_id}/proof-of-life`**: Confirmación manual de prueba de vida del operario (opcionalmente con nueva posición/estado/biométricos) que reinicia su temporizador y emite resolución por WebSocket.
- **`POST /api/juli/proof-of-life/check`** *(en `app.main` `:8000`)*: Ejecuta una comprobación bajo demanda y difunde las alertas nuevas por `WS /ws` (además del monitor automático en segundo plano cada `30 s`).

---

## 5. Ejemplo rápido en JavaScript Vanilla (para el Frontend)

```javascript
const API_BASE = "http://localhost:8001"; // o :8000 si usas app.main
const WS_URL = "ws://localhost:8001/ws/tracking";

async function loadInitialUnits() {
  const res = await fetch(`${API_BASE}/api/units`);
  const geojson = await res.json();
  // geojson.features (GeoJSON Point) y geojson.units (array limpio)
  renderUnitsOnMap(geojson);
}

function connectTrackingWS() {
  const ws = new WebSocket(WS_URL);
  ws.onmessage = (event) => renderUnitsOnMap(JSON.parse(event.data));
  ws.onclose = () => setTimeout(connectTrackingWS, 2000);
}

async function triggerSOS(unitId = "unit-bombero-01") {
  await fetch(`${API_BASE}/api/units/${unitId}/sos`, { method: "POST" });
}

function renderUnitsOnMap(geojson) {
  console.table(geojson.units);
}

loadInitialUnits().then(connectTrackingWS);
```

---

## 6. Chat Táctico con Cifrado de Extremo a Extremo (E2EE)

JULI expone un subsistema de chat (`WS /ws/chat` + REST `/api/juli/chat/*`, disponible tanto en `:8000` como en `:8001`) diseñado para **WebCrypto nativo del navegador** (`window.crypto.subtle`), sin almacenar **nunca** claves privadas ni texto plano en el servidor.

### Modelo lógico de cifrado, supervisión de Central y usabilidad
- **Supervisión total de Central (`"central"`)**: el Centro de Control pertenece automáticamente a **todos** los canales (`global:operativo`, `team:*`, `incident:*` y `dm:*`), puede listarlos, leer historial, recibir avisos en tiempo real por `WS /ws/chat?participant_id=central` y **hablar en cualquiera de ellos**.
1. **Chat Directo (`dm:{min_id}:{max_id}`, esquema `e2ee-ecdh-p256-aes256gcm` o `e2ee-room-aes256gcm`)**:
   - Para conversaciones directas entre operarios con supervisión E2EE de Central, se recomienda envolver la clave del canal (`e2ee-room-aes256gcm`) para ambos operarios **y para `central`**; entre un operario y `central` también puede usarse `e2ee-ecdh-p256-aes256gcm` directo.
   - Pueden verificar ausencia de MITM comparando su **`safety_code`** numérico (`GET /api/juli/chat/safety-code`).
2. **Chat de Escuadrón / Grupo (`team:{team_id}` y `global:operativo`, esquema `e2ee-room-aes256gcm`)**:
   - Cada escuadrón comparte automáticamente sala con **Central**.
   - El creador (o Central/Jefe de cuadrilla) genera una clave aleatoria de sala **AES-256-GCM** por época (`key_epoch`) y la sube **envuelta individualmente** para cada miembro (`POST /api/juli/chat/channels/{channel_id}/keys`). Si entra o sale un operario, se rota `rotate_epoch: true`.
3. **Modo rápido por PIN/frase táctica (`e2ee-psk-pbkdf2-aes256gcm`)**:
   - Alternativa E2EE opcional para despliegues inmediatos sin intercambio previo de claves públicas (`PBKDF2-SHA256` 150 000 iteraciones + `AES-256-GCM`).
4. **Puente de Prueba de Vida (`system_alert`)**:
   - Cuando se dispara una alerta `proof_of_life_alert`, JULI publica automáticamente una tarjeta `system_alert` en el canal `team:{team_id}` (marcada `is_encrypted: false`) con `last_location`.

### Endpoints REST y WebSocket del Chat
- `GET /api/juli/chat/crypto-spec`: Parámetros criptográficos WebCrypto (`JULI-E2EE-v1`).
- `POST /api/juli/chat/keys` / `GET /api/juli/chat/keys` / `DELETE /api/juli/chat/keys/{participant_id}`: Directorio, rotación y revocación de claves públicas ECDH P-256.
- `GET /api/juli/chat/safety-code?participant_a=...&participant_b=...`: Código numérico de verificación.
- `GET /api/juli/chat/channels?participant_id=...`: Salas disponibles (con **`global:operativo`** primero como canal general por defecto, `default_channel_id` e `is_default: true`), `unread_count` y si el miembro tiene clave envuelta vigente.
- `POST /api/juli/chat/channels/direct` / `POST /api/juli/chat/channels`: Abrir chat directo 1 a 1 o sala multi-escuadrón.
- `POST /api/juli/chat/channels/{channel_id}/keys` / `GET /api/juli/chat/channels/{channel_id}/keys?participant_id=...`: Publicar o descargar la clave de sala envuelta por `key_epoch`.
- `POST /api/juli/chat/messages` / `GET /api/juli/chat/messages?participant_id=...` *(opcional `&channel_id=...`, por defecto **`global:operativo`**)*: Envío idempotente (`client_msg_id`) e historial cifrado; acepta `attachment_ids` ya verificados (`message_type`: `"image"`, `"pdf"`, `"attachment"`).
- `POST /api/juli/chat/attachments`: Sube una imagen (`PNG`/`JPEG`/`WEBP`/`GIF`) o `PDF` (`content_b64`, `filename`, `sender_id`, `channel_id`), ejecuta inspección binaria + antimalware + CDR antes de guardarlo y devuelve `attachment_id` + `sha256` si es seguro (rechaza con `400` si es falso o malicioso).
- `GET /api/juli/chat/attachments/{attachment_id}?participant_id=...`: Descarga segura del adjunto verificado para miembros autorizados o `central` (`X-Content-Type-Options: nosniff` + `Content-Security-Policy: sandbox`).
- `POST /api/juli/chat/messages/ack`: Acuses `delivered` / `read` *(por defecto sobre `global:operativo` si se omite `channel_id`)*.
- `WS /ws/chat?participant_id=op_hu_01` *(o `central`)*: Soporta acciones JSON `send_message`, `publish_keys`, `ack`, `typing` (todas con `channel_id` opcional apuntando por defecto a **`global:operativo`**) y `ping`; emite `chat_welcome` (`default_channel_id`), `chat_message`, `chat_key_bundle`, `chat_receipt`, `chat_typing` y `chat_presence`.

### Snippet WebCrypto listo para el Frontend (1 a 1 E2EE)
```javascript
const enc = new TextEncoder();
const dec = new TextDecoder();
const toB64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const fromB64 = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

// 1. Generar identidad en navegador y subir SOLO publicKeyJwk a POST /api/juli/chat/keys
async function createIdentity() {
  const kp = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
  const publicJwk = await crypto.subtle.exportKey("jwk", kp.publicKey);
  return { privateKey: kp.privateKey, publicJwk };
}

// 2. Derivar clave compartida AES-256-GCM entre mi privateKey y la publicJwk del peer
async function deriveDirectAesKey(myPrivateKey, peerPublicJwk, channelId) {
  const peerPub = await crypto.subtle.importKey("jwk", peerPublicJwk, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const sharedBits = await crypto.subtle.deriveBits({ name: "ECDH", public: peerPub }, myPrivateKey, 256);
  const hkdfKey = await crypto.subtle.importKey("raw", sharedBits, "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt: enc.encode(channelId), info: enc.encode("juli-e2ee-v1") },
    hkdfKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

// 3. Cifrar / Descifrar sobre enviado a POST /api/juli/chat/messages o WS /ws/chat
async function encryptText(aesKey, plaintext, senderFingerprint, aadText = "") {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const aad = aadText ? enc.encode(aadText) : undefined;
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad }, aesKey, enc.encode(plaintext));
  return {
    scheme: "e2ee-ecdh-p256-aes256gcm",
    ciphertext_b64: toB64(ct),
    iv_b64: toB64(iv),
    ...(aad ? { aad_b64: toB64(aad) } : {}),
    key_epoch: 1,
    sender_key_fingerprint: senderFingerprint,
  };
}

async function decryptText(aesKey, envelope) {
  const aad = envelope.aad_b64 ? fromB64(envelope.aad_b64) : undefined;
  const pt = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: fromB64(envelope.iv_b64), additionalData: aad },
    aesKey,
    fromB64(envelope.ciphertext_b64)
  );
  return dec.decode(pt);
}
```

---

## 7. Capa Walkie-Talkie BLE GATT + TETRA PEI (Cambio de frecuencia y escuadrón atómico)

Modela el protocolo **BLE GATT + TETRA PEI (`ETSI TS 100 392-5 AT Commands`)** con el que los walkie-talkies tácticos modernos se comunican con un terminal móvil o tablet MDT.

### Sincronización única (sin doble cambio operario + Central)
Cuando un operario cambia de frecuencia / talkgroup `GSSI` (de forma real o **simulada**), JULI actualiza **en un único paso**:
1. El equipo (`team_id`) y metadatos RF del operario en `juli_tracker` (`radio_channel`, `radio_frequency_mhz`, `talkgroup_id`, `radio_protocol`, `radio_device_id`, `radio_last_switch_at`) y en disco (`juli_state.json`).
2. La geometría GeoJSON (`juli_operators.geojson` / `GET /api/juli/geojson`), moviendo al operario, recalculando centroides/enlaces de formación y propagando `team_id` a las unidades live (`UNITS`).
3. Los canales de chat de escuadrón (`team:{id}` en `juli_chat`), sacándolo del canal anterior e incorporándolo al nuevo (Central conserva visibilidad global).
4. Los destinatarios de alertas de **Prueba de Vida** (el nuevo escuadrón + Central).
5. La difusión en tiempo real por WebSocket (`/ws/chat`, `/ws/radio` y `/ws` con evento `juli_radio_frequency_switched`).

### Servicio BLE GATT y comandos TETRA PEI AT soportados
- **Servicio GATT:** `7a690001-4a55-4c49-5241-44494f303031`
  - **RX (Terminal → Walkie):** `7a690002-4a55-4c49-5241-44494f303031` (`payload_utf8` / `payload_hex`)
  - **TX (Walkie → Terminal):** `7a690003-4a55-4c49-5241-44494f303031` (`+CTGS`, `+CFREQ`, `+CREG`, `OK`)
  - **Telemetría RF:** `7a690004-4a55-4c49-5241-44494f303031`
- **Plan de frecuencias por defecto (`VHF-High / SIRDEE-TETRA`):**
  - `team_brif_huelva`: canal `VHF-01`, `154.5250 MHz` (TETRA `391.1250 MHz`), `GSSI 1001`
  - `team_ume_zamora`: canal `VHF-02`, `154.6250 MHz` (TETRA `391.2500 MHz`), `GSSI 2002`
  - `team_first_response_live`: canal `VHF-TAC`, `154.8750 MHz` (TETRA `391.3750 MHz`), `GSSI 3003`
- **Comandos AT soportados:** `AT+CTGS=<gssi_or_radio_channel>`, `AT+CFREQ=<frequency_mhz>`, `AT+CTSG=<team_id>`, `AT+CNUMF?`, `AT+CTGLIST?`, `AT+CSCAN` (tanto en texto AT como en `ble_payload_hex`).

### Endpoints REST y WebSocket de Radio
- `GET /api/juli/radio/protocol` — Especificación BLE GATT UUIDs y comandos TETRA PEI AT.
- `GET /api/juli/radio/frequencies` — Banco completo de frecuencias y talkgroups de todos los escuadrones (incluidos equipos creados dinámicamente).
- `GET /api/juli/radio/operators/{operator_id}` — Frecuencia, talkgroup y estado RF/BLE actual del operario.
- `GET /api/juli/radio/history` — Histórico de conmutaciones reales y simuladas (`limit`, `operator_id`).
- `POST /api/juli/radio/switch` — Cambio de frecuencia (por `target_team_id`, `target_frequency_mhz`, `target_radio_channel`, `target_talkgroup_id`, `at_command` o `ble_payload_hex`) con sincronización automática de escuadrón.
- `POST /api/juli/radio/simulate-switch` — Simulación directa (`simulated=True`) de conmutación BLE GATT + TETRA PEI con métricas RF simuladas (`rssi_dbm`, `snr_db`, `handover_latency_ms`) y cambio de escuadrón inmediato en JULI.
- `POST /api/juli/radio/pei` — Ejecución directa de comandos crudos TETRA PEI AT / trama hexadecimal BLE.
- `WS /ws/radio?operator_id=<id|*>` — Puente bidireccional tiempo real para acciones `pei`, `switch`, `simulate_switch` y `ping`.
