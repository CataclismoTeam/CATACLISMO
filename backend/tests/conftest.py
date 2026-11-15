"""Configuración de recolección y marcadores de pytest para CATACLISMO."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_TRAINER_TEST_FILES = frozenset(
    {
        "test_cata_lucia_continual_nrt.py",
        "test_valen_pipeline.py",
    }
)
_TRAINER_MODULES = ("numpy", "pandas", "tensorflow")


def _has_trainer_deps() -> bool:
    return all(importlib.util.find_spec(mod) is not None for mod in _TRAINER_MODULES)


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Omite tests de ML/pipeline cuando no está instalado el extra `[trainer]`."""
    del config
    if collection_path.name in _TRAINER_TEST_FILES and not _has_trainer_deps():
        return True
    return None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Etiqueta los tests de datos y entrenamiento con `trainer`."""
    for item in items:
        if Path(str(item.fspath)).name in _TRAINER_TEST_FILES:
            item.add_marker(pytest.mark.trainer)
