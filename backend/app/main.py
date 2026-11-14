"""Punto de entrada de la API: uvicorn app.main:app --reload"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import postgis_version
from app.ws import manager

app = FastAPI(title="CATACLISMO API", version="0.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Estado de la API y de la base de datos (no falla si la BD está caída)."""
    version = await postgis_version()
    return {"status": "ok", "database": "ok" if version else "unavailable", "postgis": version}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Canal en tiempo real: de momento reenvía a todos lo que recibe."""
    await manager.connect(websocket)
    try:
        while True:
            await manager.broadcast(await websocket.receive_json())
    except WebSocketDisconnect:
        manager.disconnect(websocket)
