"""Suite QA — Seguridad de Adjuntos (CDR/Antimalware) y Criptografía E2EE (JULI).

Cubre exhaustivamente:
  1. `app.juli.chat_crypto`:
     - Fuzzing y validación algebraica sobre curva elíptica NIST P-256 (secp256r1):
       puntos válidos (G, -G, múltiplos escalares k*G), puntos fuera de curva, punto nulo (0,0),
       coordenadas fuera de cuerpo primo (>= p), longitudes inválidas, clave privada 'd',
       kty/crv inválidos, y decodificación flexible de base64/base64url con y sin padding.
     - Huellas criptográficas RFC 7638 (SHA-256 canónico) e invariancia ante orden/campos extra.
     - Código numérico de pares (`compute_pair_safety_code`): simetría, normalización y formato.
     - Validación de sobres AES-256-GCM (`validate_encrypted_envelope`): rechazo de texto plano,
       ciphertext < 17 bytes, límite máximo de tamaño, IV != 12 bytes, key_epoch < 1,
       ausencia de `sender_key_fingerprint`, sal PBKDF2 < 8 bytes, firmas ECDSA y claves efímeras.
     - Validación de `validate_wrapped_key_entry`: wrapped_key < 32 bytes, IV != 12 bytes,
       y clave pública efímera inválida.
  2. `app.juli.attachment_security`:
     - Higiene de nombres: path traversal, null bytes, control ASCII y dobles extensiones.
     - Bloqueo de firmas camufladas en offset 0: PE/MZ, ELF, Mach-O, ZIP/RAR/7z/GZIP,
       SVG, XML, HTML, PHP y shebang.
     - Inspección profunda de imágenes:
       * PNG: corrupción de CRC32, payload oculto tras `IEND`, scripts en `tEXt`/`iTXt`/`zTXt`,
         primer chunk distinto de `IHDR`, falta de `IEND` y truncado.
       * JPEG: payload oculto tras EOI (`0xFFD9`) y scripts en cabecera/comentarios.
       * WEBP: discrepancia de tamaño en cabecera `RIFF` y datos anexados.
       * GIF: ausencia de terminador `;` (`0x3B`), basura tras terminador y scripts embebidos.
       * Sanitización CDR con Pillow (JPEG, PNG, WEBP, GIF estático y animado): magic bytes,
         eliminación de EXIF/metadatos y límites contra pixel-flood / bombas de descompresión.
     - Inspección profunda de PDF:
       * Cabecera fuera de offset 0, basura tras `%%EOF`, falta de `obj`/`endobj`/`trailer`.
       * Nombres peligrosos ofuscados en hex `#XX` (`/J#53`, `/Open#41ction`,
         `/Embe#64dedFile`, `/#45ncrypt`, etc.).
       * Amenazas ocultas dentro de streams comprimidos `FlateDecode`.
       * Detección de bombas de descompresión (zip-bomb) > `CHAT_PDF_MAX_DECOMPRESSED_BYTES`.
       * Límite máximo de archivo `CHAT_ATTACHMENT_MAX_BYTES` y aceptación de PDF limpio válido.
"""

from __future__ import annotations

import base64
import hashlib
import io
import struct
import unittest
import zlib
from unittest import mock

from PIL import Image, PngImagePlugin

from app.juli import attachment_security, chat_crypto, config
from app.juli.attachment_security import MaliciousAttachmentError

# ---------------------------------------------------------------------------
# Utilidades matemáticas NIST P-256 para generación y fuzzing de puntos reales
# ---------------------------------------------------------------------------
_P256_P = chat_crypto._P256_P
_P256_A = chat_crypto._P256_A
_P256_B = chat_crypto._P256_B
_P256_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_P256_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5


def _ec_point_add(p1: tuple[int, int] | None, p2: tuple[int, int] | None) -> tuple[int, int] | None:
    """Suma afín en la curva NIST P-256 sobre F_p para generar vectores de prueba."""
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P256_P == 0:
        return None
    if x1 == x2 and y1 == y2:
        num = (3 * x1 * x1 + _P256_A) % _P256_P
        den = pow(2 * y1, -1, _P256_P)
    else:
        num = (y2 - y1) % _P256_P
        den = pow((x2 - x1) % _P256_P, -1, _P256_P)
    lam = (num * den) % _P256_P
    x3 = (lam * lam - x1 - x2) % _P256_P
    y3 = (lam * (x1 - x3) - y1) % _P256_P
    return x3, y3


def _ec_scalar_mul(k: int, point: tuple[int, int] = (_P256_GX, _P256_GY)) -> tuple[int, int]:
    """Multiplicación escalar k * P en NIST P-256."""
    result: tuple[int, int] | None = None
    addend: tuple[int, int] | None = point
    scalar = k
    while scalar > 0:
        if scalar & 1:
            result = _ec_point_add(result, addend)
        addend = _ec_point_add(addend, addend)
        scalar >>= 1
    assert result is not None
    return result


def _int_to_b64url_32(val: int) -> str:
    return base64.urlsafe_b64encode(val.to_bytes(32, "big")).rstrip(b"=").decode("ascii")


def _make_valid_jwk(scalar: int = 1) -> dict[str, str]:
    x, y = _ec_scalar_mul(scalar)
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _int_to_b64url_32(x),
        "y": _int_to_b64url_32(y),
    }


