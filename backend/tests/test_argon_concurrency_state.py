"""Suite QA de Alta Complejidad: Concurrencia, Carrera de Datos y Estado Persistente (Gemini Argon).

Cubre:
  1. Concurrencia WebSocket en `ConnectionManager` (`app/ws.py`) y `ChatConnectionManager`
     (`app/juli/chat.py`): ráfagas simultáneas con `asyncio.gather`, desconexiones concurrentes
     y aislamiento/limpieza ante excepciones en `send_json` a mitad de broadcast.
  2. Concurrencia y consistencia en `JuliChatManager`: idempotencia por `(sender_id, client_msg_id)`,
     recorte exacto en `CHAT_MAX_MESSAGES_PER_CHANNEL` (500), rotación de `key_epoch` y fusión de
     `wrapped_keys`, acceso omnisciente de `central` en equipos dinámicos/DM/incidentes,
     subida/descarga autorizada e integridad SHA-256 de adjuntos, y recuperación ante JSON corrupto.
  3. `WalkieRadioManager` + `JuliTracker`: >205 conmutaciones rápidas alternando `AT+CTGS`,
     `AT+CFREQ`, `AT+CTSG` y `ble_payload_hex` validando el tope de 200 entradas y recarga desde
     disco; máquina de estados intercalada de Prueba de Vida (inmovilidad + fuego -> alerta ->
     cambio de escuadrón por radio -> `confirm_proof_of_life`/movimiento -> `fire_clear`);
     clamping de subcoordenadas `[0, 1000)` y `[0, 1)`; recuperación ante estados JSON corruptos.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
from typing import Any
import unittest
from unittest import mock

from PIL import Image

from app.juli import chat as juli_chat_module
from app.juli import config as juli_config
from app.juli import coords as juli_coords
from app.juli.chat import ChatConnectionManager, JuliChatManager, team_channel_id
from app.juli.tracker import JuliTracker, load_burning_quadrants
from app.juli.walkie_radio import WalkieRadioManager

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

# ---------------------------------------------------------------------------
# Utilidades criptográficas NIST P-256 puras para generar JWKs válidos de test
# ---------------------------------------------------------------------------
_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_A = (_P256_P - 3) % _P256_P
_P256_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_P256_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5


def _p256_point_add(
    p1: tuple[int, int] | None, p2: tuple[int, int] | None
) -> tuple[int, int] | None:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P256_P == 0:
        return None
    if p1 == p2:
        lam = ((3 * x1 * x1 + _P256_A) * pow(2 * y1, -1, _P256_P)) % _P256_P
    else:
        lam = ((y2 - y1) * pow(x2 - x1, -1, _P256_P)) % _P256_P
    x3 = (lam * lam - x1 - x2) % _P256_P
    y3 = (lam * (x1 - x3) - y1) % _P256_P
    return x3, y3


def _p256_scalar_mult(k: int) -> tuple[int, int]:
    result: tuple[int, int] | None = None
    addend: tuple[int, int] | None = (_P256_GX, _P256_GY)
    scalar = k
    while scalar > 0:
        if scalar & 1:
            result = _p256_point_add(result, addend)
        addend = _p256_point_add(addend, addend)
        scalar >>= 1
    assert result is not None
    return result


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_valid_p256_jwk(scalar: int) -> dict[str, str]:
    x, y = _p256_scalar_mult(scalar)
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(x.to_bytes(32, "big")),
        "y": _b64url(y.to_bytes(32, "big")),
    }


def _make_encrypted_envelope(
    sender_fp: str = "fp_default_0123456789abcdef",
    key_epoch: int = 1,
    scheme: str = "e2ee-room-aes256gcm",
    seed: int = 1,
) -> dict[str, Any]:
    ct_raw = f"cipher_payload_{seed:06d}_authenticated_tag_16b".encode("utf-8")
    iv_raw = f"iv_{seed:09d}".encode("utf-8")[:12]
    return {
        "scheme": scheme,
        "ciphertext_b64": base64.b64encode(ct_raw).decode("ascii"),
        "iv_b64": base64.b64encode(iv_raw).decode("ascii"),
        "key_epoch": key_epoch,
        "sender_key_fingerprint": sender_fp,
    }


def _make_wrapped_key_bundle(seed: int = 1, ephemeral_scalar: int = 10) -> dict[str, Any]:
    wrapped_raw = (f"wrapped_aes256_key_{seed:04d}_" + "X" * 32).encode("utf-8")[:48]
    iv_raw = f"wk_{seed:09d}".encode("utf-8")[:12]
    return {
        "wrapped_key_b64": base64.b64encode(wrapped_raw).decode("ascii"),
        "iv_b64": base64.b64encode(iv_raw).decode("ascii"),
        "alg": "ECDH-P256+HKDF-SHA256+AES-256-GCM",
        "ephemeral_public_jwk": _make_valid_p256_jwk(ephemeral_scalar),
    }


def _make_clean_png_bytes() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (24, 24), color=(32, 160, 96))
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_clean_pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n"
        b"%%EOF\n"
    )


def _load_app_ws_module():
    """Carga `app.ws` inyectando un stub de `fastapi` en `sys.modules` si no está instalado."""
    if _HAS_FASTAPI:
        return importlib.import_module("app.ws")
    fastapi_stub = types.ModuleType("fastapi")

    class _WebSocketStub:
        pass

    fastapi_stub.WebSocket = _WebSocketStub
    with mock.patch.dict(sys.modules, {"fastapi": fastapi_stub}):
        sys.modules.pop("app.ws", None)
        return importlib.import_module("app.ws")


class _MockAsyncWebSocket:
    """Socket simulado con soporte de latencia cooperativa y fallo configurable en `send_json`."""

    def __init__(
        self,
        name: str,
        *,
        fail_on_send_call: int | None = None,
        delay_s: float = 0.0005,
    ) -> None:
        self.name = name
        self.accepted = False
        self.sent_messages: list[dict[str, Any]] = []
        self.send_calls = 0
        self.fail_on_send_call = fail_on_send_call
        self.delay_s = delay_s

    async def accept(self) -> None:
        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)
        self.accepted = True

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.send_calls += 1
        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)
        if self.fail_on_send_call is not None and self.send_calls >= self.fail_on_send_call:
            raise RuntimeError(f"Simulated broken pipe on websocket {self.name}")
        self.sent_messages.append(payload)


# ===========================================================================
# 1. CONCURRENCIA WEBSOCKET (ConnectionManager en ws.py y ChatConnectionManager)
# ===========================================================================
class TestWebSocketConcurrency(unittest.IsolatedAsyncioTestCase):
    async def test_chat_connection_manager_concurrent_gather_and_deduplication(self) -> None:
        """Verifica conexiones/desconexiones y broadcasts simultáneos en `ChatConnectionManager`."""
        mgr = ChatConnectionManager()
        participants = ["central", "op_hu_01", "op_hu_02", "op_za_01", "op_za_02"]
        sockets_by_pid: dict[str, list[_MockAsyncWebSocket]] = {
            pid: [_MockAsyncWebSocket(f"{pid}_s1"), _MockAsyncWebSocket(f"{pid}_s2")]
            for pid in participants
        }

        await asyncio.gather(
            *(
                mgr.connect(pid, ws)
                for pid, ws_list in sockets_by_pid.items()
                for ws in ws_list
            )
        )
        self.assertEqual(mgr.online_participants(), sorted(participants))
        for ws_list in sockets_by_pid.values():
            for ws in ws_list:
                self.assertTrue(ws.accepted)

        # Broadcasts concurrentes con IDs duplicados en la lista y exclusión de emisor
        recipients_with_dups = [
            "central",
            "op_hu_01",
            "op_hu_01",
            "op_hu_02",
            "op_za_01",
            "central",
        ]
        burst_count = 15
        await asyncio.gather(
            *(
                mgr.broadcast_to_participants(
                    recipients_with_dups,
                    {"event": "chat_message", "seq": idx},
                    exclude_participant="op_za_01",
                )
                for idx in range(burst_count)
            )
        )

        for pid in ("central", "op_hu_01", "op_hu_02"):
            for ws in sockets_by_pid[pid]:
                self.assertEqual(len(ws.sent_messages), burst_count)

        # op_za_01 fue excluido y op_za_02 no estaba en recipients_with_dups
        for pid in ("op_za_01", "op_za_02"):
            for ws in sockets_by_pid[pid]:
                self.assertEqual(len(ws.sent_messages), 0)

        # Desconectar primer socket de cada participante; el participante sigue online
        for pid in participants:
            mgr.disconnect(pid, sockets_by_pid[pid][0])
        self.assertEqual(mgr.online_participants(), sorted(participants))

        # Desconectar segundo socket; todos quedan offline y el diccionario queda limpio
        for pid in participants:
            mgr.disconnect(pid, sockets_by_pid[pid][1])
            mgr.disconnect(pid, sockets_by_pid[pid][1])  # idempotente
        self.assertEqual(mgr.online_participants(), [])

    async def test_chat_connection_manager_broken_socket_cleanup_mid_broadcast(self) -> None:
        """Verifica que sockets fallidos en `ChatConnectionManager` se limpian sin romper el broadcast."""
        mgr = ChatConnectionManager()
        ws_central_ok = _MockAsyncWebSocket("central_ok")
        ws_central_fail = _MockAsyncWebSocket("central_fail", fail_on_send_call=1)
        ws_hu1_fail_second = _MockAsyncWebSocket("hu1_fail_2", fail_on_send_call=2)
        ws_hu2_ok = _MockAsyncWebSocket("hu2_ok")

        await asyncio.gather(
            mgr.connect("central", ws_central_ok),
            mgr.connect("central", ws_central_fail),
            mgr.connect("op_hu_01", ws_hu1_fail_second),
            mgr.connect("op_hu_02", ws_hu2_ok),
        )

        # Primer broadcast: ws_central_fail lanza excepción en mitad de envío, pero central_ok,
        # hu1_fail_second y hu2_ok reciben el mensaje sin interrupción.
        await mgr.broadcast_to_participants(
            ["central", "op_hu_01", "op_hu_02"],
            {"event": "round_1"},
        )
        self.assertEqual(len(ws_central_ok.sent_messages), 1)
        self.assertEqual(len(ws_hu1_fail_second.sent_messages), 1)
        self.assertEqual(len(ws_hu2_ok.sent_messages), 1)
        self.assertIn("central", mgr.online_participants())

        # Segundo broadcast concurrente: ws_hu1_fail_second falla en su 2º envío y op_hu_01
        # es eliminado automáticamente de online_participants().
        await asyncio.gather(
            mgr.broadcast_to_participants(
                ["central", "op_hu_01", "op_hu_02"],
                {"event": "round_2a"},
            ),
            mgr.broadcast_to_participants(
                ["central", "op_hu_01", "op_hu_02"],
                {"event": "round_2b"},
            ),
        )
        self.assertEqual(len(ws_central_ok.sent_messages), 3)
        self.assertEqual(len(ws_hu2_ok.sent_messages), 3)
        self.assertNotIn("op_hu_01", mgr.online_participants())
        self.assertEqual(mgr.online_participants(), ["central", "op_hu_02"])

    async def test_ws_connection_manager_concurrent_healthy_broadcasts(self) -> None:
        """Verifica `ConnectionManager` de `app/ws.py` bajo `asyncio.gather` con clientes sanos."""
        app_ws = _load_app_ws_module()
        mgr = app_ws.ConnectionManager()
        clients = [_MockAsyncWebSocket(f"client_{i}") for i in range(12)]

        await asyncio.gather(*(mgr.connect(c) for c in clients))
        self.assertEqual(len(mgr.active), 12)

        await asyncio.gather(*(mgr.broadcast({"seq": i}) for i in range(10)))
        for c in clients:
            self.assertEqual(len(c.sent_messages), 10)

        for c in clients[:6]:
            mgr.disconnect(c)
        self.assertEqual(len(mgr.active), 6)

    async def test_ws_connection_manager_broken_socket_mid_broadcast_resilience(self) -> None:
        """Verifica si `ConnectionManager.broadcast` en `app/ws.py` aísla y limpia un socket caído.

        Si un cliente lanza excepción en `send_json` a mitad de `broadcast`, el gestor no
        debería abortar el envío al resto de clientes activos ni dejar el socket muerto en `active`.
        """
        app_ws = _load_app_ws_module()
        mgr = app_ws.ConnectionManager()
        ws_ok_1 = _MockAsyncWebSocket("ws_ok_1")
        ws_broken = _MockAsyncWebSocket("ws_broken", fail_on_send_call=1)
        ws_ok_2 = _MockAsyncWebSocket("ws_ok_2")

        await mgr.connect(ws_ok_1)
        await mgr.connect(ws_broken)
        await mgr.connect(ws_ok_2)

        # Un broadcast resiliente no debe propagar la excepción de un cliente caído ni dejar
        # sin mensaje a los demás sockets conectados, y debe limpiar `ws_broken` de `mgr.active`.
        await mgr.broadcast({"event": "field_update"})

        self.assertNotIn(ws_broken, mgr.active)
        self.assertEqual(len(ws_ok_1.sent_messages), 1)
        self.assertEqual(len(ws_ok_2.sent_messages), 1)


# ===========================================================================
# 2. CONCURRENCIA Y CONSISTENCIA EN JULICHATMANAGER
# ===========================================================================
class TestJuliChatConcurrencyAndState(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name
        self.tracker_state = os.path.join(self.tmp_dir, "juli_state.json")
        self.tracker_geojson = os.path.join(self.tmp_dir, "juli_operators.geojson")
        self.chat_state = os.path.join(self.tmp_dir, "juli_chat_state.json")
        self.attachments_dir = os.path.join(self.tmp_dir, "chat_attachments")

        self.tracker = JuliTracker(
            state_path=self.tracker_state,
            geojson_path=self.tracker_geojson,
        )
        self.chat = JuliChatManager(
            state_path=self.chat_state,
            tracker=self.tracker,
            attachments_dir=self.attachments_dir,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_concurrent_burst_client_msg_id_idempotency_and_receipts(self) -> None:
        """Ráfagas concurrentes con reintentos `client_msg_id`: unicidad de `server_seq` y acuses."""
        cid = team_channel_id("team_brif_huelva")
        unique_ids = [f"cmsg_burst_{i:03d}" for i in range(25)]

        async def _send_Async(sender: str, cmsg_id: str, seed: int) -> tuple[dict[str, Any], bool]:
            await asyncio.sleep(0.0002 * (seed % 5))
            return self.chat.send_message(
                channel_id=cid,
                sender_id=sender,
                encryption=_make_encrypted_envelope(
                    sender_fp=f"fp_{sender}",
                    seed=seed,
                ),
                message_type="text",
                client_msg_id=cmsg_id,
            )

        # 25 IDs únicos enviados 3 veces cada uno por op_hu_01 (75 llamadas -> 25 creados)
        # + 5 de esos mismos client_msg_id enviados por op_hu_02 (emisor distinto -> 5 creados)
        tasks = []
        for idx, cmid in enumerate(unique_ids):
            for retry in range(3):
                tasks.append(_send_Async("op_hu_01", cmid, idx * 10 + retry))
        for idx, cmid in enumerate(unique_ids[:5]):
            tasks.append(_send_Async("op_hu_02", cmid, 1000 + idx))

        results = await asyncio.gather(*tasks)
        created_Flags = [created for _, created in results]
        self.assertEqual(sum(1 for c in created_Flags if c), 30)
        self.assertEqual(sum(1 for c in created_Flags if not c), 50)

        # Verificar que todos los reintentos de op_hu_01 para un mismo client_msg_id devuelven
        # exactamente el mismo message_id y server_seq
        by_sender_cmsg: dict[tuple[str, str], set[tuple[str, int]]] = {}
        for msg_dict, _ in results:
            key = (msg_dict["sender_id"], msg_dict["client_msg_id"])
            by_sender_cmsg.setdefault(key, set()).add(
                (msg_dict["message_id"], msg_dict["server_seq"])
            )
        for pair_set in by_sender_cmsg.values():
            self.assertEqual(len(pair_set), 1)

        history = self.chat.list_messages(cid, participant_id="op_hu_03", limit=500)
        self.assertEqual(history["last_seq"], 30)
        self.assertEqual(len(history["messages"]), 30)
        seqs = [m["server_seq"] for m in history["messages"]]
        self.assertEqual(seqs, list(range(1, 31)))

        # Acuses de entrega y lectura actualizan unread_count
        channels_before = {
            c["channel_id"]: c for c in self.chat.list_channels("op_hu_03")
        }
        self.assertEqual(channels_before[cid]["unread_count"], 30)

        all_msg_ids = [m["message_id"] for m in history["messages"]]
        receipt = self.chat.ack_messages(
            cid, participant_id="op_hu_03", message_ids=all_msg_ids[:10], status="read"
        )
        self.assertEqual(len(receipt["message_ids"]), 10)
        channels_after = {
            c["channel_id"]: c for c in self.chat.list_channels("op_hu_03")
        }
        self.assertEqual(channels_after[cid]["unread_count"], 20)

    def test_exact_trimming_above_chat_max_messages_per_channel_and_reload(self) -> None:
        """Verifica recorte FIFO exacto al superar `CHAT_MAX_MESSAGES_PER_CHANNEL` (500)."""
        cid = juli_config.CHAT_GLOBAL_CHANNEL_ID
        max_msgs = juli_config.CHAT_MAX_MESSAGES_PER_CHANNEL
        extra = 35
        total_sent = max_msgs + extra

        for seq_idx in range(1, total_sent + 1):
            msg, created = self.chat.send_message(
                channel_id=cid,
                sender_id="op_hu_01",
                encryption=_make_encrypted_envelope(
                    sender_fp="fp_trim_test",
                    seed=seq_idx,
                ),
                message_type="text",
                client_msg_id=f"trim_msg_{seq_idx:04d}",
            )
            self.assertTrue(created)
            self.assertEqual(msg["server_seq"], seq_idx)

        stored = self.chat.messages[cid]
        self.assertEqual(len(stored), max_msgs)
        self.assertEqual(stored[0].server_seq, extra + 1)
        self.assertEqual(stored[-1].server_seq, total_sent)
        self.assertEqual(stored[0].client_msg_id, f"trim_msg_{extra + 1:04d}")
        self.assertEqual(stored[-1].client_msg_id, f"trim_msg_{total_sent:04d}")

        # Recargar desde disco y comprobar que el estado persistido conserva last_seq y 500 mensajes
        reloaded = JuliChatManager(
            state_path=self.chat_state,
            tracker=self.tracker,
            attachments_dir=self.attachments_dir,
        )
        hist = reloaded.list_messages(cid, participant_id="central", limit=max_msgs + 50)
        self.assertEqual(hist["last_seq"], total_sent)
        self.assertEqual(len(hist["messages"]), max_msgs)
        self.assertEqual(hist["messages"][0]["server_seq"], extra + 1)
        self.assertEqual(hist["messages"][-1]["server_seq"], total_sent)

    def test_key_epoch_rotation_wrapped_keys_and_identity_revocation(self) -> None:
        """Valida registro/rotación/revocación de claves ECDH P-256 y épocas `key_epoch`."""
        jwk_central = _make_valid_p256_jwk(1)
        jwk_hu1_v1 = _make_valid_p256_jwk(2)
        jwk_hu1_v2 = _make_valid_p256_jwk(3)
        jwk_hu2 = _make_valid_p256_jwk(4)

        rec_c = self.chat.register_identity_key("central", jwk_central, device_label="CMD-01")
        rec_1a = self.chat.register_identity_key("op_hu_01", jwk_hu1_v1, device_label="MDT-A1")
        # Re-registro idempotente de la misma clave mantiene key_version == 1
        rec_1b = self.chat.register_identity_key("op_hu_01", jwk_hu1_v1, device_label="MDT-A1")
        self.assertEqual(rec_1a["key_version"], 1)
        self.assertEqual(rec_1b["key_version"], 1)
        self.assertIsNone(rec_1b["previous_fingerprint"])

        # Rotación de clave de identidad incrementa key_version y guarda previous_fingerprint
        rec_1_rot = self.chat.register_identity_key("op_hu_01", jwk_hu1_v2, device_label="MDT-A1-NEW")
        self.assertEqual(rec_1_rot["key_version"], 2)
        self.assertEqual(rec_1_rot["previous_fingerprint"], rec_1a["fingerprint"])

        rec_2 = self.chat.register_identity_key("op_hu_02", jwk_hu2)

        # Código de seguridad simétrico
        sc_ab = self.chat.get_safety_code("central", "op_hu_01")
        sc_ba = self.chat.get_safety_code("op_hu_01", "central")
        self.assertEqual(sc_ab["safety_code"], sc_ba["safety_code"])

        cid = team_channel_id("team_brif_huelva")
        # Publicar época 1 inicialmente para central y op_hu_01
        pub_e1_part1 = self.chat.publish_channel_keys(
            channel_id=cid,
            sender_id="op_hu_01",
            wrapped_keys={
                "central": _make_wrapped_key_bundle(seed=10, ephemeral_scalar=11),
                "op_hu_01": _make_wrapped_key_bundle(seed=11, ephemeral_scalar=12),
            },
            key_epoch=1,
        )
        self.assertEqual(pub_e1_part1["key_epoch"], 1)

        # Fusionar clave envuelta para op_hu_02 en la misma época 1 sin perder las anteriores
        self.chat.publish_channel_keys(
            channel_id=cid,
            sender_id="op_hu_01",
            wrapped_keys={
                "op_hu_02": _make_wrapped_key_bundle(seed=12, ephemeral_scalar=13),
            },
            key_epoch=1,
        )
        k_c_e1 = self.chat.get_channel_key_for_participant(cid, "central", key_epoch=1)
        k_2_e1 = self.chat.get_channel_key_for_participant(cid, "op_hu_02", key_epoch=1)
        self.assertEqual(k_c_e1["key_epoch"], 1)
        self.assertEqual(k_2_e1["key_epoch"], 1)

        # Rotar a época 2 (rotate_epoch=True)
        pub_e2 = self.chat.publish_channel_keys(
            channel_id=cid,
            sender_id="central",
            wrapped_keys={
                "central": _make_wrapped_key_bundle(seed=20, ephemeral_scalar=21),
                "op_hu_01": _make_wrapped_key_bundle(seed=21, ephemeral_scalar=22),
            },
            rotate_epoch=True,
        )
        self.assertEqual(pub_e2["key_epoch"], 2)
        self.assertEqual(self.chat.channels[cid].current_key_epoch, 2)

        # Por defecto devuelve la época 2, pero permite consultar la época 1 histórica
        k_1_latest = self.chat.get_channel_key_for_participant(cid, "op_hu_01")
        self.assertEqual(k_1_latest["key_epoch"], 2)
        k_1_hist = self.chat.get_channel_key_for_participant(cid, "op_hu_01", key_epoch=1)
        self.assertEqual(k_1_hist["key_epoch"], 1)
        self.assertNotEqual(
            k_1_latest["wrapped_key"]["wrapped_key_b64"],
            k_1_hist["wrapped_key"]["wrapped_key_b64"],
        )

        # Un miembro de otro escuadrón no puede obtener ni publicar claves en este canal
        with self.assertRaises(PermissionError):
            self.chat.get_channel_key_for_participant(cid, "op_za_01")
        with self.assertRaises(ValueError):
            self.chat.publish_channel_keys(
                channel_id=cid,
                sender_id="central",
                wrapped_keys={"op_za_01": _make_wrapped_key_bundle(seed=99)},
            )

        # Revocar la clave de op_hu_02 impide publicar claves o enviar mensajes
        self.chat.revoke_identity_key("op_hu_02")
        with self.assertRaises(PermissionError):
            self.chat.send_message(
                channel_id=cid,
                sender_id="op_hu_02",
                encryption=_make_encrypted_envelope(sender_fp=rec_2["fingerprint"], seed=77),
            )

    def test_central_omniscient_access_in_dynamic_teams_direct_and_incident_channels(self) -> None:
        """Verifica que `central` tiene acceso automático de lectura/escritura en todo canal."""
        # 1. Equipo creado dinámicamente con upsert_team + operario asignado
        self.tracker.upsert_team(
            team_id="team_dyn_heli",
            name="Helitransporte Kamov",
            unit_code="KAMOV-01",
            radio_channel="VHF-09",
        )
        self.tracker.upsert_operator(
            operator_id="op_heli_01",
            name="Elena Cumbres",
            team_id="team_dyn_heli",
            lon=-6.12,
            lat=37.88,
        )
        # 2. Equipo auto-creado implícitamente al dar de alta un operario con team_id nuevo
        self.tracker.upsert_operator(
            operator_id="op_auto_01",
            name="Marcos Sierra",
            team_id="team_auto_created",
            lon=-5.95,
            lat=38.10,
        )
        # 3. Canal directo 1 a 1 entre dos operarios de terreno
        dm_ch = self.chat.open_direct_channel("op_hu_01", "op_za_01")
        # 4. Canal de incidente creado por un jefe de cuadrilla sin pasar explícitamente 'central'
        inc_ch = self.chat.create_incident_channel(
            channel_id="incident:flanco_norte",
            title="Flanco Norte Crítico",
            member_ids=["op_hu_01", "op_heli_01"],
            created_by="op_hu_01",
        )

        central_channels = {c["channel_id"]: c for c in self.chat.list_channels("central")}
        for expected_cid in (
            "global:operativo",
            "team:team_dyn_heli",
            "team:team_auto_created",
            dm_ch["channel_id"],
            inc_ch["channel_id"],
        ):
            self.assertIn(expected_cid, central_channels)
            self.assertIn("central", central_channels[expected_cid]["member_ids"])

            # Central puede escribir y leer en cada uno de estos canales
            msg, created = self.chat.send_message(
                channel_id=expected_cid,
                sender_id="central",
                encryption=_make_encrypted_envelope(sender_fp="fp_central_omni", seed=42),
                message_type="tactical_order",
            )
            self.assertTrue(created)
            self.assertIn("central", msg["recipients"])
            listed = self.chat.list_messages(expected_cid, participant_id="central")
            self.assertGreaterEqual(len(listed["messages"]), 1)

        # Un operario ajeno (op_za_02) no tiene acceso a team_dyn_heli, al DM ajeno ni al incidente
        for forbidden_cid in ("team:team_dyn_heli", dm_ch["channel_id"], inc_ch["channel_id"]):
            with self.assertRaises(PermissionError):
                self.chat.list_messages(forbidden_cid, participant_id="op_za_02")
            with self.assertRaises(PermissionError):
                self.chat.send_message(
                    channel_id=forbidden_cid,
                    sender_id="op_za_02",
                    encryption=_make_encrypted_envelope(sender_fp="fp_za2", seed=9),
                )

    def test_authorized_attachments_upload_download_and_sha256_integrity(self) -> None:
        """Verifica control de acceso en subida/descarga de adjuntos e integridad SHA-256."""
        cid_hu = team_channel_id("team_brif_huelva")
        png_bytes = _make_clean_png_bytes()
        pdf_bytes = _make_clean_pdf_bytes()

        att_img = self.chat.upload_attachment(
            sender_id="op_hu_01",
            filename="frente_llama.png",
            content_bytes=png_bytes,
            channel_id=cid_hu,
            declared_mime_type="image/png",
        )
        att_pdf = self.chat.upload_attachment(
            sender_id="op_hu_01",
            filename="sectorizacion.pdf",
            content_bytes=pdf_bytes,
            channel_id=cid_hu,
            declared_mime_type="application/pdf",
        )
        self.assertEqual(att_img["kind"], "image")
        self.assertEqual(att_pdf["kind"], "pdf")

        # Compañero del mismo escuadrón y Central pueden descargar ambos adjuntos
        for authorized_viewer in ("op_hu_02", "central"):
            meta_i, raw_i = self.chat.get_attachment_content(
                att_img["attachment_id"], participant_id=authorized_viewer
            )
            self.assertEqual(meta_i["attachment_id"], att_img["attachment_id"])
            self.assertGreater(len(raw_i), 0)

        # Operario de otro escuadrón (op_za_01) tiene prohibido subir o descargar en cid_hu
        with self.assertRaises(PermissionError):
            self.chat.upload_attachment(
                sender_id="op_za_01",
                filename="intruso.png",
                content_bytes=png_bytes,
                channel_id=cid_hu,
            )
        with self.assertRaises(PermissionError):
            self.chat.get_attachment_content(
                att_img["attachment_id"], participant_id="op_za_01"
            )

        # Otro miembro no puede adjuntar en send_message un archivo subido por op_hu_01
        with self.assertRaises(PermissionError):
            self.chat.send_message(
                channel_id=cid_hu,
                sender_id="op_hu_02",
                encryption=_make_encrypted_envelope(sender_fp="fp_hu2", seed=1),
                message_type="image",
                attachment_ids=[att_img["attachment_id"]],
            )

        # Ni op_hu_01 puede reutilizar el adjunto de cid_hu en otro canal distinto
        with self.assertRaises(PermissionError):
            self.chat.send_message(
                channel_id=juli_config.CHAT_GLOBAL_CHANNEL_ID,
                sender_id="op_hu_01",
                encryption=_make_encrypted_envelope(sender_fp="fp_hu1", seed=2),
                message_type="image",
                attachment_ids=[att_img["attachment_id"]],
            )

        # Envío válido por el autor en el canal correcto
        msg, created = self.chat.send_message(
            channel_id=cid_hu,
            sender_id="op_hu_01",
            encryption=_make_encrypted_envelope(sender_fp="fp_hu1", seed=3),
            message_type="attachment",
            attachment_ids=[att_img["attachment_id"], att_pdf["attachment_id"]],
        )
        self.assertTrue(created)
        self.assertEqual(len(msg["attachments"]), 2)

        # Corrupción en disco detectada por verificación SHA-256 al descargar
        disk_path = os.path.join(self.attachments_dir, att_pdf["storage_filename"])
        with open(disk_path, "ab") as f:
            f.write(b"\x00")
        with self.assertRaises(ValueError):
            self.chat.get_attachment_content(att_pdf["attachment_id"], participant_id="central")

    def test_recovery_from_corrupt_juli_chat_state_json(self) -> None:
        """Verifica que `JuliChatManager` se recupera limpiamente ante `juli_chat_state.json` corrupto."""
        corrupt_payloads = [
            "{corrupt_json_without_closing_brace",
            "[]",
            json.dumps({"identity_keys": {"bad": "not_a_dict"}}),
        ]
        for raw_corrupt in corrupt_payloads:
            with open(self.chat_state, "w", encoding="utf-8") as f:
                f.write(raw_corrupt)

            recovered = JuliChatManager(
                state_path=self.chat_state,
                tracker=self.tracker,
                attachments_dir=self.attachments_dir,
            )
            channels = {c["channel_id"]: c for c in recovered.list_channels("central")}
            self.assertIn(juli_config.CHAT_GLOBAL_CHANNEL_ID, channels)
            self.assertIn("team:team_brif_huelva", channels)
            self.assertIn("team:team_ume_zamora", channels)

            msg, created = recovered.send_message(
                channel_id=juli_config.CHAT_GLOBAL_CHANNEL_ID,
                sender_id="central",
                encryption=_make_encrypted_envelope(sender_fp="fp_rec", seed=55),
            )
            self.assertTrue(created)
            self.assertEqual(msg["server_seq"], 1)


# ===========================================================================
# 3. WALKIERADIOMANAGER + JULITRACKER (HISTORIAL >205, PRUEBA DE VIDA, CLAMPING)
# ===========================================================================
class TestWalkieRadioAndTrackerState(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name
        self.tracker_state = os.path.join(self.tmp_dir, "juli_state.json")
        self.tracker_geojson = os.path.join(self.tmp_dir, "juli_operators.geojson")
        self.radio_log = os.path.join(self.tmp_dir, "juli_radio_log.json")
        self.chat_state = os.path.join(self.tmp_dir, "juli_chat_state.json")
        self.attachments_dir = os.path.join(self.tmp_dir, "chat_attachments")
        self.cata_pred_path = os.path.join(self.tmp_dir, "cata_predictions.json")

        self.tracker = JuliTracker(
            state_path=self.tracker_state,
            geojson_path=self.tracker_geojson,
        )
        self.radio = WalkieRadioManager(
            tracker=self.tracker,
            log_path=self.radio_log,
        )
        self.chat = JuliChatManager(
            state_path=self.chat_state,
            tracker=self.tracker,
            attachments_dir=self.attachments_dir,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_rapid_switches_over_205_history_cap_200_and_disk_reload(self) -> None:
        """Ejecuta 212 conmutaciones rápidas alternando AT+CTGS, AT+CFREQ, AT+CTSG y BLE hex."""
        # Añadir un tercer escuadrón para rotar entre 3 frecuencias/talkgroups
        self.tracker.upsert_team(
            team_id="team_first_response_live",
            name=" Intervención Rápida TAC",
            unit_code="TAC-03",
            radio_channel="VHF-TAC",
        )

        # Consultas PEI sin cambio de estado
        q_freq = self.radio.execute_pei_command("op_hu_01", "AT+CNUMF?", simulated=True)
        self.assertEqual(q_freq["status"], "ok")
        q_list = self.radio.execute_pei_command("op_hu_01", "AT+CTGLIST?", simulated=True)
        self.assertEqual(len(q_list["frequencies"]), 3)

        ble_hex_ume = "41542b435447533d32303032"  # "AT+CTGS=2002"
        ble_hex_tac_prefixed = "0x" + "AT+CTSG=team_first_response_live".encode("utf-8").hex()

        switch_modes = [
            {"at_command": "AT+CTGS=2002"},                       # Talkgroup UME
            {"at_command": "AT+CFREQ=154.5250"},                  # VHF MHz BRIF Huelva
            {"at_command": "AT+CTSG=team_first_response_live"},   # Team ID directo
            {"at_command": "AT+CFREQ=391.2500"},                  # TETRA MHz UME
            {"at_command": "AT+CTGS=VHF-01"},                     # Nombre de canal BRIF
            {"ble_payload_hex": ble_hex_ume},                     # Trama BLE GATT hex sin 0x
            {"ble_payload_hex": ble_hex_tac_prefixed},            # Trama BLE GATT hex con 0x
            {"at_command": "AT+CTSG=team_brif_huelva"},           # Retorno a BRIF Huelva
        ]

        total_switches = 212
        all_switch_ids: list[str] = []
        for idx in range(total_switches):
            kwargs = switch_modes[idx % len(switch_modes)]
            rec = self.radio.switch_frequency(
                operator_id="op_hu_01",
                simulated=(idx % 2 == 0),
                note=f"rapid_switch_{idx + 1}",
                **kwargs,
            )
            all_switch_ids.append(rec["switch_id"])

        # El historial en memoria y en disco debe recortarse exactamente a las últimas 200 entradas
        self.assertEqual(len(self.radio.history), 200)
        self.assertEqual(self.radio.history[0]["switch_id"], all_switch_ids[total_switches - 200])
        self.assertEqual(self.radio.history[-1]["switch_id"], all_switch_ids[-1])
        self.assertEqual(self.radio.history[0]["note"], "rapid_switch_13")
        self.assertEqual(self.radio.history[-1]["note"], f"rapid_switch_{total_switches}")

        # get_history devuelve orden cronológico inverso (más reciente primero) con tope 200
        hist_api = self.radio.get_history(limit=500, operator_id="op_hu_01")
        self.assertEqual(len(hist_api), 200)
        self.assertEqual(hist_api[0]["switch_id"], all_switch_ids[-1])
        self.assertEqual(hist_api[-1]["switch_id"], all_switch_ids[12])

        # Recargar WalkieRadioManager y JuliTracker desde disco y verificar coherencia total
        reloaded_tracker = JuliTracker(
            state_path=self.tracker_state,
            geojson_path=self.tracker_geojson,
        )
        reloaded_radio = WalkieRadioManager(
            tracker=reloaded_tracker,
            log_path=self.radio_log,
        )
        self.assertEqual(len(reloaded_radio.history), 200)
        self.assertEqual(reloaded_radio.history[0]["switch_id"], all_switch_ids[12])
        self.assertEqual(reloaded_radio.history[-1]["switch_id"], all_switch_ids[-1])

        # El cambio 212 (índice 211 -> 211 % 8 == 3 -> AT+CFREQ=391.2500) dejó a op_hu_01 en team_ume_zamora
        op_reloaded = reloaded_tracker.operators["op_hu_01"]
        self.assertEqual(op_reloaded.team_id, "team_ume_zamora")
        self.assertEqual(op_reloaded.talkgroup_id, "2002")

        op_channels = {c["channel_id"] for c in self.chat.list_channels("op_hu_01")}
        self.assertIn("team:team_ume_zamora", op_channels)
        self.assertNotIn("team:team_brif_huelva", op_channels)

    async def test_interleaved_proof_of_life_transitions_and_squadron_handover(self) -> None:
        """Valida transiciones intercaladas de Prueba de Vida y cambio de destinatarios de escuadrón."""
        op = self.tracker.operators["op_hu_01"]
        t0 = datetime(2026, 7, 15, 10, 0, 0, tzinfo=timezone.utc)
        op.updated_at = t0.isoformat()
        op.last_moved_at = t0.isoformat()
        op.last_proof_of_life_at = t0.isoformat()
        qid = op.quadrant_location()["quadrant_id"]

        # 1. En t0 (recién movido y sin fuego), no hay alertas
        poll_0 = self.tracker.poll_proof_of_life_events(
            now=t0, cata_predictions_path=self.cata_pred_path
        )
        self.assertEqual(len(poll_0["new_alerts"]), 0)

        # 2. En t1 = t0 + 16 min (inmóvil >= 15 min), salta alerta "high" por immobile_timeout
        #    dirigida a Central y a su escuadrón inicial (team_brif_huelva)
        t1 = t0 + timedelta(minutes=16)
        poll_1 = self.tracker.poll_proof_of_life_events(
            now=t1, cata_predictions_path=self.cata_pred_path
        )
        hu1_alerts = [a for a in poll_1["new_alerts"] if a["operator_id"] == "op_hu_01"]
        self.assertEqual(len(hu1_alerts), 1)
        self.assertEqual(hu1_alerts[0]["reasons"], ["immobile_timeout"])
        self.assertEqual(hu1_alerts[0]["priority"], "high")
        self.assertEqual(
            hu1_alerts[0]["recipients"]["squadron"]["team_id"], "team_brif_huelva"
        )
        self.assertEqual(
            sorted(hu1_alerts[0]["recipients"]["squadron"]["member_ids"]),
            ["op_hu_02", "op_hu_03", "op_hu_04"],
        )

        # Re-sondeo 20s después sin cambios no re-emite evento duplicado
        poll_1_dup = self.tracker.poll_proof_of_life_events(
            now=t1 + timedelta(seconds=20), cata_predictions_path=self.cata_pred_path
        )
        self.assertEqual(
            [a for a in poll_1_dup["new_alerts"] if a["operator_id"] == "op_hu_01"], []
        )

        # 3. Entra fuego activo (estado 2) en el cuadrante de op_hu_01 Y el operario conmuta su
        #    walkie-talkie al escuadrón team_ume_zamora. La nueva razón ("quadrant_burning")
        #    escala la alerta a "critical" y cambia los destinatarios de escuadrón a team_ume_zamora.
        with open(self.cata_pred_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "active_and_predicted_cells": [
                        {
                            "quadrant_id": qid,
                            "quadrant_state": 2,
                            "state_label": "En llamas",
                            "fire_probability_t1": 0.94,
                        }
                    ]
                },
                f,
            )

        self.radio.switch_frequency(
            operator_id="op_hu_01",
            at_command="AT+CTSG=team_ume_zamora",
            simulated=True,
        )

        t2 = t1 + timedelta(minutes=1)
        poll_2 = self.tracker.poll_proof_of_life_events(
            now=t2, cata_predictions_path=self.cata_pred_path
        )
        hu1_fire_alerts = [a for a in poll_2["new_alerts"] if a["operator_id"] == "op_hu_01"]
        self.assertEqual(len(hu1_fire_alerts), 1)
        alert_escalated = hu1_fire_alerts[0]
        self.assertEqual(
            sorted(alert_escalated["reasons"]),
            ["immobile_timeout", "quadrant_burning"],
        )
        self.assertEqual(alert_escalated["priority"], "critical")
        self.assertEqual(
            alert_escalated["recipients"]["squadron"]["team_id"], "team_ume_zamora"
        )
        self.assertEqual(
            sorted(alert_escalated["recipients"]["squadron"]["member_ids"]),
            ["op_za_01", "op_za_02", "op_za_03"],
        )

        # Difusión de la alerta al chat y WebSocket usando instancias aisladas en tmp_dir
        temp_ws = ChatConnectionManager()
        ws_za1 = _MockAsyncWebSocket("ws_za1")
        ws_central = _MockAsyncWebSocket("ws_central")
        await temp_ws.connect("op_za_01", ws_za1)
        await temp_ws.connect("central", ws_central)

        with (
            mock.patch.object(juli_chat_module, "juli_chat", self.chat),
            mock.patch.object(juli_chat_module, "chat_ws_manager", temp_ws),
        ):
            await juli_chat_module.broadcast_proof_of_life_alerts_to_chat([alert_escalated])

        self.assertEqual(len(ws_za1.sent_messages), 1)
        self.assertEqual(ws_za1.sent_messages[0]["channel_id"], "team:team_ume_zamora")
        self.assertEqual(len(ws_central.sent_messages), 1)

        # 4. op_hu_01 confirma prueba de vida (confirm_proof_of_life) y se desplaza > 5m dentro del
        #    mismo cuadrante: desaparece 'immobile_timeout', pero persiste 'quadrant_burning'
        t3 = t2 + timedelta(minutes=1)
        self.tracker.confirm_proof_of_life(
            "op_hu_01",
            lon=op.lon + 0.0001,
            lat=op.lat,
            note="Operario consciente en línea de defensa",
            timestamp=t3.isoformat(),
        )
        poll_3 = self.tracker.poll_proof_of_life_events(
            now=t3 + timedelta(seconds=15), cata_predictions_path=self.cata_pred_path
        )
        st_hu1 = poll_3["evaluation"]["statuses_by_operator"]["op_hu_01"]
        self.assertTrue(st_hu1["triggered"])
        self.assertEqual(st_hu1["reasons"], ["quadrant_burning"])
        self.assertNotIn("op_hu_01", poll_3["resolved_operator_ids"])

        # 5. Extinción del fuego en el cuadrante (fire_clear): la alerta de op_hu_01 queda resuelta
        with open(self.cata_pred_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "active_and_predicted_cells": [
                        {"quadrant_id": qid, "quadrant_state": 0, "state_label": "Controlado"}
                    ]
                },
                f,
            )

        t4 = t3 + timedelta(minutes=1)
        poll_4 = self.tracker.poll_proof_of_life_events(
            now=t4, cata_predictions_path=self.cata_pred_path
        )
        self.assertIn("op_hu_01", poll_4["resolved_operator_ids"])
        resolved_events = [
            e
            for e in poll_4["events"]
            if e.get("event") == "proof_of_life_resolved" and e.get("operator_id") == "op_hu_01"
        ]
        self.assertEqual(len(resolved_events), 1)
        self.assertEqual(resolved_events[0]["team_id"], "team_ume_zamora")

    def test_subcoordinate_clamping_and_corrupt_state_recovery(self) -> None:
        """Verifica clamping de subcoordenadas [0, 1000) y [0, 1) y recuperación ante JSON corrupto."""
        qid = "ES1K:L0:Y02209:X02996"

        # Clamping en quadrant_subcoords_to_lonlat para offset_x_m / offset_y_m fuera de [0, 1000)
        lon_min, lat_max = juli_coords.quadrant_subcoords_to_lonlat(
            qid, offset_x_m=0.0, offset_y_m=999.99
        )
        lon_clamp_1, lat_clamp_1 = juli_coords.quadrant_subcoords_to_lonlat(
            qid, offset_x_m=-450.0, offset_y_m=3200.0
        )
        self.assertEqual((lon_clamp_1, lat_clamp_1), (lon_min, lat_max))

        # Clamping en quadrant_subcoords_to_lonlat para sub_x_norm / sub_y_norm fuera de [0, 1)
        lon_clamp_2, lat_clamp_2 = juli_coords.quadrant_subcoords_to_lonlat(
            qid, sub_x_norm=-0.75, sub_y_norm=2.4
        )
        self.assertEqual((lon_clamp_2, lat_clamp_2), (lon_min, lat_max))

        # Verificar alta y actualización de operario con subcoordenadas en rango y fuera de rango
        op_clamped = self.tracker.upsert_operator(
            operator_id="op_clamp_test",
            name="Operario Subcoords",
            team_id="team_brif_huelva",
            quadrant_id=qid,
            offset_x_m=500.0,
            offset_y_m=500.0,
            battery_pct=150,  # también se clampea a 100
        )
        self.assertEqual(op_clamped.battery_pct, 100)
        loc = op_clamped.quadrant_location()
        self.assertEqual(loc["quadrant_id"], qid)
        self.assertGreaterEqual(loc["offset_x_m"], 0.0)
        self.assertLess(loc["offset_x_m"], 1000.0)
        self.assertGreaterEqual(loc["offset_y_m"], 0.0)
        self.assertLess(loc["offset_y_m"], 1000.0)
        self.assertGreaterEqual(loc["sub_x_norm"], 0.0)
        self.assertLess(loc["sub_x_norm"], 1.0)
        self.assertGreaterEqual(loc["sub_y_norm"], 0.0)
        self.assertLess(loc["sub_y_norm"], 1.0)

        # Recuperación ante archivos de estado JSON corruptos en JuliTracker, WalkieRadioManager y CATA
        with open(self.tracker_state, "w", encoding="utf-8") as f:
            f.write("{corrupt_tracker_state")
        with open(self.radio_log, "w", encoding="utf-8") as f:
            f.write("{corrupt_radio_log")
        with open(self.cata_pred_path, "w", encoding="utf-8") as f:
            f.write("{corrupt_cata_predictions")

        recovered_tracker = JuliTracker(
            state_path=self.tracker_state,
            geojson_path=self.tracker_geojson,
        )
        self.assertGreaterEqual(len(recovered_tracker.teams), 2)
        self.assertIn("op_hu_01", recovered_tracker.operators)

        recovered_radio = WalkieRadioManager(
            tracker=recovered_tracker,
            log_path=self.radio_log,
        )
        self.assertEqual(recovered_radio.history, [])

        burning = load_burning_quadrants(self.cata_pred_path)
        self.assertEqual(burning, {})


if __name__ == "__main__":
    unittest.main()
