"""Capa de protocolo Walkie-Talkie moderno <-> Terminal móvil para JULI.

Modela el enlace **BLE GATT + TETRA PEI (ETSI TS 100 392-5 AT Commands)** utilizado
por radios tácticos modernos (SIRDEE/TETRA, DMR Tier III y VHF) al conectarse a un
terminal móvil o tablet MDT para cambiar de frecuencia / grupo de conversación (`GSSI`).

Garantiza coherencia única en los datos de JULI:
  Cuando un operario cambia de frecuencia hacia otro escuadrón (de forma real o simulada),
  `juli_tracker` actualiza automáticamente su `team_id`, metadatos de radio, `juli_state.json`,
  `juli_operators.geojson`, la membresía del chat de escuadrón y las alertas de Prueba de Vida,
  sin requerir una segunda edición manual por parte de Central.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
from typing import Any
import uuid

from . import config
from .tracker import JuliTracker, juli_tracker

_AT_CMD_REGEX = re.compile(r"^\s*(AT\+[A-Z0-9]+)\s*(?:=\s*(.+?)|\?)?\s*$", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_ble_or_text_command(raw_command: str | None, ble_payload_hex: str | None) -> str:
    """Decodifica un comando AT PEI recibido en texto UTF-8 o trama hexadecimal BLE GATT."""
    if raw_command and raw_command.strip():
        return raw_command.strip()
    if ble_payload_hex and ble_payload_hex.strip():
        cleaned = ble_payload_hex.strip().lower().removeprefix("0x").replace(" ", "")
        try:
            return bytes.fromhex(cleaned).decode("utf-8").strip()
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("La carga hexadecimal BLE GATT no contiene un comando AT UTF-8 válido.") from exc
    return ""


def build_protocol_spec() -> dict[str, Any]:
    """Especificación pública BLE GATT + TETRA PEI para terminales móviles y simuladores."""
    return {
        "protocol": config.RADIO_DEFAULT_PROTOCOL,
        "standards": [
            "ETSI TS 100 392-5 (TETRA Peripheral Equipment Interface - PEI AT)",
            "Bluetooth Low Energy (BLE GATT) Radio Companion Profile",
            "VHF-High / SIRDEE-TETRA Dual-Band Mapping",
        ],
        "ble_gatt": {
            "service_uuid": config.RADIO_BLE_SERVICE_UUID,
            "rx_command_char_uuid": config.RADIO_BLE_RX_CHAR_UUID,
            "tx_status_char_uuid": config.RADIO_BLE_TX_CHAR_UUID,
            "telemetry_char_uuid": config.RADIO_BLE_TELEMETRY_CHAR_UUID,
            "encoding": "utf-8",
            "line_terminator": "\\r\\n",
        },
        "pei_at_commands": {
            "switch_talkgroup": "AT+CTGS=<gssi_or_radio_channel>",
            "tune_frequency_mhz": "AT+CFREQ=<frequency_mhz>",
            "switch_squadron": "AT+CTSG=<team_id>",
            "query_current_frequency": "AT+CNUMF?",
            "list_squadron_channels": "AT+CTGLIST?",
        },
    }


class WalkieRadioManager:
    """Controlador BLE GATT / TETRA PEI conectado directamente a `JuliTracker`."""

    def __init__(
        self,
        tracker: JuliTracker | None = None,
        log_path: str = config.DEFAULT_RADIO_LOG_PATH,
    ) -> None:
        self.tracker = tracker or juli_tracker
        self.log_path = log_path
        self.history: list[dict[str, Any]] = []
        self._load_history()

    def _load_history(self) -> None:
        if not self.log_path or not os.path.exists(self.log_path):
            return
        try:
            with open(self.log_path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("history"), list):
                self.history = raw["history"][-200:]
        except Exception:
            pass

    def _save_history(self) -> None:
        if not self.log_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.log_path)), exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "protocol": config.RADIO_DEFAULT_PROTOCOL,
                    "updated_at": _now_iso(),
                    "history": self.history[-200:],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    def get_frequency_bank(self) -> list[dict[str, Any]]:
        """Construye el banco de frecuencias/talkgroups sintonizables a partir de los equipos."""
        bank: list[dict[str, Any]] = []
        used_vhf: set[float] = {
            round(float(p["frequency_mhz"]), 4)
            for p in config.DEFAULT_TEAM_FREQUENCY_PLANS.values()
        }
        used_tetra: set[float] = {
            round(float(p["tetra_frequency_mhz"]), 4)
            for p in config.DEFAULT_TEAM_FREQUENCY_PLANS.values()
        }
        used_gssi: set[str] = {
            str(p["talkgroup_id"]) for p in config.DEFAULT_TEAM_FREQUENCY_PLANS.values()
        }

        dyn_idx = 0
        for tid, team in self.tracker.teams.items():
            preset = config.DEFAULT_TEAM_FREQUENCY_PLANS.get(tid)
            if preset is not None:
                freq_mhz = float(preset["frequency_mhz"])
                tetra_mhz = float(preset["tetra_frequency_mhz"])
                gssi = str(preset["talkgroup_id"])
                ctcss_hz = float(preset["ctcss_hz"])
                channel_name = team.radio_channel or str(preset["radio_channel"])
                band = str(preset["band"])
            else:
                while True:
                    dyn_idx += 1
                    freq_mhz = round(155.0 + dyn_idx * config.RADIO_CHANNEL_STEP_MHZ, 4)
                    tetra_mhz = round(391.5 + dyn_idx * config.RADIO_CHANNEL_STEP_MHZ, 4)
                    gssi = str(3000 + dyn_idx)
                    if freq_mhz not in used_vhf and tetra_mhz not in used_tetra and gssi not in used_gssi:
                        used_vhf.add(freq_mhz)
                        used_tetra.add(tetra_mhz)
                        used_gssi.add(gssi)
                        break
                ctcss_hz = round(88.5 + (dyn_idx % 8) * 6.0, 1)
                channel_name = team.radio_channel or f"VHF-{dyn_idx + 10:02d}"
                band = "VHF-High / SIRDEE-TETRA"

            members = [
                {
                    "operator_id": op.operator_id,
                    "name": op.name,
                    "callsign": op.callsign,
                    "role": op.role,
                    "status": op.status,
                }
                for op in self.tracker.operators.values()
                if op.team_id == tid
            ]
            bank.append(
                {
                    "team_id": tid,
                    "team_name": team.name,
                    "unit_code": team.unit_code,
                    "radio_channel": channel_name,
                    "frequency_mhz": freq_mhz,
                    "tetra_frequency_mhz": tetra_mhz,
                    "talkgroup_id": gssi,
                    "ctcss_hz": ctcss_hz,
                    "band": band,
                    "zone_assigned": team.zone_assigned,
                    "members_count": len(members),
                    "member_ids": [m["operator_id"] for m in members],
                    "members": members,
                }
            )
        return bank

    def _find_entry_by_frequency(
        self, bank: list[dict[str, Any]], freq_mhz: float
    ) -> dict[str, Any] | None:
        target = round(float(freq_mhz), 4)
        for entry in bank:
            if (
                abs(entry["frequency_mhz"] - target) <= 0.0025
                or abs(entry["tetra_frequency_mhz"] - target) <= 0.0025
            ):
                return entry
        return None

    def resolve_target_channel(
        self,
        *,
        target_team_id: str | None = None,
        target_frequency_mhz: float | None = None,
        target_radio_channel: str | None = None,
        target_talkgroup_id: str | None = None,
        at_command: str | None = None,
        ble_payload_hex: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Resuelve la frecuencia/escuadrón destino y normaliza el comando AT TETRA PEI."""
        bank = self.get_frequency_bank()
        decoded_cmd = _decode_ble_or_text_command(at_command, ble_payload_hex)

        if decoded_cmd:
            match = _AT_CMD_REGEX.match(decoded_cmd)
            if not match:
                raise ValueError(
                    f"+CME ERROR: 3 — Comando TETRA PEI inválido: '{decoded_cmd}'."
                )
            cmd_name = match.group(1).upper()
            arg = (match.group(2) or "").strip().strip('"').strip("'")
            if not arg:
                raise ValueError(f"+CME ERROR: 50 — El comando '{cmd_name}' requiere argumento.")
            if cmd_name == "AT+CFREQ":
                try:
                    target_frequency_mhz = float(arg)
                except ValueError as exc:
                    raise ValueError(f"+CME ERROR: 3 — Frecuencia MHz inválida: '{arg}'.") from exc
            elif cmd_name == "AT+CTGS":
                if any(e["talkgroup_id"] == arg for e in bank):
                    target_talkgroup_id = arg
                else:
                    target_radio_channel = arg
            elif cmd_name == "AT+CTSG":
                target_team_id = arg
            else:
                raise ValueError(
                    f"+CME ERROR: 4 — Comando '{cmd_name}' no soporta cambio directo de frecuencia."
                )

        resolved: dict[str, Any] | None = None
        if target_team_id:
            tid = target_team_id.strip()
            resolved = next((e for e in bank if e["team_id"] == tid), None)
        elif target_talkgroup_id:
            gssi = str(target_talkgroup_id).strip()
            resolved = next((e for e in bank if e["talkgroup_id"] == gssi), None)
        elif target_radio_channel:
            ch = target_radio_channel.strip().lower()
            resolved = next(
                (e for e in bank if e["radio_channel"].strip().lower() == ch), None
            )
        elif target_frequency_mhz is not None:
            resolved = self._find_entry_by_frequency(bank, float(target_frequency_mhz))

        if resolved is None:
            raise KeyError(
                "+CME ERROR: 22 — Ningún escuadrón asignado a la frecuencia o talkgroup solicitado."
            )

        effective_at = decoded_cmd or f"AT+CTGS={resolved['talkgroup_id']}"
        return resolved, effective_at

    def get_operator_radio_state(self, operator_id: str) -> dict[str, Any]:
        """Devuelve el estado de radio actual del operario según su escuadrón activo en JULI."""
        op = self.tracker.operators.get(operator_id)
        if op is None:
            raise KeyError(f"No existe el operario '{operator_id}' en JULI.")
        bank = self.get_frequency_bank()
        entry = next((e for e in bank if e["team_id"] == op.team_id), None)
        return {
            "operator_id": op.operator_id,
            "name": op.name,
            "callsign": op.callsign,
            "team_id": op.team_id,
            "team_name": entry["team_name"] if entry else op.team_id,
            "radio_channel": op.radio_channel or (entry["radio_channel"] if entry else ""),
            "radio_frequency_mhz": op.radio_frequency_mhz
            or (entry["frequency_mhz"] if entry else None),
            "tetra_frequency_mhz": entry["tetra_frequency_mhz"] if entry else None,
            "talkgroup_id": op.talkgroup_id or (entry["talkgroup_id"] if entry else ""),
            "ctcss_hz": entry["ctcss_hz"] if entry else None,
            "radio_protocol": op.radio_protocol,
            "radio_device_id": op.radio_device_id,
            "radio_last_switch_at": op.radio_last_switch_at,
        }

    def switch_frequency(
        self,
        operator_id: str,
        *,
        target_team_id: str | None = None,
        target_frequency_mhz: float | None = None,
        target_radio_channel: str | None = None,
        target_talkgroup_id: str | None = None,
        at_command: str | None = None,
        ble_payload_hex: str | None = None,
        ble_device_id: str = "",
        simulated: bool = False,
        note: str = "",
    ) -> dict[str, Any]:
        """Ejecuta el cambio de frecuencia BLE/PEI y mueve atómicamente al operario de escuadrón."""
        oid = operator_id.strip()
        if oid not in self.tracker.operators:
            raise KeyError(f"No existe el operario '{operator_id}' en JULI.")

        prev_state = self.get_operator_radio_state(oid)
        target, effective_at = self.resolve_target_channel(
            target_team_id=target_team_id,
            target_frequency_mhz=target_frequency_mhz,
            target_radio_channel=target_radio_channel,
            target_talkgroup_id=target_talkgroup_id,
            at_command=at_command,
            ble_payload_hex=ble_payload_hex,
        )

        now_str = _now_iso()
        device_label = ble_device_id.strip() or (
            f"SIM-WALKIE-{oid.upper()}" if simulated else f"BLE-PEI-{oid.upper()}"
        )
        updated_op = self.tracker.reassign_operator_team(
            operator_id=oid,
            new_team_id=target["team_id"],
            radio_channel=target["radio_channel"],
            radio_frequency_mhz=target["frequency_mhz"],
            talkgroup_id=target["talkgroup_id"],
            radio_protocol=config.RADIO_DEFAULT_PROTOCOL,
            radio_device_id=device_label,
            switched_at=now_str,
        )

        # Mantener referencia coherente en el plano BLE / TETRA PEI
        tx_wire = f"{effective_at}\r\n"
        pei_responses = [
            f'+CTGS: {target["talkgroup_id"]},{target["frequency_mhz"]:.4f},"{target["radio_channel"]}","{target["team_id"]}"',
            f'+CFREQ: {target["frequency_mhz"]:.4f},{target["tetra_frequency_mhz"]:.4f},{target["ctcss_hz"]}',
            f'+CREG: 1,"{target["unit_code"]}"',
            "OK",
        ]
        rx_wire = "\r\n".join(pei_responses) + "\r\n"

        updated_bank = self.get_frequency_bank()
        new_team_entry = next(e for e in updated_bank if e["team_id"] == target["team_id"])
        switch_id = f"rad_{uuid.uuid4().hex[:14]}"
        team_changed = prev_state["team_id"] != target["team_id"]

        record = {
            "switch_id": switch_id,
            "event": "juli_radio_frequency_switched",
            "switched_at": now_str,
            "simulated": bool(simulated),
            "team_changed": team_changed,
            "operator_id": updated_op.operator_id,
            "operator_name": updated_op.name,
            "callsign": updated_op.callsign,
            "note": note,
            "previous": {
                "team_id": prev_state["team_id"],
                "team_name": prev_state["team_name"],
                "radio_channel": prev_state["radio_channel"],
                "frequency_mhz": prev_state["radio_frequency_mhz"],
                "talkgroup_id": prev_state["talkgroup_id"],
            },
            "current": {
                "team_id": target["team_id"],
                "team_name": target["team_name"],
                "unit_code": target["unit_code"],
                "radio_channel": target["radio_channel"],
                "frequency_mhz": target["frequency_mhz"],
                "tetra_frequency_mhz": target["tetra_frequency_mhz"],
                "talkgroup_id": target["talkgroup_id"],
                "ctcss_hz": target["ctcss_hz"],
            },
            "protocol_trace": {
                "protocol": config.RADIO_DEFAULT_PROTOCOL,
                "transport": "BLE-GATT (simulado)" if simulated else "BLE-GATT / PEI",
                "ble_device_id": device_label,
                "ble_gatt_rx": {
                    "service_uuid": config.RADIO_BLE_SERVICE_UUID,
                    "characteristic_uuid": config.RADIO_BLE_RX_CHAR_UUID,
                    "payload_utf8": tx_wire,
                    "payload_hex": tx_wire.encode("utf-8").hex(),
                },
                "ble_gatt_tx": {
                    "service_uuid": config.RADIO_BLE_SERVICE_UUID,
                    "characteristic_uuid": config.RADIO_BLE_TX_CHAR_UUID,
                    "payload_utf8": rx_wire,
                    "payload_hex": rx_wire.encode("utf-8").hex(),
                },
                "at_command": effective_at,
                "pei_responses": pei_responses,
                "rf_metrics": {
                    "rssi_dbm": -64 if simulated else None,
                    "snr_db": 22.5 if simulated else None,
                    "handover_latency_ms": 85 if simulated else None,
                },
            },
            "new_squadron_members": new_team_entry["members"],
            "operator": updated_op.to_dict(),
        }
        self.history.append(record)
        self.history = self.history[-200:]
        self._save_history()
        return record

    def execute_pei_command(
        self,
        operator_id: str,
        command: str | None = None,
        *,
        ble_payload_hex: str | None = None,
        ble_device_id: str = "",
        simulated: bool = False,
    ) -> dict[str, Any]:
        """Procesa un comando AT TETRA PEI completo (consultas `?` o sintonización)."""
        cmd_str = _decode_ble_or_text_command(command, ble_payload_hex)
        if not cmd_str:
            raise ValueError("+CME ERROR: 3 — Comando AT vacío.")

        upper = cmd_str.strip().upper()
        if upper == "AT+CNUMF?":
            state = self.get_operator_radio_state(operator_id)
            responses = [
                f'+CNUMF: {state["talkgroup_id"]},{state["radio_frequency_mhz"]},"{state["radio_channel"]}","{state["team_id"]}"',
                "OK",
            ]
            return {
                "status": "ok",
                "command": cmd_str,
                "simulated": bool(simulated),
                "pei_responses": responses,
                "radio_state": state,
            }

        if upper in ("AT+CTGLIST?", "AT+CSCAN"):
            bank = self.get_frequency_bank()
            responses = [
                f'+CTGLIST: {e["talkgroup_id"]},{e["frequency_mhz"]:.4f},"{e["radio_channel"]}","{e["team_id"]}"'
                for e in bank
            ]
            responses.append("OK")
            return {
                "status": "ok",
                "command": cmd_str,
                "simulated": bool(simulated),
                "pei_responses": responses,
                "frequencies": bank,
            }

        return self.switch_frequency(
            operator_id=operator_id,
            at_command=cmd_str,
            ble_device_id=ble_device_id,
            simulated=simulated,
        )

    def get_history(self, limit: int = 50, operator_id: str | None = None) -> list[dict[str, Any]]:
        items = self.history
        if operator_id:
            items = [h for h in items if h.get("operator_id") == operator_id.strip()]
        return list(reversed(items[-max(1, min(limit, 200)) :]))


walkie_radio = WalkieRadioManager()
