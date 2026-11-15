"""Sincroniza en la API los resultados del ciclo en vivo (FIRMS → VALEN → CATA → LUCIA).

El ciclo necesita TensorFlow y corre en GitHub Actions (`.github/workflows/live-nrt.yml`), que
publica sus ficheros en la release `live-data`. La API los descarga cada pocos minutos y, cuando
cambian, avisa al front por el WebSocket `/ws` con el evento `live_nrt_updated`.

Se activa con `LIVE_DATA_URL` (por ejemplo,
`https://github.com/CataclismoTeam/CATACLISMO/releases/download/live-data`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import urllib.request
from collections.abc import Awaitable, Callable
from typing import Any

from app.lucia import config as lucia_config

logger = logging.getLogger(__name__)

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_STATUS_PATH = os.path.join(_APP_DIR, "continual", "artifacts", "live_nrt_status.json")

#: Fichero publicado en la release → ruta local donde lo leen los endpoints
LIVE_FILES: dict[str, str] = {
    "live_nrt_status.json": LIVE_STATUS_PATH,
    "cata_predictions.json": lucia_config.DEFAULT_CATA_PREDICTIONS_PATH,
    "lucia_routes.geojson": lucia_config.DEFAULT_GEOJSON_OUTPUT_PATH,
}
#: Tamaño máximo aceptado por fichero (las rutas de LUCIA ocupan ~1 MB)
MAX_BYTES = 20 * 1024 * 1024


def _download(url: str, timeout_sec: int = 30) -> bytes | None:
    """Descarga `url` (sigue la redirección de GitHub). None si no existe o falla."""
    if not url.startswith("https://"):
        raise ValueError(f"Esquema no permitido: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Cataclismo-API/1.0"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
            data = resp.read(MAX_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 — sin red o 404: se reintenta en el siguiente ciclo
        logger.info("live-data: no se pudo descargar %s: %s", url, exc)
        return None
    if len(data) > MAX_BYTES:
        logger.warning("live-data: %s supera %d bytes; se ignora", url, MAX_BYTES)
        return None
    return data


def _digest(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _write_atomic(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_status() -> dict[str, Any]:
    try:
        with open(LIVE_STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def sync_once(
    base_url: str,
    download: Callable[[str], bytes | None] = _download,
    files: dict[str, str] | None = None,
) -> list[str]:
    """Descarga los ficheros publicados y sustituye los que cambian. Devuelve los cambiados."""
    changed: list[str] = []
    for name, path in (files or LIVE_FILES).items():
        data = download(f"{base_url.rstrip('/')}/{name}")
        if data is None:
            continue
        try:
            json.loads(data)
        except ValueError:
            logger.warning("live-data: %s no es JSON válido; se ignora", name)
            continue
        if hashlib.sha256(data).hexdigest() == _digest(path):
            continue
        _write_atomic(path, data)
        changed.append(name)
    return changed


async def live_sync_loop(
    base_url: str,
    interval_sec: float,
    broadcast: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Sincroniza al arrancar y cada `interval_sec`; avisa por WebSocket de lo que cambie."""
    while True:
        try:
            changed = await asyncio.to_thread(sync_once, base_url)
            if changed:
                logger.info("live-data: actualizado %s", ", ".join(changed))
                status = await asyncio.to_thread(_read_status)
                await broadcast({**status, "event": "live_nrt_updated", "files": changed})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — un fallo puntual no tumba la API
            logger.warning("live-data: error al sincronizar: %s", exc)
        await asyncio.sleep(interval_sec)