def _build_png_chunk(chunk_type: bytes, payload: bytes, *, bad_crc: bool = False) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    if bad_crc:
        crc ^= 0xDEADBEEF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def _make_valid_image_bytes(fmt: str, size: tuple[int, int] = (24, 24)) -> bytes:
    img = Image.new("RGB", size, color=(32, 128, 220))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_minimal_pdf(
    *,
    header: bytes = b"%PDF-1.7\n",
    extra_body: bytes = b"",
    stream_payload: bytes | None = None,
    compress_stream: bool = True,
    trailing_after_eof: bytes = b"",
) -> bytes:
    stream_block = b""
    if stream_payload is not None:
        encoded_stream = zlib.compress(stream_payload) if compress_stream else stream_payload
        stream_block = (
            b"2 0 obj\n<< /Length "
            + str(len(encoded_stream)).encode("ascii")
            + (b" /Filter /FlateDecode" if compress_stream else b"")
            + b" >>\nstream\r\n"
            + encoded_stream
            + b"\r\nendstream\nendobj\n"
        )
    body = (
        header
        + b"1 0 obj\n<< /Type /Catalog /Pages 3 0 R >>\nendobj\n"
        + stream_block
        + extra_body
        + b"trailer\n<< /Root 1 0 R >>\n%%EOF"
        + trailing_after_eof
    )
    return body


