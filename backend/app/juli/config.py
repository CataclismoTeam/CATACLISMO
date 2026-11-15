"""Configuración del sistema JULI — Control en tiempo real de equipos y operarios en el terreno."""

from __future__ import annotations

import os
from typing import Literal

ALGORITHM_NAME: str = "juli"
OUTPUT_GEOJSON_CRS: str = "EPSG:4326"

# Cuadrícula táctica normalizada a 1000 × 1000 m (idéntica a VALEN, CATA y LUCIA)
GRID_CRS: str = "EPSG:3035"
CELL_PREFIX: str = "ES1K"
GRID_LEVEL: int = 0
CELL_SIZE_M: float = 1000.0

OperatorStatus = Literal["en_terreno", "en_ruta", "en_descanso", "alerta", "inactivo"]
OperatorRole = Literal[
    "jefe_cuadrilla",
    "brigadista",
    "conductor_autobomba",
    "sanitario",
    "piloto_dron",
    "coordinador",
]

STATUS_COLORS: dict[str, str] = {
    "en_terreno": "#10b981",  # Verde esmeralda: operativo en misión
    "en_ruta": "#3b82f6",  # Azul: desplazándose
    "en_descanso": "#a855f7",  # Violeta: relevo / base
    "alerta": "#ef4444",  # Rojo: emergencia / SOS del operario
    "inactivo": "#6b7280",  # Gris: fuera de turno
}

ROLE_LABELS: dict[str, str] = {
    "jefe_cuadrilla": "Jefe de Cuadrilla",
    "brigadista": "Brigadista Forestal",
    "conductor_autobomba": "Conductor Autobomba",
    "sanitario": "Sanitario / Apoyo Vital",
    "piloto_dron": "Operador Dron Térmico",
    "coordinador": "Coordinador de Puesto de Mando",
}

TEAM_PALETTE: tuple[str, ...] = (
    "#06b6d4",  # Cyan
    "#f59e0b",  # Amber
    "#8b5cf6",  # Purple
    "#ec4899",  # Pink
    "#14b8a6",  # Teal
    "#eab308",  # Yellow
)

_JULI_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_JULI_DIR)
ARTIFACT_DIR: str = os.path.join(_JULI_DIR, "artifacts")
STATE_DIR: str = os.path.join(ARTIFACT_DIR, "state")
GEOJSON_DIR: str = os.path.join(ARTIFACT_DIR, "geojson")

DEFAULT_STATE_PATH: str = os.path.join(STATE_DIR, "juli_state.json")
DEFAULT_GEOJSON_OUTPUT_PATH: str = os.path.join(GEOJSON_DIR, "juli_operators.geojson")
DEFAULT_CATA_PREDICTIONS_PATH: str = os.path.join(
    _APP_DIR, "cata", "artifacts", "predictions", "cata_predictions.json"
)

# Parámetros de Prueba de Vida (Proof of Life) para operarios
PROOF_OF_LIFE_IMMOBILE_SECONDS: int = 15 * 60
PROOF_OF_LIFE_MIN_MOVE_M: float = 5.0
PROOF_OF_LIFE_BURNING_STATES: tuple[int, ...] = (1, 2, 3)
PROOF_OF_LIFE_CHECK_INTERVAL_S: float = 30.0
PROOF_OF_LIFE_INACTIVE_IMMOBILE_STATUSES: tuple[str, ...] = ("en_descanso", "inactivo")

# Parámetros de Chat E2EE táctico para JULI
DEFAULT_CHAT_STATE_PATH: str = os.path.join(STATE_DIR, "juli_chat_state.json")
CHAT_CENTRAL_ID: str = "central"
CHAT_GLOBAL_CHANNEL_ID: str = "global:operativo"
CHAT_MAX_MESSAGES_PER_CHANNEL: int = 500
CHAT_MAX_CIPHERTEXT_B64_CHARS: int = 65536
CHAT_PSK_ITERATIONS: int = 150000
CHAT_E2EE_SCHEMES: tuple[str, ...] = (
    "e2ee-ecdh-p256-aes256gcm",
    "e2ee-room-aes256gcm",
    "e2ee-psk-pbkdf2-aes256gcm",
)

# Parámetros de seguridad para adjuntos (imágenes y PDF) en chat JULI
DEFAULT_CHAT_ATTACHMENTS_DIR: str = os.path.join(ARTIFACT_DIR, "chat_attachments")
CHAT_ATTACHMENT_MAX_BYTES: int = 10 * 1024 * 1024
CHAT_IMAGE_MAX_WIDTH: int = 8192
CHAT_IMAGE_MAX_HEIGHT: int = 8192
CHAT_IMAGE_MAX_PIXELS: int = 25_000_000
CHAT_PDF_MAX_DECOMPRESSED_BYTES: int = 25 * 1024 * 1024

# Protocolo de enlace Walkie-Talkie moderno <-> Terminal móvil (BLE GATT + TETRA PEI TS 100 392-5)
DEFAULT_RADIO_LOG_PATH: str = os.path.join(STATE_DIR, "juli_radio_log.json")
RADIO_DEFAULT_PROTOCOL: str = "TETRA-PEI/BLE-GATT"
RADIO_BLE_SERVICE_UUID: str = "7a690001-4a55-4c49-5241-44494f303031"
RADIO_BLE_RX_CHAR_UUID: str = "7a690002-4a55-4c49-5241-44494f303031"
RADIO_BLE_TX_CHAR_UUID: str = "7a690003-4a55-4c49-5241-44494f303031"
RADIO_BLE_TELEMETRY_CHAR_UUID: str = "7a690004-4a55-4c49-5241-44494f303031"
RADIO_BASE_VHF_MHZ: float = 154.5250
RADIO_BASE_TETRA_MHZ: float = 391.1250
RADIO_CHANNEL_STEP_MHZ: float = 0.0250
DEFAULT_TEAM_FREQUENCY_PLANS: dict[str, dict[str, object]] = {
    "team_brif_huelva": {
        "radio_channel": "VHF-01",
        "frequency_mhz": 154.5250,
        "tetra_frequency_mhz": 391.1250,
        "talkgroup_id": "1001",
        "ctcss_hz": 88.5,
        "band": "VHF-High / SIRDEE-TETRA",
    },
    "team_ume_zamora": {
        "radio_channel": "VHF-02",
        "frequency_mhz": 154.6250,
        "tetra_frequency_mhz": 391.2500,
        "talkgroup_id": "2002",
        "ctcss_hz": 103.5,
        "band": "VHF-High / SIRDEE-TETRA",
    },
    "team_first_response_live": {
        "radio_channel": "VHF-TAC",
        "frequency_mhz": 154.8750,
        "tetra_frequency_mhz": 391.3750,
        "talkgroup_id": "3003",
        "ctcss_hz": 118.8,
        "band": "VHF-High / SIRDEE-TETRA",
    },
}
