"""Lógica de mensajería y cifrado E2EE para el chat táctico de JULI.

Soporta:
  - Directorio de claves públicas ECDH P-256 (y firma opcional ECDSA P-256) con validación
    en servidor y códigos de seguridad estilo Signal (`safety_code`).
  - Canales directos 1 a 1 (`dm:{a}:{b}`), canales de escuadrón (`team:{team_id}`),
    canal operativo general (`global:operativo`) y salas de incidente (`incident:{id}`).
  - Distribución de claves de sala AES-256-GCM envueltas por época (`key_epoch`) y
    rotación de claves ante altas/bajas de operarios.
  - Almacenamiento únicamente de sobres cifrados (cero texto plano en disco/servidor),
    idempotencia de reintentos (`client_msg_id`), acuses de entrega/lectura y difusión WebSocket.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import config
from .attachment_security import inspect_and_sanitize_attachment
from .chat_crypto import (
    compute_jwk_thumbprint,
    compute_pair_safety_code,
    validate_ec_p256_jwk,
    validate_encrypted_envelope,
    validate_wrapped_key_entry,
)
from .tracker import JuliTracker, juli_tracker

logger = logging.getLogger("juli.chat")

ALLOWED_MESSAGE_TYPES = frozenset(
    {
        "text",
        "image",
        "pdf",
        "attachment",
        "location_share",
        "tactical_order",
        "sos_ack",
        "system_alert",
    }
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def direct_channel_id(participant_a: str, participant_b: str) -> str:
    """Identificador determinista para un chat directo 1 a 1."""
    a = participant_a.strip()
    b = participant_b.strip()
    if not a or not b or a == b:
        raise ValueError("Se requieren dos participantes distintos para abrir un chat directo.")
    p1, p2 = sorted((a, b))
    return f"dm:{p1}:{p2}"


def team_channel_id(team_id: str) -> str:
    """Identificador canónico del canal de un escuadrón."""
    return f"team:{team_id.strip()}"


@dataclass
class IdentityKeyRecord:
    """Registro público de clave criptográfica de un participante (nunca clave privada)."""

    participant_id: str
    display_name: str
    role: str
    team_id: str | None
    ecdh_public_jwk: dict[str, str]
    fingerprint: str
    short_fingerprint: str
    signing_public_jwk: dict[str, str] | None = None
    device_label: str = ""
    key_version: int = 1
    previous_fingerprint: str | None = None
    revoked: bool = False
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatChannel:
    """Metadatos y membresía autorizada de una sala/canal de chat."""

    channel_id: str
    channel_type: str  # "direct" | "team" | "global" | "incident"
    title: str
    member_ids: list[str]
    team_id: str | None = None
    current_key_epoch: int = 1
    created_by: str = config.CHAT_CENTRAL_ID
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatAttachment:
    """Adjunto verificado (imagen o PDF) almacenado tras inspección antimalware."""

    attachment_id: str
    channel_id: str
    sender_id: str
    kind: str  # "image" | "pdf"
    format: str
    safe_filename: str
    mime_type: str
    extension: str
    storage_filename: str
    size_bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None
    security_scan: dict[str, Any] = field(default_factory=dict)
    uploaded_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "download_url": f"/api/juli/chat/attachments/{self.attachment_id}",
        }


@dataclass
class ChatMessage:
    """Mensaje persistido en JULI con carga cifrada opaca (o alerta del sistema)."""

    message_id: str
    client_msg_id: str
    channel_id: str
    server_seq: int
    sender_id: str
    sender_name: str
    sender_role: str
    recipients: list[str]
    encryption: dict[str, Any]
    message_type: str = "text"
    reply_to_id: str | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    sent_at: str = field(default_factory=_now_iso)
    delivered_to: list[str] = field(default_factory=list)
    read_by: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChatConnectionManager:
    """Gestor de sockets activos para `/ws/chat` indexado por `participant_id`."""

    def __init__(self) -> None:
        self._connections: dict[str, list[Any]] = {}

    async def connect(self, participant_id: str, websocket: Any) -> None:
        await websocket.accept()
        self._connections.setdefault(participant_id, []).append(websocket)

    def disconnect(self, participant_id: str, websocket: Any) -> None:
        sockets = self._connections.get(participant_id)
        if not sockets:
            return
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            self._connections.pop(participant_id, None)

    def online_participants(self) -> list[str]:
        return sorted(self._connections.keys())

    async def send_to_participant(self, participant_id: str, payload: dict[str, Any]) -> None:
        sockets = list(self._connections.get(participant_id, ()))
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(participant_id, ws)

    async def broadcast_to_participants(
        self,
        participant_ids: list[str],
        payload: dict[str, Any],
        exclude_participant: str | None = None,
    ) -> None:
        seen: set[str] = set()
        for pid in participant_ids:
            if pid in seen or pid == exclude_participant:
                continue
            seen.add(pid)
            await self.send_to_participant(pid, payload)


class JuliChatManager:
    """Controlador principal del chat E2EE táctico para Central y operarios de JULI."""

    def __init__(
        self,
        state_path: str = config.DEFAULT_CHAT_STATE_PATH,
        tracker: JuliTracker | None = None,
        attachments_dir: str = config.DEFAULT_CHAT_ATTACHMENTS_DIR,
    ) -> None:
        self.state_path = state_path
        self.tracker = tracker or juli_tracker
        self.attachments_dir = attachments_dir
        self.identity_keys: dict[str, IdentityKeyRecord] = {}
        self.channels: dict[str, ChatChannel] = {}
        # room_keys[channel_id][str(key_epoch)] -> bundle con wrapped_keys[member_id]
        self.room_keys: dict[str, dict[str, dict[str, Any]]] = {}
        self.attachments: dict[str, ChatAttachment] = {}
        self.messages: dict[str, list[ChatMessage]] = {}
        self._channel_seq: dict[str, int] = {}
        self._load_or_init()

    # -----------------------------------------------------------------------
    # Resolución de participantes y sincronización con `JuliTracker`
    # -----------------------------------------------------------------------
    def _resolve_participant(self, participant_id: str) -> dict[str, Any] | None:
        pid = participant_id.strip()
        if not pid:
            return None
        if pid == config.CHAT_CENTRAL_ID:
            return {
                "participant_id": config.CHAT_CENTRAL_ID,
                "display_name": "Central de Coordinación",
                "role": "central",
                "team_id": None,
            }
        op = self.tracker.operators.get(pid)
        if op is not None:
            return {
                "participant_id": op.operator_id,
                "display_name": f"{op.name} ({op.callsign or op.operator_id})",
                "role": op.role,
                "team_id": op.team_id,
            }
        ident = self.identity_keys.get(pid)
        if ident is not None:
            return {
                "participant_id": ident.participant_id,
                "display_name": ident.display_name,
                "role": ident.role,
                "team_id": ident.team_id,
            }
        return None

    def _require_participant(self, participant_id: str) -> dict[str, Any]:
        info = self._resolve_participant(participant_id)
        if info is None:
            raise KeyError(
                f"Participante '{participant_id}' no registrado en JULI (ni es 'central')."
            )
        return info

    def _team_roster_ids(self, team_id: str) -> list[str]:
        ops = [op.operator_id for op in self.tracker.operators.values() if op.team_id == team_id]
        return sorted(set([*ops, config.CHAT_CENTRAL_ID]))

    def _global_roster_ids(self) -> list[str]:
        return sorted(set([*self.tracker.operators.keys(), config.CHAT_CENTRAL_ID]))

    def _sync_default_channels(self) -> None:
        """Mantiene sincronizados `global:operativo` y los canales `team:{id}` con el tracker."""
        now_str = _now_iso()
        global_members = self._global_roster_ids()
        if config.CHAT_GLOBAL_CHANNEL_ID not in self.channels:
            self.channels[config.CHAT_GLOBAL_CHANNEL_ID] = ChatChannel(
                channel_id=config.CHAT_GLOBAL_CHANNEL_ID,
                channel_type="global",
                title="Canal Operativo General (Central + Terreno)",
                member_ids=global_members,
                created_at=now_str,
                updated_at=now_str,
            )
        else:
            ch = self.channels[config.CHAT_GLOBAL_CHANNEL_ID]
            ch.member_ids = sorted(set([*ch.member_ids, *global_members]))

        for tid, team in self.tracker.teams.items():
            cid = team_channel_id(tid)
            roster = self._team_roster_ids(tid)
            if cid not in self.channels:
                self.channels[cid] = ChatChannel(
                    channel_id=cid,
                    channel_type="team",
                    title=f"Escuadrón {team.unit_code} — {team.name}",
                    team_id=tid,
                    member_ids=roster,
                    created_at=now_str,
                    updated_at=now_str,
                )
            else:
                ch = self.channels[cid]
                ch.title = f"Escuadrón {team.unit_code} — {team.name}"
                ch.member_ids = roster

        # Supervisión global: Central tiene acceso de lectura y escritura en todos los canales
        for ch in self.channels.values():
            if config.CHAT_CENTRAL_ID not in ch.member_ids:
                ch.member_ids = sorted([*ch.member_ids, config.CHAT_CENTRAL_ID])

    def _load_or_init(self) -> None:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    raw = json.load(f)
                self.identity_keys = {
                    pid: IdentityKeyRecord(**data)
                    for pid, data in raw.get("identity_keys", {}).items()
                }
                self.channels = {
                    cid: ChatChannel(**data) for cid, data in raw.get("channels", {}).items()
                }
                self.room_keys = raw.get("room_keys", {})
                self.attachments = {
                    aid: ChatAttachment(**adata)
                    for aid, adata in raw.get("attachments", {}).items()
                }
                self.messages = {
                    cid: [ChatMessage(**mdata) for mdata in mlist]
                    for cid, mlist in raw.get("messages", {}).items()
                }
                self._channel_seq = {
                    cid: int(seq) for cid, seq in raw.get("channel_seq", {}).items()
                }
            except Exception as exc:
                logger.warning("Estado de chat corrupto o ilegible en %s: %s", self.state_path, exc)
        self._sync_default_channels()

    def save_state(self) -> None:
        if not self.state_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
        payload = {
            "protocol": "JULI-E2EE-v1",
            "updated_at": _now_iso(),
            "identity_keys": {pid: rec.to_dict() for pid, rec in self.identity_keys.items()},
            "channels": {cid: ch.to_dict() for cid, ch in self.channels.items()},
            "room_keys": self.room_keys,
            "attachments": {
                aid: {k: v for k, v in asdict(att).items()} for aid, att in self.attachments.items()
            },
            "channel_seq": self._channel_seq,
            "messages": {cid: [m.to_dict() for m in mlist] for cid, mlist in self.messages.items()},
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # -----------------------------------------------------------------------
    # Directorio de Claves Públicas E2EE y Verificación (Safety Code)
    # -----------------------------------------------------------------------
    def register_identity_key(
        self,
        participant_id: str,
        ecdh_public_jwk: dict[str, Any],
        signing_public_jwk: dict[str, Any] | None = None,
        device_label: str = "",
        display_name: str | None = None,
    ) -> dict[str, Any]:
        """Registra o rota la clave pública ECDH P-256 de un participante."""
        pid = participant_id.strip()
        info = self._resolve_participant(pid)
        if info is None:
            raise KeyError(
                f"No se puede registrar clave: '{pid}' no existe como operario ni 'central'."
            )

        clean_ecdh = validate_ec_p256_jwk(ecdh_public_jwk, label="ECDH")
        clean_sig = (
            validate_ec_p256_jwk(signing_public_jwk, label="ECDSA")
            if signing_public_jwk is not None
            else None
        )
        thumb = compute_jwk_thumbprint(clean_ecdh)

        prev = self.identity_keys.get(pid)
        key_version = 1
        previous_fp = None
        if prev is not None and not prev.revoked and prev.fingerprint == thumb["fingerprint"]:
            key_version = prev.key_version
            previous_fp = prev.previous_fingerprint
        elif prev is not None:
            key_version = prev.key_version + 1
            previous_fp = prev.fingerprint

        rec = IdentityKeyRecord(
            participant_id=pid,
            display_name=display_name or info["display_name"],
            role=info["role"],
            team_id=info["team_id"],
            ecdh_public_jwk=clean_ecdh,
            signing_public_jwk=clean_sig,
            fingerprint=thumb["fingerprint"],
            short_fingerprint=thumb["short_fingerprint"],
            device_label=device_label.strip(),
            key_version=key_version,
            previous_fingerprint=previous_fp,
            revoked=False,
            updated_at=_now_iso(),
        )
        self.identity_keys[pid] = rec
        self._sync_default_channels()
        self.save_state()
        return rec.to_dict()

    def revoke_identity_key(self, participant_id: str) -> dict[str, Any]:
        pid = participant_id.strip()
        rec = self.identity_keys.get(pid)
        if rec is None:
            raise KeyError(f"El participante '{pid}' no tiene clave registrada en el directorio.")
        rec.revoked = True
        rec.updated_at = _now_iso()
        self.save_state()
        return rec.to_dict()

    def list_identity_keys(
        self,
        team_id: str | None = None,
        viewer_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Devuelve el directorio público de claves, añadiendo `safety_code` relativo al lector."""
        viewer_rec = self.identity_keys.get(viewer_id.strip()) if viewer_id else None
        results: list[dict[str, Any]] = []
        for rec in self.identity_keys.values():
            if team_id and rec.team_id != team_id and rec.participant_id != config.CHAT_CENTRAL_ID:
                continue
            entry = rec.to_dict()
            if (
                viewer_rec is not None
                and not viewer_rec.revoked
                and not rec.revoked
                and rec.participant_id != viewer_rec.participant_id
            ):
                entry["safety_code"] = compute_pair_safety_code(
                    viewer_rec.fingerprint, rec.fingerprint
                )
            results.append(entry)
        return results

    def get_safety_code(self, participant_a: str, participant_b: str) -> dict[str, Any]:
        rec_a = self.identity_keys.get(participant_a.strip())
        rec_b = self.identity_keys.get(participant_b.strip())
        if rec_a is None or rec_a.revoked:
            raise KeyError(f"Clave activa no encontrada para '{participant_a}'.")
        if rec_b is None or rec_b.revoked:
            raise KeyError(f"Clave activa no encontrada para '{participant_b}'.")
        return {
            "participants": sorted([rec_a.participant_id, rec_b.participant_id]),
            "fingerprints": {
                rec_a.participant_id: rec_a.short_fingerprint,
                rec_b.participant_id: rec_b.short_fingerprint,
            },
            "safety_code": compute_pair_safety_code(rec_a.fingerprint, rec_b.fingerprint),
        }

    # -----------------------------------------------------------------------
    # Gestión de Canales y Envoltura de Claves de Sala (`key_epoch`)
    # -----------------------------------------------------------------------
    def has_channel_access(self, participant_id: str, channel: ChatChannel) -> bool:
        """Central ('central') tiene acceso de supervisión y habla en todos los canales."""
        pid = participant_id.strip()
        return pid == config.CHAT_CENTRAL_ID or pid in channel.member_ids

    def channel_recipients(self, channel: ChatChannel) -> list[str]:
        """Devuelve miembros del canal incluyendo siempre a Central."""
        return sorted(set([*channel.member_ids, config.CHAT_CENTRAL_ID]))

    def open_direct_channel(self, participant_a: str, participant_b: str) -> dict[str, Any]:
        info_a = self._require_participant(participant_a)
        info_b = self._require_participant(participant_b)
        cid = direct_channel_id(info_a["participant_id"], info_b["participant_id"])
        if cid not in self.channels:
            now_str = _now_iso()
            members = sorted(
                {info_a["participant_id"], info_b["participant_id"], config.CHAT_CENTRAL_ID}
            )
            self.channels[cid] = ChatChannel(
                channel_id=cid,
                channel_type="direct",
                title=f"{info_a['display_name']} <-> {info_b['display_name']}",
                member_ids=members,
                created_by=info_a["participant_id"],
                created_at=now_str,
                updated_at=now_str,
            )
            self.save_state()
        return self.channels[cid].to_dict()

    def create_incident_channel(
        self,
        channel_id: str,
        title: str,
        member_ids: list[str],
        created_by: str = config.CHAT_CENTRAL_ID,
    ) -> dict[str, Any]:
        cid = channel_id.strip()
        if not cid:
            raise ValueError("El 'channel_id' no puede estar vacío.")
        validated_members = sorted(
            {
                *(
                    self._require_participant(pid)["participant_id"]
                    for pid in [*member_ids, created_by]
                ),
                config.CHAT_CENTRAL_ID,
            }
        )
        now_str = _now_iso()
        ch = ChatChannel(
            channel_id=cid,
            channel_type="incident",
            title=title.strip() or cid,
            member_ids=validated_members,
            created_by=created_by,
            created_at=now_str,
            updated_at=now_str,
        )
        self.channels[cid] = ch
        self.save_state()
        return ch.to_dict()

    def _get_or_auto_channel(self, channel_id: str | None = None) -> ChatChannel:
        self._sync_default_channels()
        cid = (channel_id or config.CHAT_GLOBAL_CHANNEL_ID).strip() or config.CHAT_GLOBAL_CHANNEL_ID
        if cid in self.channels:
            return self.channels[cid]
        if cid.startswith("dm:"):
            parts = cid.split(":", 2)
            if len(parts) == 3:
                self.open_direct_channel(parts[1], parts[2])
                return self.channels[cid]
        raise KeyError(f"No existe el canal de chat '{channel_id}'.")

    def list_channels(self, participant_id: str | None = None) -> list[dict[str, Any]]:
        self._sync_default_channels()
        pid = participant_id.strip() if participant_id else None
        out: list[dict[str, Any]] = []
        for ch in self.channels.values():
            if pid and not self.has_channel_access(pid, ch):
                continue
            msgs = self.messages.get(ch.channel_id, [])
            last_msg = msgs[-1].to_dict() if msgs else None
            unread = (
                sum(1 for m in msgs if m.sender_id != pid and pid not in m.read_by) if pid else 0
            )
            entry = {
                **ch.to_dict(),
                "is_default": ch.channel_id == config.CHAT_GLOBAL_CHANNEL_ID,
                "message_count": len(msgs),
                "last_seq": self._channel_seq.get(ch.channel_id, 0),
                "last_message": last_msg,
                "has_wrapped_key_for_participant": bool(
                    pid
                    and pid
                    in self.room_keys.get(ch.channel_id, {})
                    .get(str(ch.current_key_epoch), {})
                    .get("wrapped_keys", {})
                ),
            }
            if pid:
                entry["unread_count"] = unread
            out.append(entry)
        out.sort(key=lambda item: (0 if item["is_default"] else 1, item["channel_id"]))
        return out

    def publish_channel_keys(
        self,
        channel_id: str,
        sender_id: str,
        wrapped_keys: dict[str, dict[str, Any]],
        key_epoch: int | None = None,
        sender_key_fingerprint: str = "",
        rotate_epoch: bool = False,
    ) -> dict[str, Any]:
        """Almacena claves de sala AES-256 envueltas por miembro para un canal grupal/escuadrón."""
        ch = self._get_or_auto_channel(channel_id)
        if not self.has_channel_access(sender_id, ch):
            raise PermissionError(
                f"'{sender_id}' no pertenece al canal '{ch.channel_id}' para distribuir claves."
            )
        if not wrapped_keys:
            raise ValueError("Se requiere al menos una clave envuelta en 'wrapped_keys'.")

        sender_ident = self.identity_keys.get(sender_id)
        if sender_ident is not None and sender_ident.revoked:
            raise PermissionError(f"La clave de '{sender_id}' fue revocada.")
        resolved_fp = sender_key_fingerprint or (sender_ident.fingerprint if sender_ident else "")
        if not resolved_fp:
            raise ValueError(
                "Se requiere 'sender_key_fingerprint' o haber registrado clave pública previa."
            )

        target_epoch = (
            ch.current_key_epoch + 1 if rotate_epoch else int(key_epoch or ch.current_key_epoch)
        )
        if target_epoch < 1:
            raise ValueError("'key_epoch' debe ser >= 1.")

        validated_bundles: dict[str, dict[str, Any]] = {}
        for member_id, bundle in wrapped_keys.items():
            if member_id not in ch.member_ids:
                raise ValueError(
                    f"El destinatario '{member_id}' no pertenece al canal '{ch.channel_id}'."
                )
            validated_bundles[member_id] = validate_wrapped_key_entry(bundle, member_id)

        epoch_key = str(target_epoch)
        ch_bundles = self.room_keys.setdefault(ch.channel_id, {})
        existing = ch_bundles.get(epoch_key)
        merged_wrapped = dict(existing.get("wrapped_keys", {})) if existing else {}
        merged_wrapped.update(validated_bundles)

        now_str = _now_iso()
        record = {
            "channel_id": ch.channel_id,
            "key_epoch": target_epoch,
            "distributed_by": sender_id,
            "sender_key_fingerprint": resolved_fp,
            "distributor_ecdh_public_jwk": (sender_ident.ecdh_public_jwk if sender_ident else None),
            "updated_at": now_str,
            "wrapped_keys": merged_wrapped,
        }
        ch_bundles[epoch_key] = record
        ch.current_key_epoch = max(ch.current_key_epoch, target_epoch)
        ch.updated_at = now_str
        self.save_state()
        return {
            "channel_id": ch.channel_id,
            "key_epoch": target_epoch,
            "distributed_by": sender_id,
            "sender_key_fingerprint": resolved_fp,
            "recipients": sorted(validated_bundles.keys()),
            "updated_at": now_str,
        }

    def get_channel_key_for_participant(
        self,
        channel_id: str,
        participant_id: str,
        key_epoch: int | None = None,
    ) -> dict[str, Any]:
        """Devuelve únicamente el sobre de clave de sala cifrado para `participant_id`."""
        ch = self._get_or_auto_channel(channel_id)
        pid = participant_id.strip()
        if not self.has_channel_access(pid, ch):
            raise PermissionError(f"'{pid}' no es miembro del canal '{ch.channel_id}'.")

        epoch = int(key_epoch or ch.current_key_epoch)
        bundle = self.room_keys.get(ch.channel_id, {}).get(str(epoch))
        if bundle is None or pid not in bundle.get("wrapped_keys", {}):
            raise KeyError(
                f"No hay clave de sala envuelta para '{pid}' en '{ch.channel_id}' (epoch {epoch})."
            )
        return {
            "channel_id": ch.channel_id,
            "key_epoch": epoch,
            "distributed_by": bundle["distributed_by"],
            "sender_key_fingerprint": bundle["sender_key_fingerprint"],
            "distributor_ecdh_public_jwk": bundle.get("distributor_ecdh_public_jwk"),
            "updated_at": bundle["updated_at"],
            "wrapped_key": bundle["wrapped_keys"][pid],
        }

    # -----------------------------------------------------------------------
    # Adjuntos Seguros (Imágenes y PDF verificados antes de difundir)
    # -----------------------------------------------------------------------
    def upload_attachment(
        self,
        sender_id: str,
        filename: str,
        content_bytes: bytes,
        channel_id: str | None = None,
        declared_mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Inspecciona y sanitiza una imagen o PDF antes de almacenarlo y permitir su envío."""
        sid = sender_id.strip()
        self._require_participant(sid)
        ch = self._get_or_auto_channel(channel_id)
        if not self.has_channel_access(sid, ch):
            raise PermissionError(
                f"'{sid}' no tiene permiso para subir adjuntos en '{ch.channel_id}'."
            )

        inspected = inspect_and_sanitize_attachment(
            content_bytes=content_bytes,
            filename=filename,
            declared_mime_type=declared_mime_type,
        )
        aid = f"att_{uuid.uuid4().hex[:16]}"
        storage_filename = f"{aid}.{inspected['extension']}"
        os.makedirs(self.attachments_dir, exist_ok=True)
        dest_path = os.path.join(self.attachments_dir, storage_filename)
        with open(dest_path, "wb") as f:
            f.write(inspected["clean_bytes"])

        att = ChatAttachment(
            attachment_id=aid,
            channel_id=ch.channel_id,
            sender_id=sid,
            kind=inspected["kind"],
            format=inspected["format"],
            safe_filename=inspected["safe_filename"],
            mime_type=inspected["mime_type"],
            extension=inspected["extension"],
            storage_filename=storage_filename,
            size_bytes=inspected["size_bytes"],
            sha256=inspected["sha256"],
            width=inspected["width"],
            height=inspected["height"],
            security_scan=inspected["security_scan"],
        )
        self.attachments[aid] = att
        self.save_state()
        return att.to_dict()

    def get_attachment_content(
        self,
        attachment_id: str,
        participant_id: str,
    ) -> tuple[dict[str, Any], bytes]:
        """Recupera un adjunto verificado si el solicitante pertenece al canal o es Central."""
        aid = attachment_id.strip()
        att = self.attachments.get(aid)
        if att is None:
            raise KeyError(f"No existe el adjunto '{attachment_id}'.")
        ch = self._get_or_auto_channel(att.channel_id)
        pid = participant_id.strip()
        if not self.has_channel_access(pid, ch):
            raise PermissionError(
                f"'{pid}' no tiene permiso para descargar adjuntos de '{ch.channel_id}'."
            )
        file_path = os.path.join(self.attachments_dir, att.storage_filename)
        if not os.path.exists(file_path):
            raise KeyError(f"Archivo físico no encontrado para el adjunto '{attachment_id}'.")
        with open(file_path, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() != att.sha256:
            raise ValueError(
                "Integridad comprometida: el checksum SHA-256 del adjunto no coincide."
            )
        return att.to_dict(), data

    # -----------------------------------------------------------------------
    # Envío, Historial y Acuses de Mensajes Cifrados E2EE
    # -----------------------------------------------------------------------
    def send_message(
        self,
        channel_id: str | None,
        sender_id: str,
        encryption: dict[str, Any],
        message_type: str = "text",
        client_msg_id: str | None = None,
        reply_to_id: str | None = None,
        attachment_ids: list[str] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Valida y persiste un mensaje E2EE (adjuntos opcionales). Devuelve `(msg, created)`."""
        if message_type not in ALLOWED_MESSAGE_TYPES or message_type == "system_alert":
            raise ValueError(
                f"Tipo de mensaje '{message_type}' inválido. Válidos: "
                f"{sorted(ALLOWED_MESSAGE_TYPES - {'system_alert'})}."
            )

        ch = self._get_or_auto_channel(channel_id)
        sid = sender_id.strip()
        sender_info = self._require_participant(sid)
        if not self.has_channel_access(sid, ch):
            raise PermissionError(f"'{sid}' no tiene permiso para escribir en '{ch.channel_id}'.")

        cmsg_id = (client_msg_id or uuid.uuid4().hex).strip()
        existing_list = self.messages.setdefault(ch.channel_id, [])
        for existing in existing_list:
            if existing.sender_id == sid and existing.client_msg_id == cmsg_id:
                return existing.to_dict(), False

        normalized_enc = validate_encrypted_envelope(encryption)

        resolved_attachments: list[dict[str, Any]] = []
        for aid in attachment_ids or []:
            att = self.attachments.get(str(aid).strip())
            if att is None:
                raise KeyError(f"Adjunto '{aid}' no encontrado o no verificado previamente.")
            if not att.security_scan.get("verified"):
                raise ValueError(f"El adjunto '{aid}' no superó la inspección de seguridad.")
            if att.channel_id != ch.channel_id:
                raise PermissionError(
                    f"El adjunto '{aid}' pertenece a otro canal ('{att.channel_id}')."
                )
            if att.sender_id != sid:
                raise PermissionError(
                    f"El adjunto '{aid}' fue subido por otro emisor ('{att.sender_id}')."
                )
            resolved_attachments.append(att.to_dict())

        sender_ident = self.identity_keys.get(sid)
        if sender_ident is not None:
            if sender_ident.revoked:
                raise PermissionError(f"La clave de identidad de '{sid}' ha sido revocada.")
            fp = normalized_enc.get("sender_key_fingerprint", "")
            if fp and fp not in (sender_ident.fingerprint, sender_ident.short_fingerprint):
                raise ValueError(
                    "El 'sender_key_fingerprint' no coincide con la clave pública registrada."
                )

        seq = self._channel_seq.get(ch.channel_id, 0) + 1
        self._channel_seq[ch.channel_id] = seq
        now_str = _now_iso()
        msg = ChatMessage(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            client_msg_id=cmsg_id,
            channel_id=ch.channel_id,
            server_seq=seq,
            sender_id=sid,
            sender_name=sender_info["display_name"],
            sender_role=sender_info["role"],
            recipients=self.channel_recipients(ch),
            encryption=normalized_enc,
            message_type=message_type,
            reply_to_id=reply_to_id,
            attachments=resolved_attachments,
            sent_at=now_str,
            delivered_to=[sid],
            read_by={sid: now_str},
        )
        existing_list.append(msg)
        if len(existing_list) > config.CHAT_MAX_MESSAGES_PER_CHANNEL:
            del existing_list[: len(existing_list) - config.CHAT_MAX_MESSAGES_PER_CHANNEL]
        ch.updated_at = now_str
        self.save_state()
        return msg.to_dict(), True

    def list_messages(
        self,
        channel_id: str | None,
        participant_id: str,
        since_seq: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Recupera historial cifrado de un canal verificando pertenencia del solicitante."""
        ch = self._get_or_auto_channel(channel_id)
        pid = participant_id.strip()
        if not self.has_channel_access(pid, ch):
            raise PermissionError(f"'{pid}' no tiene acceso al canal '{ch.channel_id}'.")

        all_msgs = self.messages.get(ch.channel_id, [])
        filtered = [m for m in all_msgs if m.server_seq > since_seq]
        sliced = filtered[-max(1, min(limit, config.CHAT_MAX_MESSAGES_PER_CHANNEL)) :]
        return {
            "channel": ch.to_dict(),
            "last_seq": self._channel_seq.get(ch.channel_id, 0),
            "messages": [m.to_dict() for m in sliced],
        }

    def ack_messages(
        self,
        channel_id: str | None,
        participant_id: str,
        message_ids: list[str],
        status: str = "read",
    ) -> dict[str, Any]:
        """Marca mensajes como entregados (`delivered`) o leídos (`read`)."""
        if status not in ("delivered", "read"):
            raise ValueError("El estado de acuse debe ser 'delivered' o 'read'.")
        ch = self._get_or_auto_channel(channel_id)
        pid = participant_id.strip()
        if not self.has_channel_access(pid, ch):
            raise PermissionError(f"'{pid}' no pertenece al canal '{ch.channel_id}'.")

        target_ids = set(message_ids)
        now_str = _now_iso()
        updated_ids: list[str] = []
        for msg in self.messages.get(ch.channel_id, []):
            if msg.message_id not in target_ids:
                continue
            changed = False
            if pid not in msg.delivered_to:
                msg.delivered_to.append(pid)
                changed = True
            if status == "read" and pid not in msg.read_by:
                msg.read_by[pid] = now_str
                changed = True
            if changed:
                updated_ids.append(msg.message_id)

        if updated_ids:
            self.save_state()
        return {
            "event": "chat_receipt",
            "channel_id": ch.channel_id,
            "participant_id": pid,
            "status": status,
            "message_ids": updated_ids,
            "recipients": self.channel_recipients(ch),
            "updated_at": now_str,
        }

    def publish_proof_of_life_alert(self, alert: dict[str, Any]) -> dict[str, Any]:
        """Publica una tarjeta `system_alert` de Prueba de Vida dentro del chat de escuadrón."""
        squadron = (alert.get("recipients") or {}).get("squadron") or {}
        team_id = squadron.get("team_id")
        target_cid = (
            team_channel_id(team_id)
            if team_id and team_id in self.tracker.teams
            else config.CHAT_GLOBAL_CHANNEL_ID
        )
        ch = self._get_or_auto_channel(target_cid)
        seq = self._channel_seq.get(ch.channel_id, 0) + 1
        self._channel_seq[ch.channel_id] = seq
        now_str = _now_iso()
        msg = ChatMessage(
            message_id=f"sys_{uuid.uuid4().hex[:16]}",
            client_msg_id=f"pol_{alert.get('operator_id')}_{seq}",
            channel_id=ch.channel_id,
            server_seq=seq,
            sender_id=config.CHAT_CENTRAL_ID,
            sender_name="Sistema JULI — Prueba de Vida",
            sender_role="system",
            recipients=list(ch.member_ids),
            message_type="system_alert",
            encryption={
                "scheme": "system-alert",
                "is_encrypted": False,
                "system_payload": {
                    "event": alert.get("event", "proof_of_life_alert"),
                    "priority": alert.get("priority", "high"),
                    "operator_id": alert.get("operator_id"),
                    "name": alert.get("name"),
                    "callsign": alert.get("callsign"),
                    "reasons": alert.get("reasons", []),
                    "summary": alert.get("summary", ""),
                    "last_location": alert.get("last_location"),
                },
            },
            sent_at=now_str,
            delivered_to=[],
            read_by={},
        )
        msgs = self.messages.setdefault(ch.channel_id, [])
        msgs.append(msg)
        if len(msgs) > config.CHAT_MAX_MESSAGES_PER_CHANNEL:
            del msgs[: len(msgs) - config.CHAT_MAX_MESSAGES_PER_CHANNEL]
        ch.updated_at = now_str
        self.save_state()
        return msg.to_dict()


chat_ws_manager = ChatConnectionManager()
juli_chat = JuliChatManager()


async def broadcast_proof_of_life_alerts_to_chat(events: list[dict[str, Any]]) -> None:
    """Publica alertas de Prueba de Vida en el chat de escuadrón y notifica por `/ws/chat`."""
    for event in events:
        if event.get("event") != "proof_of_life_alert":
            continue
        sys_msg = juli_chat.publish_proof_of_life_alert(event)
        await chat_ws_manager.broadcast_to_participants(
            sys_msg["recipients"],
            {
                "event": "chat_message",
                "channel_id": sys_msg["channel_id"],
                "message": sys_msg,
            },
        )
