"""Pruebas estándar para JULI (coords, tracker, chat, walkie) y capa API/WS (Hydrogen xHigh)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from app.juli import config as juli_config
from app.juli import coords as juli_coords
from app.juli.chat import JuliChatManager
from app.juli.tracker import JuliTracker
from app.juli.walkie_radio import WalkieRadioManager, build_protocol_spec

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


class TestJuliCoordsAndTracker(unittest.TestCase):
    def test_quadrant_subcoords_roundtrip(self) -> None:
        lon, lat = -6.5423, 37.9512
        info = juli_coords.lonlat_to_quadrant_subcoords(lon, lat)
        self.assertTrue(info["quadrant_id"].startswith("ES1K:L0:"))
        self.assertGreaterEqual(info["offset_x_m"], 0.0)
        self.assertLess(info["offset_x_m"], 1000.0)
        self.assertGreaterEqual(info["offset_y_m"], 0.0)
        self.assertLess(info["offset_y_m"], 1000.0)
        self.assertGreaterEqual(info["sub_x_norm"], 0.0)
        self.assertLess(info["sub_x_norm"], 1.0)

        lon_rt, lat_rt = juli_coords.quadrant_subcoords_to_lonlat(
            quadrant_id=info["quadrant_id"],
            offset_x_m=info["offset_x_m"],
            offset_y_m=info["offset_y_m"],
        )
        self.assertAlmostEqual(lon_rt, lon, delta=1e-4)
        self.assertAlmostEqual(lat_rt, lat, delta=1e-4)

        with self.assertRaises(ValueError):
            juli_coords.parse_quadrant_id("INVALID_GRID_ID")

    def test_tracker_crud_and_proof_of_life_immobile_and_fire(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "juli_state.json")
            geojson_path = os.path.join(tmp, "juli_ops.geojson")
            pred_path = os.path.join(tmp, "cata_predictions.json")
            tracker = JuliTracker(state_path=state_path, geojson_path=geojson_path)

            team = tracker.upsert_team("team_alpha", "Alfa Test", unit_code="ALF-1", radio_channel="VHF-07")
            self.assertEqual(team.team_id, "team_alpha")

            op = tracker.upsert_operator(
                operator_id="op_alpha_1",
                name="Lucia Campo",
                team_id="team_alpha",
                lon=-6.54,
                lat=37.95,
            )
            self.assertEqual(op.team_id, "team_alpha")

            # Confirmar prueba de vida reinicia alerta de inmovilidad
            tracker.confirm_proof_of_life("op_alpha_1", note="OK en radio")
            future_dt = datetime.fromisoformat(tracker.operators["op_alpha_1"].last_moved_at) + timedelta(minutes=20)
            res = tracker.evaluate_proof_of_life(now=future_dt, cata_predictions_path=pred_path)
            alpha_alerts = [a for a in res["alerts"] if a["operator_id"] == "op_alpha_1"]
            self.assertEqual(len(alpha_alerts), 1)
            self.assertIn("immobile_timeout", alpha_alerts[0]["reasons"])
            self.assertEqual(alpha_alerts[0]["recipients"]["central"]["target"], "central")
            self.assertEqual(alpha_alerts[0]["recipients"]["squadron"]["team_id"], "team_alpha")

            gj = tracker.build_geojson()
            self.assertEqual(gj["type"], "FeatureCollection")
            self.assertEqual(gj["metadata"]["quadrant_grid"]["cell_size_m"], 1000.0)


class TestJuliWalkieAndChatStandard(unittest.TestCase):
    def test_walkie_switch_and_chat_general_central_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = JuliTracker(
                state_path=os.path.join(tmp, "state.json"),
                geojson_path=os.path.join(tmp, "ops.geojson"),
            )
            radio = WalkieRadioManager(tracker=tracker, log_path=os.path.join(tmp, "radio.json"))
            chat = JuliChatManager(
                state_path=os.path.join(tmp, "chat.json"),
                tracker=tracker,
                attachments_dir=os.path.join(tmp, "atts"),
            )

            spec = build_protocol_spec()
            self.assertEqual(spec["protocol"], juli_config.RADIO_DEFAULT_PROTOCOL)
            self.assertEqual(spec["ble_gatt"]["service_uuid"], juli_config.RADIO_BLE_SERVICE_UUID)

            # Modo default general y omnividencia de Central
            ch_hu = {c["channel_id"]: c for c in chat.list_channels("op_hu_01")}
            self.assertIn("global:operativo", ch_hu)
            self.assertIn("team:team_brif_huelva", ch_hu)

            ch_central = {c["channel_id"]: c for c in chat.list_channels("central")}
            self.assertIn("global:operativo", ch_central)
            self.assertIn("team:team_brif_huelva", ch_central)
            self.assertIn("team:team_ume_zamora", ch_central)

            rec = radio.switch_frequency(
                operator_id="op_hu_01",
                at_command="AT+CTGS=2002",
                simulated=True,
            )
            self.assertTrue(rec["team_changed"])
            self.assertEqual(rec["current"]["team_id"], "team_ume_zamora")

            ch_hu_after = {c["channel_id"]: c for c in chat.list_channels("op_hu_01")}
            self.assertIn("team:team_ume_zamora", ch_hu_after)
            self.assertNotIn("team:team_brif_huelva", ch_hu_after)


class TestAppCoreWithMocks(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _build_fastapi_pydantic_stubs() -> dict[str, types.ModuleType]:
        fastapi_mod = types.ModuleType("fastapi")
        fastapi_cors = types.ModuleType("fastapi.middleware.cors")

        class _HTTPException(Exception):
            def __init__(self, status_code: int, detail: str = "") -> None:
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        class _WebSocketDisconnect(Exception):
            pass

        class _WebSocket:
            pass

        class _DummyAppOrRouter:
            def __init__(self, *args, **kwargs) -> None:
                self.routes = []

            def add_middleware(self, *args, **kwargs) -> None:
                pass

            def include_router(self, *args, **kwargs) -> None:
                pass

            def _dec(self, *args, **kwargs):
                return lambda fn: fn

            get = post = patch = delete = websocket = _dec

        fastapi_mod.APIRouter = _DummyAppOrRouter
        fastapi_mod.FastAPI = _DummyAppOrRouter
        fastapi_mod.File = lambda *a, **kw: None
        fastapi_mod.Form = lambda *a, **kw: None
        fastapi_mod.HTTPException = _HTTPException
        fastapi_mod.Query = lambda *a, **kw: None
        fastapi_mod.UploadFile = object
        fastapi_mod.WebSocket = _WebSocket
        fastapi_mod.WebSocketDisconnect = _WebSocketDisconnect
        fastapi_cors.CORSMiddleware = object

        responses_mod = types.ModuleType("fastapi.responses")
        responses_mod.Response = object

        pydantic_mod = types.ModuleType("pydantic")

        class _BaseModel:
            def __init__(self, **kwargs) -> None:
                for cls in reversed(self.__class__.__mro__):
                    for k, v in cls.__dict__.items():
                        if not k.startswith("_") and not callable(v) and not isinstance(v, (staticmethod, classmethod, property)):
                            setattr(self, k, v)
                for k, v in kwargs.items():
                    setattr(self, k, v)

            def model_dump(self, exclude_none: bool = False):
                d = dict(self.__dict__)
                return {k: v for k, v in d.items() if v is not None} if exclude_none else d

        pydantic_mod.BaseModel = _BaseModel
        pydantic_mod.Field = lambda default=None, **kw: default

        pydantic_settings_mod = types.ModuleType("pydantic_settings")

        class _BaseSettings:
            def __init__(self, **kwargs) -> None:
                for k, v in self.__class__.__dict__.items():
                    if not k.startswith("_") and not isinstance(v, (staticmethod, classmethod, property)) and not callable(v):
                        setattr(self, k, kwargs.get(k, v))

        pydantic_settings_mod.BaseSettings = _BaseSettings
        pydantic_settings_mod.SettingsConfigDict = lambda **kw: {}

        asyncpg_mod = types.ModuleType("asyncpg")
        return {
            "fastapi": fastapi_mod,
            "fastapi.middleware": types.ModuleType("fastapi.middleware"),
            "fastapi.middleware.cors": fastapi_cors,
            "fastapi.responses": responses_mod,
            "pydantic": pydantic_mod,
            "pydantic_settings": pydantic_settings_mod,
            "asyncpg": asyncpg_mod,
        }

    async def test_ws_connection_manager_and_db_fallback(self) -> None:
        stubs = self._build_fastapi_pydantic_stubs() if not _HAS_FASTAPI else {}
        with mock.patch.dict(sys.modules, stubs):
            from app import config as app_config
            from app import db as app_db
            from app import ws as app_ws

            self.assertIn("http://localhost:5173", app_config.Settings().cors_origin_list)

            class _FakeWS:
                def __init__(self) -> None:
                    self.accepted = False
                    self.sent: list[dict] = []

                async def accept(self) -> None:
                    self.accepted = True

                async def send_json(self, payload: dict) -> None:
                    self.sent.append(payload)

            mgr = app_ws.ConnectionManager()
            ws1 = _FakeWS()
            await mgr.connect(ws1)
            self.assertTrue(ws1.accepted)
            await mgr.broadcast({"event": "ping"})
            self.assertEqual(ws1.sent, [{"event": "ping"}])
            mgr.disconnect(ws1)
            self.assertEqual(len(mgr.active), 0)

            # Sin PostgreSQL corriendo en local, postgis_version devuelve None de forma segura
            ver = await app_db.postgis_version()
            self.assertTrue(ver is None or isinstance(ver, str))

    async def test_api_handlers_and_radio_ws_hook_isolated(self) -> None:
        import importlib

        stubs = self._build_fastapi_pydantic_stubs() if not _HAS_FASTAPI else {}
        with tempfile.TemporaryDirectory() as tmp:
            iso_tracker = JuliTracker(
                state_path=os.path.join(tmp, "juli_state.json"),
                geojson_path=os.path.join(tmp, "juli_ops.geojson"),
            )
            iso_radio = WalkieRadioManager(
                tracker=iso_tracker,
                log_path=os.path.join(tmp, "radio.json"),
            )
            iso_chat = JuliChatManager(
                state_path=os.path.join(tmp, "chat.json"),
                tracker=iso_tracker,
                attachments_dir=os.path.join(tmp, "atts"),
            )

            with (
                mock.patch.dict(sys.modules, stubs),
                mock.patch("app.juli.tracker.juli_tracker", iso_tracker),
                mock.patch("app.juli.walkie_radio.walkie_radio", iso_radio),
                mock.patch("app.juli.chat.juli_chat", iso_chat),
            ):
                # Limpiar caché de importación previa si existía para que tome singletons aislados
                for mod_name in ("app.main", "app.juli.main"):
                    sys.modules.pop(mod_name, None)

                app_juli_main = importlib.import_module("app.juli.main")
                app_main = importlib.import_module("app.main")

                try:
                    # 1. Health sin BD devuelve status ok
                    h = await app_main.health()
                    self.assertEqual(h["status"], "ok")
                    self.assertEqual(h["pipeline"], ["valen", "cata", "lucia"])

                    # 2. Simulación radio vía endpoint handler + difusión al WS /ws principal via hook
                    received_ws: list[dict] = []

                    class _CapturingWS:
                        async def accept(self) -> None:
                            pass

                        async def send_json(self, msg: dict) -> None:
                            received_ws.append(msg)

                    ws_client = _CapturingWS()
                    await app_main.manager.connect(ws_client)
                    try:
                        req = app_juli_main.RadioSwitchInput(
                            operator_id="op_hu_01",
                            target_team_id="team_ume_zamora",
                            simulated=True,
                        )
                        res = await app_juli_main.simulate_juli_radio_switch(req)
                        self.assertEqual(res["current"]["team_id"], "team_ume_zamora")
                        self.assertTrue(any(ev.get("event") == "juli_radio_frequency_switched" for ev in received_ws))
                    finally:
                        app_main.manager.disconnect(ws_client)

                    # 3. Rechazo 400 cuando compute_lucia_interactive_route recibe cuadrante inválido
                    bad_route_req = app_main.LuciaRouteRequest(quadrant_id="INVALIDO")
                    with self.assertRaises(app_main.HTTPException) as ctx:
                        await app_main.compute_lucia_interactive_route(bad_route_req)
                    self.assertEqual(ctx.exception.status_code, 400)
                finally:
                    for mod_name in ("app.main", "app.juli.main"):
                        sys.modules.pop(mod_name, None)

    @unittest.skipUnless(_HAS_FASTAPI, "Requiere fastapi instalado en .venv para TestClient en vivo")
    def test_live_fastapi_health_endpoint(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
