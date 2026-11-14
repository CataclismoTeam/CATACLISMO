from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_responde_sin_base_de_datos():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_websocket_reenvia_los_mensajes():
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"tipo": "ping"})
        assert websocket.receive_json() == {"tipo": "ping"}
