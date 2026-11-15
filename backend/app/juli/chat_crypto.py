"""Utilidades criptográficas E2EE (sin dependencias externas) para el chat táctico de JULI.

Diseño lógico para entorno WebCrypto en navegador (cero claves privadas o texto plano en servidor):
  1. Chat directo 1 a 1 (`e2ee-ecdh-p256-aes256gcm`):
     Identidades con par de claves ECDH P-256 en el cliente. El secreto compartido
     se deriva con ECDH + HKDF-SHA256 y cifra con AES-256-GCM (IV de 12 bytes + AAD).
  2. Chat de escuadrón / grupo (`e2ee-room-aes256gcm`):
     Clave de sala aleatoria AES-256-GCM rotada por `key_epoch`, envuelta (key wrapping)
     individualmente para cada miembro autorizado y para Central mediante su clave pública ECDH.
  3. Modo rápido con PIN/frase táctica (`e2ee-psk-pbkdf2-aes256gcm`):
     Opcional para despliegues sin PKI: PBKDF2-SHA256 (`150_000` iteraciones) + AES-256-GCM.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

from . import config

# Parámetros de curva NIST P-256 (secp256r1) para validar claves públicas JWK en servidor
_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_A = (_P256_P - 3) % _P256_P
_P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B

_FORBIDDEN_PLAINTEXT_KEYS = frozenset({"text", "body", "message", "plaintext", "content_plain"})


def _b64_decode_flexible(value: str, *, field_name: str) -> bytes:
    """Decodifica base64 estándar o base64url aceptando relleno opcional."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"El campo '{field_name}' debe ser una cadena base64 no vacía.")
    raw = value.strip()
    padded = raw + ("=" * (-len(raw) % 4))
    try:
        if "-" in raw or "_" in raw:
            return base64.urlsafe_b64decode(padded.encode("ascii"))
        return base64.b64decode(padded.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"El campo '{field_name}' no tiene un formato base64 válido.") from exc


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def validate_ec_p256_jwk(jwk: dict[str, Any], *, label: str = "ECDH") -> dict[str, str]:
    """Valida una clave pública EC NIST P-256 en formato JWK y descarta claves privadas."""
    if not isinstance(jwk, dict):
        raise ValueError(f"La clave pública {label} debe ser un objeto JWK.")
    if "d" in jwk:
        raise ValueError(
            f"Seguridad E2EE: la clave pública {label} nunca puede incluir el componente privado 'd'."
        )
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ValueError(f"La clave {label} debe usar kty='EC' y crv='P-256'.")

    x_bytes = _b64_decode_flexible(str(jwk.get("x", "")), field_name=f"{label}.x")
    y_bytes = _b64_decode_flexible(str(jwk.get("y", "")), field_name=f"{label}.y")
    if len(x_bytes) != 32 or len(y_bytes) != 32:
        raise ValueError(f"Las coordenadas (x, y) de {label} P-256 deben medir exactamente 32 bytes.")

    x_int = int.from_bytes(x_bytes, "big")
    y_int = int.from_bytes(y_bytes, "big")
    if not (0 <= x_int < _P256_P and 0 <= y_int < _P256_P) or (x_int == 0 and y_int == 0):
        raise ValueError(f"Coordenadas fuera de rango para curva P-256 en {label}.")

    lhs = pow(y_int, 2, _P256_P)
    rhs = (pow(x_int, 3, _P256_P) + _P256_A * x_int + _P256_B) % _P256_P
    if lhs != rhs:
        raise ValueError(f"El punto JWK de {label} no pertenece a la curva NIST P-256.")

    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url_encode(x_bytes),
        "y": _b64url_encode(y_bytes),
    }


