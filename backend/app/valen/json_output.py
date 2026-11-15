#!/usr/bin/env python3
"""
Algoritmo VALEN — Escritor JSON unificado (salida en 1 archivo JSON array en lugar de JSONL).

Uso:
    from json_output import JSONArrayWriter

    with JSONArrayWriter("output.json") as w:
        for record in records:
            w.write(record)
    # Automáticamente escribe '[' al abrir, ',' entre registros, ']' al cerrar
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class JSONArrayWriter:
    """
    Escribe registros como un único array JSON en un archivo.
    Maneja streaming eficiente: no carga todo en memoria.
    """

    def __init__(
        self,
        path: str | Path,
        indent: int | None = None,
        ensure_ascii: bool = False,
        buffer_size: int = 8192,
    ):
        self.path = Path(path)
        self.indent = indent
        self.ensure_ascii = ensure_ascii
        self.buffer_size = buffer_size
        self._file = None
        self._first = True
        self._count = 0

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "w", encoding="utf-8", buffering=self.buffer_size)
        self._file.write("[")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.write("\n]")
            self._file.close()
        return False

    def write(self, record: dict[str, Any]) -> None:
        """Escribe un registro en el array JSON."""
        if not self._first:
            self._file.write(",")
        else:
            self._first = False

        if self.indent:
            self._file.write("\n" + " " * self.indent)
        json.dump(record, self._file, ensure_ascii=self.ensure_ascii, separators=(",", ":"))
        self._count += 1

    def write_batch(self, records: list[dict[str, Any]]) -> None:
        """Escribe múltiples registros de una vez."""
        for r in records:
            self.write(r)

    @property
    def count(self) -> int:
        return self._count


@contextmanager
def json_array_output(path: str | Path, **kwargs) -> Iterator[JSONArrayWriter]:
    """Context manager helper: with json_array_output('file.json') as w: w.write(record)"""
    with JSONArrayWriter(path, **kwargs) as writer:
        yield writer


def jsonl_to_json_array(
    jsonl_path: str | Path,
    json_path: str | Path,
    indent: int | None = None,
    chunk_size: int = 10000,
) -> int:
    """
    Convierte archivo JSONL a JSON array único.
    Procesa en chunks para no cargar todo en memoria.
    """
    jsonl_path = Path(jsonl_path)
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with (
        open(jsonl_path, encoding="utf-8") as infile,
        open(json_path, "w", encoding="utf-8") as outfile,
    ):
        outfile.write("[")
        first = True

        chunk = []
        for line in infile:
            line = line.strip()
            if not line:
                continue
            chunk.append(line)
            if len(chunk) >= chunk_size:
                _write_chunk(outfile, chunk, first, indent)
                count += len(chunk)
                first = False
                chunk = []

        if chunk:
            _write_chunk(outfile, chunk, first, indent)
            count += len(chunk)

        outfile.write("\n]")

    return count


def _write_chunk(outfile, chunk: list[str], first: bool, indent: int | None):
    for i, line in enumerate(chunk):
        if not first or i > 0:
            outfile.write(",")
        if indent:
            outfile.write("\n" + " " * indent)
        else:
            if not first and i == 0:
                outfile.write(" ")
        outfile.write(line)


# ---------------------------------------------------------------------------
# Funciones de conveniencia para cada fase
# ---------------------------------------------------------------------------


def write_observations_json(records: list[dict], output_path: str | Path) -> int:
    """Escribe observations.json (array único)."""
    with JSONArrayWriter(output_path, indent=2) as w:
        w.write_batch(records)
    return w.count


def write_cell_day_json(records: list[dict], output_path: str | Path) -> int:
    """Escribe cell_day.json (array único)."""
    with JSONArrayWriter(output_path, indent=2) as w:
        w.write_batch(records)
    return w.count


def write_validated_cell_day_json(records: list[dict], output_path: str | Path) -> int:
    """Escribe validated_cell_day.json (array único)."""
    with JSONArrayWriter(output_path, indent=2) as w:
        w.write_batch(records)
    return w.count


def write_manifest_json(manifest: dict, output_path: str | Path) -> None:
    """Escribe manifest.json (objeto único, no array)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def convert_all_jsonl_to_json(output_dir: str | Path) -> dict[str, int]:
    """
    Convierte todos los .jsonl en output_dir a .json (array único).
    Devuelve dict con conteos por archivo.
    """
    output_dir = Path(output_dir)
    results = {}

    for jsonl_file in output_dir.glob("*.jsonl"):
        json_file = jsonl_file.with_suffix(".json")
        count = jsonl_to_json_array(jsonl_file, json_file, indent=2)
        results[jsonl_file.name] = count
        print(f"  {jsonl_file.name} -> {json_file.name} ({count} records)")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Convierte JSONL a JSON array único")
    p.add_argument("input", type=Path, help="Archivo .jsonl o directorio")
    p.add_argument("--output", type=Path, help="Archivo .json salida (si input es archivo)")
    p.add_argument("--indent", type=int, default=2)
    p.add_argument("--chunk-size", type=int, default=10000)
    args = p.parse_args()

    input_path = Path(args.input)
    if input_path.is_dir():
        results = convert_all_jsonl_to_json(input_path)
        print(f"Total convertidos: {sum(results.values())} registros en {len(results)} archivos")
    else:
        out = args.output or input_path.with_suffix(".json")
        count = jsonl_to_json_array(input_path, out, indent=args.indent, chunk_size=args.chunk_size)
        print(f"Convertido: {count} registros -> {out}")
