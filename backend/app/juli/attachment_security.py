"""Validación profunda antimalware y sanitización (CDR) para imágenes y PDFs en JULI.

Comprueba antes de distribuir cualquier archivo a los participantes del chat:
  1. Nombre e higiene de extensión (bloquea null bytes, traversal y dobles extensiones peligrosas).
  2. Detección real por magic bytes y estructura binaria (sin confiar en MIME ni extensión).
  3. Bloqueo explícito de ejecutables (`MZ`, `ELF`), HTML/PHP, `ZIP`/`DOCX` y `SVG` (riesgo XSS).
  4. Para **imágenes (`PNG`, `JPEG`, `WEBP`, `GIF`)**: validación de chunks/marcadores, detección de
     polyglots tras `IEND`/`EOF`, protección contra bombas de descompresión (píxeles máximos) y
     re-codificación limpia (Content Disarm & Reconstruction) con `Pillow` sin metadatos EXIF.
  5. Para **PDF (`application/pdf`)**: cabecera en offset `0`, cierre `%%EOF` sin cola oculta,
     descompresión segura de streams `FlateDecode` (anti zip-bomb), decodificación de nombres
     ofuscados `#XX` y bloqueo de contenido activo (`/JS`, `/JavaScript`, `/Launch`,
     `/OpenAction`, `/AA`, `/EmbeddedFile`, `/EmbeddedFiles`, `/XFA`, `/RichMedia`, `/SubmitForm`,
     `/ImportData`, `/GoToE`, `/GoToR`, `/Encrypt`).
"""

from __future__ import annotations

import hashlib
import io
import re
import struct
import zlib
from typing import Any

from . import config

try:
    from PIL import Image, ImageSequence

    _HAS_PIL = True
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageSequence = None  # type: ignore[assignment]
    _HAS_PIL = False

_DANGEROUS_EXTENSIONS = frozenset(
    {
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
    }
)

_IMAGE_FORMATS: dict[str, dict[str, Any]] = {
    "PNG": {"mime": "image/png", "ext": "png", "aliases": {"image/png"}},
    "JPEG": {
        "mime": "image/jpeg",
        "ext": "jpg",
        "aliases": {"image/jpeg", "image/jpg", "image/pjpeg"},
    },
    "WEBP": {"mime": "image/webp", "ext": "webp", "aliases": {"image/webp"}},
    "GIF": {"mime": "image/gif", "ext": "gif", "aliases": {"image/gif"}},
}

_PDF_DANGEROUS_NAME_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("/JS", re.compile(rb"/JS(?![A-Za-z0-9_])")),
    ("/JavaScript", re.compile(rb"/JavaScript(?![A-Za-z0-9_])")),
    ("/Launch", re.compile(rb"/Launch(?![A-Za-z0-9_])")),
    ("/OpenAction", re.compile(rb"/OpenAction(?![A-Za-z0-9_])")),
    ("/AA", re.compile(rb"/AA(?![A-Za-z0-9_])")),
    ("/EmbeddedFile", re.compile(rb"/EmbeddedFile(?![A-Za-z0-9_])")),
    ("/EmbeddedFiles", re.compile(rb"/EmbeddedFiles(?![A-Za-z0-9_])")),
    ("/XFA", re.compile(rb"/XFA(?![A-Za-z0-9_])")),
    ("/RichMedia", re.compile(rb"/RichMedia(?![A-Za-z0-9_])")),
    ("/SubmitForm", re.compile(rb"/SubmitForm(?![A-Za-z0-9_])")),
    ("/ImportData", re.compile(rb"/ImportData(?![A-Za-z0-9_])")),
    ("/GoToE", re.compile(rb"/GoToE(?![A-Za-z0-9_])")),
    ("/GoToR", re.compile(rb"/GoToR(?![A-Za-z0-9_])")),
    ("/Sound", re.compile(rb"/Sound(?![A-Za-z0-9_])")),
    ("/Movie", re.compile(rb"/Movie(?![A-Za-z0-9_])")),
    ("/Encrypt", re.compile(rb"/Encrypt(?![A-Za-z0-9_])")),
)