def compute_jwk_thumbprint(jwk: dict[str, str]) -> dict[str, str]:
    """Calcula la huella RFC 7638 (SHA-256) y su identificador legible corto."""
    canonical = json.dumps(
        {
            "crv": jwk["crv"],
            "kty": jwk["kty"],
            "x": jwk["x"],
            "y": jwk["y"],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest_hex = hashlib.sha256(canonical).hexdigest()
    short_hex = digest_hex[:16].upper()
    short_formatted = "-".join(short_hex[i : i + 4] for i in range(0, 16, 4))
    return {
        "fingerprint": digest_hex,
        "short_fingerprint": short_formatted,
    }


def compute_pair_safety_code(fingerprint_a: str, fingerprint_b: str) -> str:
    """Genera un código numérico simétrico de verificación entre dos pares (estilo Signal)."""
    ordered = "|".join(sorted([fingerprint_a.strip().lower(), fingerprint_b.strip().lower()]))
    digest = hashlib.sha256(f"juli-safety-v1:{ordered}".encode()).digest()
    blocks = [
        f"{int.from_bytes(digest[i : i + 4], 'big') % 100000:05d}"
        for i in range(0, 24, 4)
    ]
    return " ".join(blocks)


def validate_encrypted_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Valida la estructura de un sobre cifrado E2EE sin intentar descifrarlo en el servidor."""
    if not isinstance(envelope, dict):
        raise ValueError("El objeto 'encryption' debe ser un diccionario.")

    leaked = _FORBIDDEN_PLAINTEXT_KEYS.intersection(envelope.keys())
    if leaked:
        raise ValueError(
            f"Seguridad E2EE: el sobre cifrado no puede contener texto plano ({sorted(leaked)})."
        )

    scheme = str(envelope.get("scheme", "")).strip()
    if scheme not in config.CHAT_E2EE_SCHEMES:
        raise ValueError(
            f"Esquema '{scheme}' no soportado. Válidos: {list(config.CHAT_E2EE_SCHEMES)}."
        )

    ct_b64 = str(envelope.get("ciphertext_b64", "")).strip()
    if len(ct_b64) > config.CHAT_MAX_CIPHERTEXT_B64_CHARS:
        raise ValueError(
            f"El mensaje cifrado supera el límite máximo ({config.CHAT_MAX_CIPHERTEXT_B64_CHARS} chars)."
        )
    ct_bytes = _b64_decode_flexible(ct_b64, field_name="encryption.ciphertext_b64")
    # AES-256-GCM siempre incluye tag de autenticación de 16 bytes + al menos 1 byte de mensaje
    if len(ct_bytes) < 17:
        raise ValueError(
            "El ciphertext AES-256-GCM debe incluir texto cifrado + tag de autenticación (mín. 17 bytes)."
        )

    iv_b64 = str(envelope.get("iv_b64", "")).strip()
    iv_bytes = _b64_decode_flexible(iv_b64, field_name="encryption.iv_b64")
    if len(iv_bytes) != 12:
        raise ValueError("El IV/nonce de AES-256-GCM debe medir exactamente 12 bytes (96 bits).")

    key_epoch = int(envelope.get("key_epoch", 1))
    if key_epoch < 1:
        raise ValueError("El campo 'key_epoch' debe ser >= 1.")

    sender_fp = str(envelope.get("sender_key_fingerprint", "")).strip()
    if scheme in ("e2ee-ecdh-p256-aes256gcm", "e2ee-room-aes256gcm") and not sender_fp:
        raise ValueError(
            f"El esquema '{scheme}' requiere 'sender_key_fingerprint' para identificar la clave emisora."
        )

    normalized: dict[str, Any] = {
        "scheme": scheme,
        "ciphertext_b64": ct_b64,
        "iv_b64": iv_b64,
        "key_epoch": key_epoch,
        "sender_key_fingerprint": sender_fp,
        "is_encrypted": True,
    }

    if scheme == "e2ee-psk-pbkdf2-aes256gcm":
        salt_b64 = str(envelope.get("salt_b64", "")).strip()
        salt_bytes = _b64_decode_flexible(salt_b64, field_name="encryption.salt_b64")
        if len(salt_bytes) < 8:
            raise ValueError("La sal PBKDF2 ('salt_b64') debe medir al menos 8 bytes.")
        normalized["salt_b64"] = salt_b64
        normalized["iterations"] = int(envelope.get("iterations", config.CHAT_PSK_ITERATIONS))

    if envelope.get("aad_b64"):
        aad_b64 = str(envelope["aad_b64"]).strip()
        _b64_decode_flexible(aad_b64, field_name="encryption.aad_b64")
        normalized["aad_b64"] = aad_b64

    if envelope.get("signature_b64"):
        sig_b64 = str(envelope["signature_b64"]).strip()
        sig_bytes = _b64_decode_flexible(sig_b64, field_name="encryption.signature_b64")
        if len(sig_bytes) < 32:
            raise ValueError("Firma ECDSA inválida ('signature_b64').")
        normalized["signature_b64"] = sig_b64

    if envelope.get("ephemeral_public_jwk") is not None:
        normalized["ephemeral_public_jwk"] = validate_ec_p256_jwk(
            envelope["ephemeral_public_jwk"], label="ephemeral"
        )

    return normalized


def validate_wrapped_key_entry(entry: dict[str, Any], recipient_id: str) -> dict[str, Any]:
    """Valida una clave de sala AES-256 envuelta individualmente para un miembro del canal."""
    if not isinstance(entry, dict):
        raise ValueError(f"La clave envuelta para '{recipient_id}' debe ser un objeto JSON.")

    wrapped_b64 = str(entry.get("wrapped_key_b64", "")).strip()
    wrapped_bytes = _b64_decode_flexible(
        wrapped_b64, field_name=f"wrapped_keys.{recipient_id}.wrapped_key_b64"
    )
    # 32 bytes de clave AES-256 + 16 bytes de tag AES-GCM = 48 bytes mínimo
    if len(wrapped_bytes) < 32:
        raise ValueError(
            f"La clave envuelta para '{recipient_id}' debe tener al menos 32 bytes cifrados."
        )

    iv_b64 = str(entry.get("iv_b64", "")).strip()
    iv_bytes = _b64_decode_flexible(iv_b64, field_name=f"wrapped_keys.{recipient_id}.iv_b64")
    if len(iv_bytes) != 12:
        raise ValueError(f"El IV de wrapping para '{recipient_id}' debe medir 12 bytes.")

    out: dict[str, Any] = {
        "wrapped_key_b64": wrapped_b64,
        "iv_b64": iv_b64,
        "alg": str(entry.get("alg", "ECDH-P256+HKDF-SHA256+AES-256-GCM")),
    }
    if entry.get("ephemeral_public_jwk") is not None:
        out["ephemeral_public_jwk"] = validate_ec_p256_jwk(
            entry["ephemeral_public_jwk"], label=f"wrapped_keys.{recipient_id}.ephemeral"
        )
    if entry.get("hkdf_salt_b64"):
        salt_b64 = str(entry["hkdf_salt_b64"]).strip()
        _b64_decode_flexible(salt_b64, field_name=f"wrapped_keys.{recipient_id}.hkdf_salt_b64")
        out["hkdf_salt_b64"] = salt_b64
    return out


def build_crypto_spec() -> dict[str, Any]:
    """Especificación pública para que el frontend configure WebCrypto sin ambigüedades."""
    return {
        "protocol": "JULI-E2EE-v1",
        "zero_knowledge_server": True,
        "ecdh": {
            "name": "ECDH",
            "namedCurve": "P-256",
            "public_key_format": "jwk",
        },
        "signing": {
            "name": "ECDSA",
            "namedCurve": "P-256",
            "hash": "SHA-256",
            "optional": True,
        },
        "kdf": {
            "direct_and_wrap": {
                "name": "HKDF",
                "hash": "SHA-256",
                "info": "juli-e2ee-v1",
                "derived_key_length_bits": 256,
            },
            "passphrase_fallback": {
                "name": "PBKDF2",
                "hash": "SHA-256",
                "iterations": config.CHAT_PSK_ITERATIONS,
            },
        },
        "aead": {
            "name": "AES-GCM",
            "key_bits": 256,
            "iv_bytes": 12,
            "tag_bits": 128,
            "aad_recommended_format": "{channel_id}|{sender_id}|{key_epoch}|{client_msg_id}",
        },
        "thumbprint": "RFC7638-SHA256",
        "safety_code": "6x5-digits-sha256",
        "supported_schemes": list(config.CHAT_E2EE_SCHEMES),
    }