class TestArgonChatCrypto(unittest.TestCase):
    """Pruebas exhaustivas de criptografía E2EE y validación algebraica en `chat_crypto.py`."""

    def test_valid_p256_points_and_b64_padding_variants(self) -> None:
        for k in (1, 2, 3, 7, 19, 257, 99991):
            jwk = _make_valid_jwk(k)
            validated = chat_crypto.validate_ec_p256_jwk(jwk)
            self.assertEqual(validated["kty"], "EC")
            self.assertEqual(validated["crv"], "P-256")
            self.assertNotIn("=", validated["x"])
            self.assertNotIn("=", validated["y"])

        # Punto inverso -G = (Gx, P - Gy) pertenece a la curva
        neg_gy = (_P256_P - _P256_GY) % _P256_P
        inv_jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": _int_to_b64url_32(_P256_GX),
            "y": _int_to_b64url_32(neg_gy),
        }
        self.assertEqual(chat_crypto.validate_ec_p256_jwk(inv_jwk)["y"], _int_to_b64url_32(neg_gy))

        # Base64 estándar con '+', '/' y padding '=' debe normalizarse a base64url sin '='
        std_jwk = None
        for k in range(1, 40):
            px, py = _ec_scalar_mul(k)
            xb = px.to_bytes(32, "big")
            yb = py.to_bytes(32, "big")
            x_std = base64.b64encode(xb).decode("ascii")
            y_std = base64.b64encode(yb).decode("ascii")
            if ("+" in x_std or "/" in x_std) or ("+" in y_std or "/" in y_std):
                std_jwk = {
                    "kty": "EC",
                    "crv": "P-256",
                    "x": f"  {x_std}  ",
                    "y": y_std.rstrip("="),
                }
                break
        self.assertIsNotNone(std_jwk)
        norm = chat_crypto.validate_ec_p256_jwk(std_jwk)  # type: ignore[arg-type]
        self.assertNotIn("+", norm["x"])
        self.assertNotIn("/", norm["x"])
        self.assertNotIn("=", norm["x"])

    def test_p256_rejects_zero_point_and_out_of_range_coordinates(self) -> None:
        zero_b64 = _int_to_b64url_32(0)
        with self.assertRaisesRegex(ValueError, "fuera de rango"):
            chat_crypto.validate_ec_p256_jwk(
                {"kty": "EC", "crv": "P-256", "x": zero_b64, "y": zero_b64}
            )

        # Coordenada x == P (cabe en 32 bytes porque P < 2^256, pero está fuera de F_p)
        p_b64 = _int_to_b64url_32(_P256_P)
        gy_b64 = _int_to_b64url_32(_P256_GY)
        gx_b64 = _int_to_b64url_32(_P256_GX)
        with self.assertRaisesRegex(ValueError, "fuera de rango"):
            chat_crypto.validate_ec_p256_jwk({"kty": "EC", "crv": "P-256", "x": p_b64, "y": gy_b64})

        # Coordenada y == 2^256 - 1
        max_u256_b64 = _int_to_b64url_32((1 << 256) - 1)
        with self.assertRaisesRegex(ValueError, "fuera de rango"):
            chat_crypto.validate_ec_p256_jwk(
                {"kty": "EC", "crv": "P-256", "x": gx_b64, "y": max_u256_b64}
            )

    def test_p256_fuzzing_off_curve_and_invalid_curve_attack_points(self) -> None:
        # Perturbaciones de 1 bit / ±1 sobre G
        for bad_y in ((_P256_GY + 1) % _P256_P, (_P256_GY - 1) % _P256_P, _P256_GY ^ 1):
            with self.assertRaisesRegex(ValueError, "no pertenece a la curva NIST P-256"):
                chat_crypto.validate_ec_p256_jwk(
                    {
                        "kty": "EC",
                        "crv": "P-256",
                        "x": _int_to_b64url_32(_P256_GX),
                        "y": _int_to_b64url_32(bad_y),
                    }
                )

        # Ataque de curva inválida: el punto (1, 2) cumple y^2 = x^3 - 3x + 6 (b'=6 != B de P-256)
        with self.assertRaisesRegex(ValueError, "no pertenece a la curva NIST P-256"):
            chat_crypto.validate_ec_p256_jwk(
                {
                    "kty": "EC",
                    "crv": "P-256",
                    "x": _int_to_b64url_32(1),
                    "y": _int_to_b64url_32(2),
                }
            )

        # Fuzzing determinista con 60 pares de coordenadas pseudoaleatorias en [1, P-1]
        for idx in range(60):
            dx = hashlib.sha256(f"p256-fuzz-x-{idx}".encode()).digest()
            dy = hashlib.sha256(f"p256-fuzz-y-{idx}".encode()).digest()
            rx = (int.from_bytes(dx, "big") % (_P256_P - 1)) + 1
            ry = (int.from_bytes(dy, "big") % (_P256_P - 1)) + 1
            if pow(ry, 2, _P256_P) == (pow(rx, 3, _P256_P) + _P256_A * rx + _P256_B) % _P256_P:
                continue
            with self.assertRaisesRegex(ValueError, "no pertenece a la curva NIST P-256"):
                chat_crypto.validate_ec_p256_jwk(
                    {
                        "kty": "EC",
                        "crv": "P-256",
                        "x": _int_to_b64url_32(rx),
                        "y": _int_to_b64url_32(ry),
                    }
                )

    def test_p256_rejects_private_key_d_and_invalid_kty_crv_or_lengths(self) -> None:
        valid = _make_valid_jwk(1)

        # Inyección de clave privada 'd'
        for d_val in (_int_to_b64url_32(1), "", None, "secret"):
            leaked_jwk = {**valid, "d": d_val}
            with self.assertRaisesRegex(ValueError, "componente privado 'd'"):
                chat_crypto.validate_ec_p256_jwk(leaked_jwk)

        # kty / crv inválidos o ausentes
        for bad_meta in (
            {"kty": "RSA", "crv": "P-256"},
            {"kty": "OKP", "crv": "Ed25519"},
            {"kty": "EC", "crv": "secp256k1"},
            {"kty": "EC", "crv": "P-384"},
            {"kty": "EC", "crv": ""},
            {"kty": "", "crv": "P-256"},
        ):
            with self.assertRaisesRegex(ValueError, "kty='EC' y crv='P-256'"):
                chat_crypto.validate_ec_p256_jwk({**valid, **bad_meta})

        with self.assertRaisesRegex(ValueError, "kty='EC' y crv='P-256'"):
            chat_crypto.validate_ec_p256_jwk({"x": valid["x"], "y": valid["y"]})

        # No-diccionario
        for non_dict in (None, "jwk", 123, ["kty"]):
            with self.assertRaisesRegex(ValueError, "objeto JWK"):
                chat_crypto.validate_ec_p256_jwk(non_dict)  # type: ignore[arg-type]

        # Longitud de coordenadas != 32 bytes (31 y 33 bytes)
        short_x = base64.urlsafe_b64encode(b"\x01" * 31).rstrip(b"=").decode("ascii")
        long_y = base64.urlsafe_b64encode(b"\x02" * 33).rstrip(b"=").decode("ascii")
        with self.assertRaisesRegex(ValueError, "exactamente 32 bytes"):
            chat_crypto.validate_ec_p256_jwk({**valid, "x": short_x})
        with self.assertRaisesRegex(ValueError, "exactamente 32 bytes"):
            chat_crypto.validate_ec_p256_jwk({**valid, "y": long_y})

        # Base64 corrupto o vacío
        for bad_b64 in ("", "   ", "a", "!!!not_base64!!!", "áéíóú"):
            with self.assertRaises(ValueError):
                chat_crypto.validate_ec_p256_jwk({**valid, "x": bad_b64})

    def test_rfc7638_jwk_thumbprint_and_symmetric_safety_code(self) -> None:
        jwk_a = _make_valid_jwk(1)
        jwk_b = _make_valid_jwk(2)

        expected_json = (
            f'{{"crv":"P-256","kty":"EC","x":"{jwk_a["x"]}","y":"{jwk_a["y"]}"}}'.encode()
        )
        expected_hex = hashlib.sha256(expected_json).hexdigest()

        noisy_jwk = {
            "y": jwk_a["y"],
            "use": "enc",
            "kid": "operario-1",
            "x": jwk_a["x"],
            "crv": "P-256",
            "kty": "EC",
        }
        thumb_a = chat_crypto.compute_jwk_thumbprint(noisy_jwk)
        self.assertEqual(thumb_a["fingerprint"], expected_hex)
        self.assertRegex(thumb_a["short_fingerprint"], r"^[0-9A-F]{4}(?:-[0-9A-F]{4}){3}$")
        self.assertEqual(thumb_a["short_fingerprint"].replace("-", ""), expected_hex[:16].upper())

        thumb_b = chat_crypto.compute_jwk_thumbprint(jwk_b)
        self.assertNotEqual(thumb_a["fingerprint"], thumb_b["fingerprint"])

        code_ab = chat_crypto.compute_pair_safety_code(
            thumb_a["fingerprint"], thumb_b["fingerprint"]
        )
        code_ba = chat_crypto.compute_pair_safety_code(
            f"  {thumb_b['fingerprint'].upper()} \n",
            f"\t{thumb_a['fingerprint'].lower()}  ",
        )
        self.assertEqual(code_ab, code_ba)
        self.assertRegex(code_ab, r"^\d{5}(?: \d{5}){5}$")
        self.assertNotEqual(
            code_ab,
            chat_crypto.compute_pair_safety_code(thumb_a["fingerprint"], thumb_a["fingerprint"]),
        )

    def test_validate_encrypted_envelope_constraints_and_attacks(self) -> None:
        valid_ct = base64.b64encode(b"C" * 17).decode("ascii")  # 1 byte + 16 bytes GCM tag
        valid_iv = base64.b64encode(b"I" * 12).decode("ascii")  # 96-bit nonce
        base_env = {
            "scheme": "e2ee-ecdh-p256-aes256gcm",
            "ciphertext_b64": valid_ct,
            "iv_b64": valid_iv,
            "key_epoch": 1,
            "sender_key_fingerprint": "abcdef0123456789" * 4,
        }

        full_env = {
            **base_env,
            "aad_b64": base64.b64encode(b"chan|op1|1|msg1").decode("ascii"),
            "signature_b64": base64.b64encode(b"S" * 64).decode("ascii"),
            "ephemeral_public_jwk": _make_valid_jwk(5),
        }
        norm = chat_crypto.validate_encrypted_envelope(full_env)
        self.assertTrue(norm["is_encrypted"])
        self.assertEqual(norm["scheme"], "e2ee-ecdh-p256-aes256gcm")
        self.assertIn("ephemeral_public_jwk", norm)

        # No-diccionario
        with self.assertRaisesRegex(ValueError, "diccionario"):
            chat_crypto.validate_encrypted_envelope("not-a-dict")  # type: ignore[arg-type]

        # 1. Prohibición estricta de campos de texto plano en el sobre
        for forbidden_key in ("text", "body", "message", "plaintext", "content_plain"):
            with self.assertRaisesRegex(ValueError, "no puede contener texto plano"):
                chat_crypto.validate_encrypted_envelope({**base_env, forbidden_key: "hola"})

        # 2. Esquema inválido
        with self.assertRaisesRegex(ValueError, "no soportado"):
            chat_crypto.validate_encrypted_envelope({**base_env, "scheme": "aes-128-ecb"})

        # 3. Ciphertext < 17 bytes (1, 8 y 16 bytes)
        for bad_ct_len in (1, 8, 16):
            short_ct = base64.b64encode(b"X" * bad_ct_len).decode("ascii")
            with self.assertRaisesRegex(ValueError, "mín. 17 bytes"):
                chat_crypto.validate_encrypted_envelope({**base_env, "ciphertext_b64": short_ct})

        # 4. Límite máximo de tamaño de ciphertext_b64
        oversized_ct = "A" * (config.CHAT_MAX_CIPHERTEXT_B64_CHARS + 4)
        with self.assertRaisesRegex(ValueError, "supera el límite máximo"):
            chat_crypto.validate_encrypted_envelope({**base_env, "ciphertext_b64": oversized_ct})

        # 5. IV != 12 bytes (8, 11, 13 y 16 bytes)
        for bad_iv_len in (8, 11, 13, 16):
            bad_iv = base64.b64encode(b"N" * bad_iv_len).decode("ascii")
            with self.assertRaisesRegex(ValueError, "exactamente 12 bytes"):
                chat_crypto.validate_encrypted_envelope({**base_env, "iv_b64": bad_iv})

        # 6. key_epoch < 1
        with self.assertRaisesRegex(ValueError, "key_epoch"):
            chat_crypto.validate_encrypted_envelope({**base_env, "key_epoch": 0})

        # 7. Falta sender_key_fingerprint en esquemas ECDH y Room
        for scheme in ("e2ee-ecdh-p256-aes256gcm", "e2ee-room-aes256gcm"):
            with self.assertRaisesRegex(ValueError, "sender_key_fingerprint"):
                chat_crypto.validate_encrypted_envelope(
                    {**base_env, "scheme": scheme, "sender_key_fingerprint": "   "}
                )

        # 8. Esquema PSK PBKDF2: sal < 8 bytes rechazada; >= 8 bytes aceptada
        psk_env = {
            **base_env,
            "scheme": "e2ee-psk-pbkdf2-aes256gcm",
            "salt_b64": base64.b64encode(b"1234567").decode("ascii"),  # 7 bytes
        }
        with self.assertRaisesRegex(ValueError, "al menos 8 bytes"):
            chat_crypto.validate_encrypted_envelope(psk_env)

        psk_valid = {
            **psk_env,
            "salt_b64": base64.b64encode(b"12345678").decode("ascii"),  # 8 bytes
        }
        psk_norm = chat_crypto.validate_encrypted_envelope(psk_valid)
        self.assertEqual(psk_norm["iterations"], config.CHAT_PSK_ITERATIONS)

        # 9. Firma ECDSA truncada (< 32 bytes) y clave efímera fuera de curva
        with self.assertRaisesRegex(ValueError, "Firma ECDSA inválida"):
            chat_crypto.validate_encrypted_envelope(
                {**base_env, "signature_b64": base64.b64encode(b"S" * 31).decode("ascii")}
            )
        with self.assertRaisesRegex(ValueError, "no pertenece a la curva"):
            chat_crypto.validate_encrypted_envelope(
                {
                    **base_env,
                    "ephemeral_public_jwk": {
                        "kty": "EC",
                        "crv": "P-256",
                        "x": _int_to_b64url_32(1),
                        "y": _int_to_b64url_32(2),
                    },
                }
            )

    def test_validate_wrapped_key_entry_and_crypto_spec(self) -> None:
        valid_entry = {
            "wrapped_key_b64": base64.b64encode(b"W" * 48).decode("ascii"),
            "iv_b64": base64.b64encode(b"I" * 12).decode("ascii"),
            "ephemeral_public_jwk": _make_valid_jwk(3),
            "hkdf_salt_b64": base64.b64encode(b"S" * 16).decode("ascii"),
        }
        res = chat_crypto.validate_wrapped_key_entry(valid_entry, "op_brif_01")
        self.assertEqual(res["alg"], "ECDH-P256+HKDF-SHA256+AES-256-GCM")
        self.assertIn("ephemeral_public_jwk", res)

        with self.assertRaisesRegex(ValueError, "objeto JSON"):
            chat_crypto.validate_wrapped_key_entry(["invalid"], "op_brif_01")  # type: ignore[arg-type]

        # wrapped_key < 32 bytes
        with self.assertRaisesRegex(ValueError, "al menos 32 bytes"):
            chat_crypto.validate_wrapped_key_entry(
                {
                    **valid_entry,
                    "wrapped_key_b64": base64.b64encode(b"W" * 31).decode("ascii"),
                },
                "op_brif_01",
            )

        # IV != 12 bytes
        with self.assertRaisesRegex(ValueError, "12 bytes"):
            chat_crypto.validate_wrapped_key_entry(
                {
                    **valid_entry,
                    "iv_b64": base64.b64encode(b"I" * 16).decode("ascii"),
                },
                "op_brif_01",
            )

        # Ephemeral JWK inválido (con clave privada 'd' o punto fuera de curva)
        with self.assertRaisesRegex(ValueError, "componente privado 'd'"):
            chat_crypto.validate_wrapped_key_entry(
                {
                    **valid_entry,
                    "ephemeral_public_jwk": {**_make_valid_jwk(1), "d": _int_to_b64url_32(9)},
                },
                "op_brif_01",
            )

        spec = chat_crypto.build_crypto_spec()
        self.assertEqual(spec["protocol"], "JULI-E2EE-v1")
        self.assertTrue(spec["zero_knowledge_server"])
        self.assertEqual(set(spec["supported_schemes"]), set(config.CHAT_E2EE_SCHEMES))