_SCRIPT_POLYGLOT_PATTERNS: tuple[re.Pattern[bytes], ...] = (
    re.compile(rb"<\s*script\b", re.IGNORECASE),
    re.compile(rb"<\?(?:php|=)", re.IGNORECASE),
    re.compile(rb"<\s*svg\b", re.IGNORECASE),
    re.compile(rb"<\s*iframe\b", re.IGNORECASE),
    re.compile(rb"<!doctype\s+html", re.IGNORECASE),
    re.compile(rb"<\s*html\b", re.IGNORECASE),
    re.compile(rb"\bjavascript\s*:", re.IGNORECASE),
    re.compile(rb"WScript\.Shell", re.IGNORECASE),
)


class MaliciousAttachmentError(ValueError):
    """Se lanza cuando un archivo adjunto incumple la validación de formato o seguridad."""


def _sanitize_stem(filename: str) -> tuple[str, str]:
    """Limpia el nombre de archivo y detecta rutas/extensiones dobles maliciosas."""
    raw = str(filename or "").strip()
    if not raw:
        return "adjunto", ""
    if "\x00" in raw or any(ord(ch) < 32 for ch in raw):
        raise MaliciousAttachmentError(
            "Nombre de archivo inválido (contiene caracteres de control)."
        )
    if "/" in raw or "\\" in raw or ".." in raw:
        raise MaliciousAttachmentError("Nombre de archivo inválido (ruta o traversal detectado).")

    parts = raw.split(".")
    for ext_part in parts[1:]:
        if ext_part.lower() in _DANGEROUS_EXTENSIONS:
            raise MaliciousAttachmentError(
                f"Extensión peligrosa bloqueada en nombre de archivo ('.{ext_part.lower()}')."
            )

    declared_ext = parts[-1].lower() if len(parts) > 1 else ""
    stem_raw = ".".join(parts[:-1]) if len(parts) > 1 else parts[0]
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem_raw).strip("_")[:64] or "adjunto"
    return safe_stem, declared_ext


def _reject_dangerous_leading_signatures(data: bytes) -> None:
    """Bloquea cabeceras de ejecutables, archivos comprimidos y scripts en offset 0."""
    head_lstrip = data[:512].lstrip()
    head_lower = head_lstrip.lower()
    if data.startswith(b"MZ"):
        raise MaliciousAttachmentError("Archivo bloqueado: ejecutable Windows (PE/MZ) camuflado.")
    if data.startswith(b"\x7fELF"):
        raise MaliciousAttachmentError("Archivo bloqueado: binario ejecutable ELF camuflado.")
    if data[:4] in (
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xca\xfe\xba\xbe",
        b"\xcf\xfa\xed\xfe",
    ):
        raise MaliciousAttachmentError("Archivo bloqueado: binario ejecutable Mach-O camuflado.")
    if data.startswith(
        (b"PK\x03\x04", b"PK\x05\x06", b"Rar!", b"\x1f\x8b\x08", b"7z\xbc\xaf\x27\x1c")
    ):
        raise MaliciousAttachmentError(
            "Archivo bloqueado: contenedor comprimido (ZIP/RAR/7z/GZIP)."
        )
    if head_lstrip.startswith(b"#!"):
        raise MaliciousAttachmentError("Archivo bloqueado: script ejecutable (#!).")
    for prefix in (b"<svg", b"<?xml", b"<html", b"<!doctype html", b"<script", b"<?php"):
        if head_lower.startswith(prefix):
            tag = prefix.decode("ascii")
            raise MaliciousAttachmentError(
                f"Archivo bloqueado: documento activo/XML/SVG no permitido ('{tag}')."
            )


def _scan_text_payload_for_polyglot(chunk: bytes, *, context: str) -> None:
    if (
        b"MZ\x90\x00" in chunk
        or b"This program cannot be run in DOS mode" in chunk
        or b"\x7fELF" in chunk
    ):
        raise MaliciousAttachmentError(f"Contenido ejecutable oculto detectado en {context}.")
    for pat in _SCRIPT_POLYGLOT_PATTERNS:
        if pat.search(chunk):
            raise MaliciousAttachmentError(
                f"Posible código/script malicioso embebido detectado en {context}."
            )


def _detect_binary_format(data: bytes) -> tuple[str, str]:
    """Identifica el tipo real exclusivamente por firma binaria (magic bytes)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "image", "JPEG"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "WEBP"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image", "GIF"
    if data.startswith((b"%PDF-1.", b"%PDF-2.")):
        return "pdf", "PDF"
    raise MaliciousAttachmentError(
        "Formato rechazado: el archivo no corresponde por cabecera binaria real "
        "a PNG, JPEG, WEBP, GIF ni PDF."
    )


def _validate_png_chunks(data: bytes) -> None:
    """Valida todos los chunks PNG, CRC32 y ausencia de payload tras `IEND`."""
    pos = 8
    saw_ihdr = False
    saw_iend = False
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        data_start = pos + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(data):
            raise MaliciousAttachmentError("PNG corrupto o truncado.")
        payload = data[data_start:data_end]
        expected_crc = struct.unpack(">I", data[data_end:crc_end])[0]
        if (zlib.crc32(chunk_type + payload) & 0xFFFFFFFF) != expected_crc:
            raise MaliciousAttachmentError(f"Checksum CRC32 inválido en chunk PNG {chunk_type!r}.")

        if pos == 8 and chunk_type != b"IHDR":
            raise MaliciousAttachmentError("PNG inválido: el primer chunk debe ser IHDR.")
        if chunk_type == b"IHDR":
            saw_ihdr = True
        if chunk_type in (b"tEXt", b"iTXt", b"zTXt"):
            _scan_text_payload_for_polyglot(
                payload, context=f"chunk PNG {chunk_type.decode('ascii')}"
            )

        pos = crc_end
        if chunk_type == b"IEND":
            saw_iend = True
            break

    if not (saw_ihdr and saw_iend):
        raise MaliciousAttachmentError("PNG incompleto: falta IHDR o IEND.")
    if pos < len(data):
        raise MaliciousAttachmentError(
            "Polyglot detectado: el PNG contiene datos ocultos tras la marca de fin IEND."
        )


def _inspect_and_sanitize_image(
    data: bytes, fmt: str
) -> tuple[bytes, int | None, int | None, list[str]]:
    """Verifica integridad de imagen, protege contra pixel-flood y limpia metadatos con CDR."""
    checks = [f"magic_bytes:{fmt}", "no_executable_or_svg_signature"]

    if fmt == "PNG":
        _validate_png_chunks(data)
        checks.append("png_chunks_crc_and_no_trailing_payload")
    elif fmt == "WEBP":
        riff_size = int.from_bytes(data[4:8], "little") + 8
        if riff_size != len(data):
            raise MaliciousAttachmentError(
                "WEBP inválido o con payload oculto anexado al final del contenedor RIFF."
            )
        checks.append("webp_riff_bounds_verified")
    elif fmt == "GIF":
        if not data.rstrip(b"\x00").endswith(b"\x3b"):
            raise MaliciousAttachmentError(
                "GIF truncado o con datos añadidos tras el terminador ';'."
            )
        _scan_text_payload_for_polyglot(data, context="metadatos GIF")
        checks.append("gif_terminator_verified")
    elif fmt == "JPEG":
        if not data.rstrip(b"\x00 \t\r\n").endswith(b"\xff\xd9"):
            raise MaliciousAttachmentError("JPEG truncado o con payload oculto tras EOI (0xFFD9).")
        _scan_text_payload_for_polyglot(data[:65536], context="cabecera JPEG")
        checks.append("jpeg_eoi_verified")

    if not _HAS_PIL:
        return data, None, None, checks

    prev_max = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = config.CHAT_IMAGE_MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            actual_fmt = (probe.format or "").upper()
            if actual_fmt != fmt:
                raise MaliciousAttachmentError(
                    f"Discrepancia de formato de imagen: cabecera {fmt}, parser {actual_fmt}."
                )
            width, height = probe.size
            if (
                width < 1
                or height < 1
                or width > config.CHAT_IMAGE_MAX_WIDTH
                or height > config.CHAT_IMAGE_MAX_HEIGHT
                or width * height > config.CHAT_IMAGE_MAX_PIXELS
            ):
                raise MaliciousAttachmentError(
                    f"Dimensiones de imagen fuera de límite seguro ({width}x{height})."
                )
            probe.verify()

        with Image.open(io.BytesIO(data)) as img:
            img.load()
            for k, v in (img.info or {}).items():
                if isinstance(v, (bytes, str)):
                    raw_val = v if isinstance(v, bytes) else v.encode("utf-8", errors="ignore")
                    _scan_text_payload_for_polyglot(raw_val, context=f"metadato {k}")

            out = io.BytesIO()
            is_animated = bool(
                getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1
            )
            if fmt == "GIF" and is_animated:
                frames = [frame.copy().convert("RGBA") for frame in ImageSequence.Iterator(img)]
                durations = [
                    frame.info.get("duration", 100) for frame in ImageSequence.Iterator(img)
                ]
                frames[0].save(
                    out,
                    format="GIF",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=0,
                )
            elif fmt == "JPEG":
                clean_rgb = img.convert("RGB")
                clean_rgb.save(out, format="JPEG", quality=90, optimize=True)
            elif fmt == "PNG":
                clean_img = img.copy()
                clean_img.info.clear()
                clean_img.save(out, format="PNG", optimize=True)
            elif fmt == "WEBP":
                clean_img = img.copy()
                clean_img.save(out, format="WEBP", quality=90)
            else:  # GIF estático
                clean_img = img.convert("RGBA")
                clean_img.save(out, format="GIF")

            sanitized_bytes = out.getvalue()
            checks.extend(["pillow_verify_and_full_decode", "cdr_reencode_metadata_stripped"])
            return sanitized_bytes, width, height, checks
    except MaliciousAttachmentError:
        raise
    except Exception as exc:
        raise MaliciousAttachmentError(
            f"Imagen corrupta, malformada o bomba de descompresión rechazada: {exc}"
        ) from exc
    finally:
        Image.MAX_IMAGE_PIXELS = prev_max


def _decode_pdf_hex_names(buf: bytes) -> bytes:
    """Decodifica escapes `#XX` dentro de nombres PDF (ej. `/J#53` -> `/JS`)."""
    if b"#" not in buf:
        return buf
    return re.sub(
        rb"#([0-9A-Fa-f]{2})",
        lambda m: bytes([int(m.group(1), 16)]),
        buf,
    )


def _scan_pdf_buffer_for_threats(buf: bytes, *, context: str) -> None:
    normalized = _decode_pdf_hex_names(buf)
    for token_name, pat in _PDF_DANGEROUS_NAME_PATTERNS:
        if pat.search(normalized):
            raise MaliciousAttachmentError(
                f"PDF rechazado por contener elemento activo/peligroso '{token_name}' en {context}."
            )
    _scan_text_payload_for_polyglot(normalized, context=context)


def _inspect_pdf(data: bytes) -> list[str]:
    """Verifica que el PDF es real sin scripts, acciones automáticas ni adjuntos ocultos."""
    if not re.match(rb"^%PDF-(?:1\.[0-7]|2\.[0-9])[ \t\r\n]", data[:16]):
        raise MaliciousAttachmentError(
            "Cabecera %PDF inválida o desplazamiento no nulo (posible polyglot)."
        )

    tail = data[-1024:]
    eof_idx = tail.rfind(b"%%EOF")
    if eof_idx == -1:
        raise MaliciousAttachmentError(
            "PDF inválido: falta marcador de cierre '%%EOF' al final del archivo."
        )
    after_eof = tail[eof_idx + 5 :].strip()
    if len(after_eof) > 0:
        raise MaliciousAttachmentError(
            "Polyglot detectado: el PDF contiene bytes añadidos después de '%%EOF'."
        )

    if not re.search(rb"\bobj\b", data) or not re.search(rb"\bendobj\b", data):
        raise MaliciousAttachmentError(
            "PDF inválido: carece de estructura de objetos ('obj'/'endobj')."
        )
    if b"trailer" not in data and b"/XRef" not in data and b"/Catalog" not in data:
        raise MaliciousAttachmentError(
            "PDF inválido: falta tabla/diccionario raíz (trailer o /XRef)."
        )

    _scan_pdf_buffer_for_threats(data, context="cuerpo principal PDF")

    total_decompressed = 0
    stream_count = 0
    for m in re.finditer(
        rb"stream(?:\r\n|\n|\r)(.*?)(?:\r\n|\n|\r)?endstream", data, flags=re.DOTALL
    ):
        stream_count += 1
        stream_body = m.group(1)
        # Intentar descomprimir streams FlateDecode para detectar /JS u /ObjStm ocultos
        if stream_body.startswith((b"\x78\x9c", b"\x78\xda", b"\x78\x01", b"\x78\x5e")):
            decomp = zlib.decompressobj()
            remaining_budget = max(1, config.CHAT_PDF_MAX_DECOMPRESSED_BYTES - total_decompressed)
            try:
                unpacked = decomp.decompress(stream_body, max_length=remaining_budget)
            except zlib.error:
                continue
            if decomp.unconsumed_tail:
                raise MaliciousAttachmentError(
                    "PDF rechazado: stream comprimido excede el presupuesto seguro "
                    "(posible zip-bomb)."
                )
            total_decompressed += len(unpacked)
            _scan_pdf_buffer_for_threats(unpacked, context=f"stream PDF #{stream_count}")

    return [
        "pdf_header_offset_0",
        "pdf_eof_and_no_trailing_payload",
        "pdf_structural_objects_verified",
        f"pdf_streams_and_hex_names_scanned:{stream_count}",
    ]


def inspect_and_sanitize_attachment(
    content_bytes: bytes,
    filename: str,
    declared_mime_type: str | None = None,
) -> dict[str, Any]:
    """Valida exhaustivamente que un adjunto es una imagen o PDF legítimo y no malicioso."""
    if not isinstance(content_bytes, (bytes, bytearray)) or len(content_bytes) < 16:
        raise MaliciousAttachmentError(
            "Archivo vacío o demasiado pequeño para ser una imagen o PDF válido."
        )

    raw = bytes(content_bytes)
    if len(raw) > config.CHAT_ATTACHMENT_MAX_BYTES:
        max_mib = config.CHAT_ATTACHMENT_MAX_BYTES // (1024 * 1024)
        raise MaliciousAttachmentError(
            f"El archivo supera el límite máximo permitido ({max_mib} MiB)."
        )

    safe_stem, declared_ext = _sanitize_stem(filename)
    _reject_dangerous_leading_signatures(raw)
    kind, fmt = _detect_binary_format(raw)

    decl_mime = (declared_mime_type or "").split(";")[0].strip().lower()
    if kind == "image":
        fmt_info = _IMAGE_FORMATS[fmt]
        canonical_mime = fmt_info["mime"]
        canonical_ext = fmt_info["ext"]
        if (
            decl_mime
            and decl_mime != "application/octet-stream"
            and decl_mime not in fmt_info["aliases"]
        ):
            raise MaliciousAttachmentError(
                f"Tipo MIME declarado '{decl_mime}' no coincide con la imagen detectada "
                f"({canonical_mime})."
            )
        if declared_ext and declared_ext == "pdf":
            raise MaliciousAttachmentError(
                "Extensión contradictoria: el archivo dice '.pdf' pero su contenido real "
                "es una imagen."
            )
        clean_bytes, width, height, checks = _inspect_and_sanitize_image(raw, fmt)
        sanitized = clean_bytes != raw or _HAS_PIL
    else:
        canonical_mime = "application/pdf"
        canonical_ext = "pdf"
        if decl_mime and decl_mime not in ("application/pdf", "application/octet-stream"):
            raise MaliciousAttachmentError(
                f"Tipo MIME declarado '{decl_mime}' no coincide con PDF real."
            )
        if declared_ext and declared_ext in ("png", "jpg", "jpeg", "gif", "webp"):
            raise MaliciousAttachmentError(
                f"Extensión contradictoria: el archivo dice '.{declared_ext}' pero es un PDF."
            )
        clean_bytes = raw
        width = None
        height = None
        checks = _inspect_pdf(raw)
        sanitized = False

    return {
        "kind": kind,
        "format": fmt,
        "mime_type": canonical_mime,
        "extension": canonical_ext,
        "safe_filename": f"{safe_stem}.{canonical_ext}",
        "clean_bytes": clean_bytes,
        "size_bytes": len(clean_bytes),
        "sha256": hashlib.sha256(clean_bytes).hexdigest(),
        "width": width,
        "height": height,
        "security_scan": {
            "verified": True,
            "sanitized_cdr": sanitized,
            "checks_passed": checks,
        },
    }