class TestArgonAttachmentSecurity(unittest.TestCase):
    """Pruebas de alta complejidad de inspección antimalware y CDR en `attachment_security.py`."""

    def test_filename_traversal_null_control_bytes_and_double_extensions(self) -> None:
        valid_png = _make_valid_image_bytes("PNG")

        # Path traversal y separadores de ruta
        for traversal_name in (
            "../evil.png",
            "../../etc/passwd.png",
            "subdir/foto.png",
            "win\\dir\\foto.png",
            "..",
            "a..b.png",
        ):
            with self.assertRaisesRegex(MaliciousAttachmentError, "ruta o traversal"):
                attachment_security.inspect_and_sanitize_attachment(valid_png, traversal_name)

        # Null bytes y caracteres de control ASCII (< 32)
        for ctrl_name in (
            "foto\x00.png",
            "foto.png\x00.exe",
            "foto\n.png",
            "foto\r.png",
            "foto\t.png",
            "foto\x1f.png",
        ):
            with self.assertRaisesRegex(MaliciousAttachmentError, "caracteres de control"):
                attachment_security.inspect_and_sanitize_attachment(valid_png, ctrl_name)

        # Dobles extensiones peligrosas (todas las familias críticas)
        for bad_ext in (
            "exe",
            "dll",
            "bat",
            "cmd",
            "ps1",
            "vbs",
            "js",
            "mjs",
            "cjs",
            "html",
            "htm",
            "svg",
            "svgz",
            "php",
            "phtml",
            "py",
            "sh",
            "bash",
            "zsh",
            "scr",
            "msi",
            "com",
            "jar",
            "apk",
            "iso",
            "lnk",
            "hta",
            "wsf",
            "reg",
        ):
            with self.assertRaisesRegex(MaliciousAttachmentError, "Extensión peligrosa bloqueada"):
                attachment_security.inspect_and_sanitize_attachment(
                    valid_png, f"informe_tactico.{bad_ext}.png"
                )

        # Nombre vacío o con caracteres especiales se limpia a stem seguro
        res_empty = attachment_security.inspect_and_sanitize_attachment(valid_png, "   ")
        self.assertEqual(res_empty["safe_filename"], "adjunto.png")

    def test_camouflaged_leading_signatures_and_mime_extension_mismatch_blocked(self) -> None:
        payloads: list[tuple[bytes, str]] = [
            (b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64, "PE/MZ"),
            (b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64, "ELF"),
            (b"\xfe\xed\xfa\xce" + b"\x00" * 64, "Mach-O"),
            (b"\xfe\xed\xfa\xcf" + b"\x00" * 64, "Mach-O"),
            (b"\xca\xfe\xba\xbe" + b"\x00" * 64, "Mach-O"),
            (b"\xcf\xfa\xed\xfe" + b"\x00" * 64, "Mach-O"),
            (b"PK\x03\x04" + b"\x00" * 64, "contenedor comprimido"),
            (b"PK\x05\x06" + b"\x00" * 64, "contenedor comprimido"),
            (b"Rar!\x1a\x07\x00" + b"\x00" * 64, "contenedor comprimido"),
            (b"\x1f\x8b\x08\x00" + b"\x00" * 64, "contenedor comprimido"),
            (b"7z\xbc\xaf\x27\x1c" + b"\x00" * 64, "contenedor comprimido"),
            (b"   <svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'></svg>", "<svg"),
            (b"<?xml version='1.0'?><!DOCTYPE foo><foo/>", "<?xml"),
            (b"<!DOCTYPE html><html><body>xss</body></html>", "<!doctype html"),
            (b"<html><script>alert(1)</script></html>", "<html"),
            (b"<script>fetch('https://evil')</script>", "<script"),
            (b"<?php system($_GET['cmd']); ?>", "<?php"),
            (b"#!/bin/sh\nrm -rf /\n" + b"#" * 32, "#!"),
        ]
        for raw_bytes, expected_msg in payloads:
            with self.assertRaisesRegex(MaliciousAttachmentError, expected_msg):
                attachment_security.inspect_and_sanitize_attachment(
                    raw_bytes, "camuflado.png", "image/png"
                )

        # Contradicciones entre magic bytes y MIME/extensión declarados
        valid_png = _make_valid_image_bytes("PNG")
        clean_pdf = _make_minimal_pdf()
        with self.assertRaisesRegex(MaliciousAttachmentError, "Extensión contradictoria"):
            attachment_security.inspect_and_sanitize_attachment(valid_png, "engano.pdf")
        with self.assertRaisesRegex(MaliciousAttachmentError, "Tipo MIME declarado"):
            attachment_security.inspect_and_sanitize_attachment(
                valid_png, "foto.png", "application/pdf"
            )
        with self.assertRaisesRegex(MaliciousAttachmentError, "Extensión contradictoria"):
            attachment_security.inspect_and_sanitize_attachment(clean_pdf, "falso.png")
        with self.assertRaisesRegex(MaliciousAttachmentError, "Tipo MIME declarado"):
            attachment_security.inspect_and_sanitize_attachment(clean_pdf, "doc.pdf", "image/png")

        # Archivo demasiado corto (< 16 bytes)
        with self.assertRaisesRegex(MaliciousAttachmentError, "demasiado pequeño"):
            attachment_security.inspect_and_sanitize_attachment(b"\x89PNG\r\n\x1a\n", "tiny.png")

    def test_png_crc32_corruption_trailing_payload_and_text_itxt_scripts(self) -> None:
        valid_png = _make_valid_image_bytes("PNG")

        # 1. Corrupción de CRC32 en el chunk IHDR
        corrupted_crc_png = bytearray(valid_png)
        corrupted_crc_png[29] ^= 0xFF
        with self.assertRaisesRegex(MaliciousAttachmentError, "Checksum CRC32 inválido"):
            attachment_security.inspect_and_sanitize_attachment(
                bytes(corrupted_crc_png), "bad_crc.png"
            )

        # 2. Payload oculto tras IEND (polyglot PNG + archivo ZIP/ejecutable anexado)
        polyglot_png = valid_png + b"PK\x03\x04HIDDEN_PAYLOAD_AFTER_IEND"
        with self.assertRaisesRegex(
            MaliciousAttachmentError, "datos ocultos tras la marca de fin IEND"
        ):
            attachment_security.inspect_and_sanitize_attachment(polyglot_png, "polyglot.png")

        # 3. Scripts maliciosos en chunks tEXt e iTXt con CRC32 válido (insertados antes de IEND)
        iend_offset = valid_png.rfind(b"\x00\x00\x00\x00IEND")
        self.assertGreater(iend_offset, 8)
        prefix = valid_png[:iend_offset]
        iend_chunk = valid_png[iend_offset:]

        malicious_chunks = [
            _build_png_chunk(b"tEXt", b"Comment\x00<script>alert('xss')</script>"),
            _build_png_chunk(
                b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00<?php eval($_GET['x']); ?>"
            ),
            _build_png_chunk(b"tEXt", b"Author\x00MZ\x90\x00PE_HEADER_IN_TEXT"),
        ]
        for chunk in malicious_chunks:
            crafted = prefix + chunk + iend_chunk
            with self.assertRaisesRegex(MaliciousAttachmentError, "chunk PNG (tEXt|iTXt)"):
                attachment_security.inspect_and_sanitize_attachment(crafted, "xss_meta.png")

        # 4. PNG sin IEND o cuyo primer chunk no es IHDR
        with self.assertRaisesRegex(MaliciousAttachmentError, "falta IHDR o IEND"):
            attachment_security.inspect_and_sanitize_attachment(prefix, "no_iend.png")
        bad_first_chunk_png = (
            b"\x89PNG\r\n\x1a\n" + _build_png_chunk(b"tEXt", b"k\x00v") + iend_chunk
        )
        with self.assertRaisesRegex(MaliciousAttachmentError, "primer chunk debe ser IHDR"):
            attachment_security.inspect_and_sanitize_attachment(bad_first_chunk_png, "no_ihdr.png")

    def test_jpeg_trailing_payload_and_header_script_injection(self) -> None:
        valid_jpg = _make_valid_image_bytes("JPEG")

        # 1. Payload oculto tras 0xFFD9 (EOI)
        with self.assertRaisesRegex(MaliciousAttachmentError, "tras EOI \\(0xFFD9\\)"):
            attachment_security.inspect_and_sanitize_attachment(
                valid_jpg + b"<?php system('id'); ?>", "polyglot.jpg"
            )

        # 2. Script embebido en segmento COM (0xFFFE) dentro de la cabecera JPEG pero con EOI válido
        comment_payload = b"<?php system($_GET['c']); ?>"
        com_segment = b"\xff\xfe" + struct.pack(">H", len(comment_payload) + 2) + comment_payload
        injected_jpg = valid_jpg[:2] + com_segment + valid_jpg[2:]
        with self.assertRaisesRegex(MaliciousAttachmentError, "cabecera JPEG"):
            attachment_security.inspect_and_sanitize_attachment(injected_jpg, "comment_php.jpg")

    def test_webp_riff_length_mismatch_and_gif_terminator_or_script(self) -> None:
        # WEBP con tamaño RIFF adulterado o payload anexado tras el contenedor
        valid_webp = _make_valid_image_bytes("WEBP")
        with self.assertRaisesRegex(MaliciousAttachmentError, "contenedor RIFF"):
            attachment_security.inspect_and_sanitize_attachment(
                valid_webp + b"EXTRA_HIDDEN_BYTES", "bad.webp"
            )
        tampered_webp = bytearray(valid_webp)
        struct.pack_into("<I", tampered_webp, 4, len(valid_webp) + 100)
        with self.assertRaisesRegex(MaliciousAttachmentError, "contenedor RIFF"):
            attachment_security.inspect_and_sanitize_attachment(
                bytes(tampered_webp), "bad_len.webp"
            )

        # GIF sin terminador ';' (0x3B) o con basura posterior
        valid_gif = _make_valid_image_bytes("GIF")
        with self.assertRaisesRegex(MaliciousAttachmentError, "terminador ';'"):
            attachment_security.inspect_and_sanitize_attachment(
                valid_gif[:-1] + b"\x21", "no_term.gif"
            )
        with self.assertRaisesRegex(MaliciousAttachmentError, "terminador ';'"):
            attachment_security.inspect_and_sanitize_attachment(
                valid_gif + b"TRAILING", "trailing.gif"
            )

        # GIF con terminador ';' válido pero con script embebido
        gif_with_script = valid_gif[:-1] + b"<script>evil()</script>;"
        with self.assertRaisesRegex(MaliciousAttachmentError, "metadatos GIF"):
            attachment_security.inspect_and_sanitize_attachment(gif_with_script, "script.gif")

    def test_cdr_sanitization_strips_exif_and_preserves_valid_magic_bytes(self) -> None:
        # 1. JPEG con metadatos EXIF sensibles (cámara, coordenadas/descripción)
        img = Image.new("RGB", (40, 30), color=(10, 200, 90))
        exif = img.getexif()
        exif[0x010F] = "DroneThermalCam-X9"
        exif[0x010E] = "CoordSecreta:41.987,-6.123"
        exif[0x0131] = "JULI-Field-Software"
        jpg_buf = io.BytesIO()
        img.save(jpg_buf, format="JPEG", exif=exif.tobytes())
        raw_jpg = jpg_buf.getvalue()
        self.assertIn(b"DroneThermalCam-X9", raw_jpg)
        self.assertIn(b"CoordSecreta", raw_jpg)

        res_jpg = attachment_security.inspect_and_sanitize_attachment(
            raw_jpg, "captura dron #1.jpeg", "image/jpeg"
        )
        clean_jpg = res_jpg["clean_bytes"]
        self.assertEqual(res_jpg["kind"], "image")
        self.assertEqual(res_jpg["format"], "JPEG")
        self.assertEqual(res_jpg["width"], 40)
        self.assertEqual(res_jpg["height"], 30)
        self.assertTrue(res_jpg["security_scan"]["sanitized_cdr"])
        self.assertTrue(clean_jpg.startswith(b"\xff\xd8\xff"))
        self.assertTrue(clean_jpg.endswith(b"\xff\xd9"))
        self.assertNotIn(b"DroneThermalCam-X9", clean_jpg)
        self.assertNotIn(b"CoordSecreta", clean_jpg)
        with Image.open(io.BytesIO(clean_jpg)) as reloaded_jpg:
            self.assertEqual(len(reloaded_jpg.getexif()), 0)

        # 2. PNG con chunks tEXt benignos y EXIF: verificar eliminación tras CDR
        png_info = PngImagePlugin.PngInfo()
        png_info.add_text("Author", "OperarioSecretName")
        png_info.add_text("Software", "TacticalMapper")
        png_buf = io.BytesIO()
        img.save(png_buf, format="PNG", pnginfo=png_info, exif=exif.tobytes())
        raw_png = png_buf.getvalue()
        self.assertIn(b"OperarioSecretName", raw_png)

        res_png = attachment_security.inspect_and_sanitize_attachment(
            raw_png, "mapa.png", "image/png"
        )
        clean_png = res_png["clean_bytes"]
        self.assertTrue(clean_png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotIn(b"OperarioSecretName", clean_png)
        self.assertNotIn(b"DroneThermalCam-X9", clean_png)

        # 3. WEBP y GIF (estático y animado) sanitizados con CDR
        res_webp = attachment_security.inspect_and_sanitize_attachment(
            _make_valid_image_bytes("WEBP"), "terreno.webp", "image/webp"
        )
        self.assertEqual(res_webp["clean_bytes"][:4], b"RIFF")
        self.assertEqual(res_webp["clean_bytes"][8:12], b"WEBP")

        frame1 = Image.new("RGB", (16, 16), color=(255, 0, 0))
        frame2 = Image.new("RGB", (16, 16), color=(0, 255, 0))
        anim_buf = io.BytesIO()
        frame1.save(
            anim_buf, format="GIF", save_all=True, append_images=[frame2], duration=80, loop=0
        )
        res_gif = attachment_security.inspect_and_sanitize_attachment(
            anim_buf.getvalue(), "radar.gif", "image/gif"
        )
        self.assertTrue(res_gif["clean_bytes"].startswith((b"GIF87a", b"GIF89a")))
        self.assertTrue(res_gif["clean_bytes"].endswith(b";"))

        # 4. Protección contra dimensiones excesivas (pixel-flood)
        with mock.patch.object(config, "CHAT_IMAGE_MAX_WIDTH", 16):
            with self.assertRaisesRegex(
                MaliciousAttachmentError, "Dimensiones de imagen fuera de límite"
            ):
                attachment_security.inspect_and_sanitize_attachment(raw_png, "too_wide.png")

    def test_pdf_header_offset_trailing_eof_hex_obfuscation_flate_and_zipbomb(self) -> None:
        # 1. PDF limpio válido con stream FlateDecode inocuo
        clean_pdf = _make_minimal_pdf(stream_payload=b"BT /F1 12 Tf (Parte de incendio) Tj ET")
        res_pdf = attachment_security.inspect_and_sanitize_attachment(
            clean_pdf, "parte_incendio.pdf", "application/pdf"
        )
        self.assertEqual(res_pdf["kind"], "pdf")
        self.assertEqual(res_pdf["format"], "PDF")
        self.assertTrue(res_pdf["security_scan"]["verified"])

        # 2. Cabecera fuera de offset 0 o versión PDF inválida
        with self.assertRaisesRegex(
            MaliciousAttachmentError, "no corresponde por cabecera|Cabecera %PDF"
        ):
            attachment_security.inspect_and_sanitize_attachment(
                b"   " + clean_pdf, "offset_bad.pdf", "application/pdf"
            )
        with self.assertRaisesRegex(MaliciousAttachmentError, "Cabecera %PDF inválida"):
            attachment_security._inspect_pdf(b"  %PDF-1.7\n1 0 obj\nendobj\ntrailer\n%%EOF")
        with self.assertRaisesRegex(MaliciousAttachmentError, "Cabecera %PDF inválida"):
            attachment_security.inspect_and_sanitize_attachment(
                _make_minimal_pdf(header=b"%PDF-1.9\n"), "bad_ver.pdf", "application/pdf"
            )

        # 3. Basura añadida tras %%EOF y falta de marcadores estructurales
        with self.assertRaisesRegex(MaliciousAttachmentError, "después de '%%EOF'"):
            attachment_security.inspect_and_sanitize_attachment(
                _make_minimal_pdf(trailing_after_eof=b"\nHIDDEN_PAYLOAD_AFTER_EOF"),
                "trailing.pdf",
                "application/pdf",
            )
        with self.assertRaisesRegex(MaliciousAttachmentError, "falta marcador de cierre '%%EOF'"):
            attachment_security.inspect_and_sanitize_attachment(
                b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n", "no_eof.pdf"
            )

        # 4. Nombres peligrosos ofuscados en hexadecimal (#XX)
        for obfuscated_token, expected_canonical in (
            (b"/J#53", "/JS"),
            (b"/Open#41ction", "/OpenAction"),
            (b"/Embe#64dedFile", "/EmbeddedFile"),
            (b"/#45ncrypt", "/Encrypt"),
            (b"/Java#53cript", "/JavaScript"),
            (b"/La#75nch", "/Launch"),
            (b"/#41#41", "/AA"),
            (b"/Embedded#46iles", "/EmbeddedFiles"),
            (b"/X#46A", "/XFA"),
            (b"/Rich#4dedia", "/RichMedia"),
            (b"/Submit#46orm", "/SubmitForm"),
            (b"/Import#44ata", "/ImportData"),
            (b"/GoTo#45", "/GoToE"),
            (b"/GoTo#52", "/GoToR"),
        ):
            malicious_pdf = _make_minimal_pdf(
                extra_body=b"4 0 obj\n<< /Type /Action "
                + obfuscated_token
                + b" (alert(1)) >>\nendobj\n"
            )
            with self.assertRaisesRegex(MaliciousAttachmentError, expected_canonical):
                attachment_security.inspect_and_sanitize_attachment(
                    malicious_pdf, "obfuscated.pdf", "application/pdf"
                )

        # 5. Amenaza oculta dentro de un stream comprimido FlateDecode
        compressed_threat_pdf = _make_minimal_pdf(
            stream_payload=(
                b"<< /Type /Action /S /Java#53cript /J#53 (app.launchURL('http://evil')) >>"
            ),
            compress_stream=True,
        )
        with self.assertRaisesRegex(MaliciousAttachmentError, "stream PDF #1"):
            attachment_security.inspect_and_sanitize_attachment(
                compressed_threat_pdf, "hidden_stream_js.pdf", "application/pdf"
            )

        # 6. Detección de zip-bomb en stream FlateDecode superando CHAT_PDF_MAX_DECOMPRESSED_BYTES
        real_bomb_payload = b"\x00" * (config.CHAT_PDF_MAX_DECOMPRESSED_BYTES + 65536)
        bomb_pdf = _make_minimal_pdf(stream_payload=real_bomb_payload, compress_stream=True)
        self.assertLess(len(bomb_pdf), config.CHAT_ATTACHMENT_MAX_BYTES)
        with self.assertRaisesRegex(MaliciousAttachmentError, "zip-bomb"):
            attachment_security.inspect_and_sanitize_attachment(
                bomb_pdf, "bomb.pdf", "application/pdf"
            )

        # 7. Tamaño máximo de adjunto excedido (> CHAT_ATTACHMENT_MAX_BYTES)
        with mock.patch.object(config, "CHAT_ATTACHMENT_MAX_BYTES", 1024):
            oversized = clean_pdf + b" " * 2048
            with self.assertRaisesRegex(MaliciousAttachmentError, "supera el límite máximo"):
                attachment_security.inspect_and_sanitize_attachment(oversized, "huge.pdf")


if __name__ == "__main__":
    unittest.main()
