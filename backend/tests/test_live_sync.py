"""Sincronización de los resultados del ciclo en vivo publicados por GitHub Actions."""

import json

from app.live_sync import sync_once


def test_sync_escribe_solo_lo_que_cambia(tmp_path):
    files = {"a.json": str(tmp_path / "a.json"), "b.json": str(tmp_path / "sub" / "b.json")}
    remote = {"https://x/a.json": b'{"v": 1}', "https://x/b.json": b'{"v": 2}'}

    assert sync_once("https://x/", remote.get, files) == ["a.json", "b.json"]
    assert json.loads((tmp_path / "sub" / "b.json").read_text()) == {"v": 2}
    # Sin cambios en remoto: no se reescribe nada
    assert sync_once("https://x", remote.get, files) == []
    remote["https://x/a.json"] = b'{"v": 3}'
    assert sync_once("https://x", remote.get, files) == ["a.json"]


def test_sync_ignora_lo_que_falta_o_no_es_json(tmp_path):
    files = {"a.json": str(tmp_path / "a.json"), "b.json": str(tmp_path / "b.json")}
    remote = {"https://x/a.json": b"<html>no</html>"}

    assert sync_once("https://x", remote.get, files) == []
    assert not (tmp_path / "a.json").exists()
    assert not (tmp_path / "b.json").exists()


def test_live_data_url_solo_en_render(monkeypatch):
    from app.config import LIVE_DATA_RELEASE, Settings

    monkeypatch.delenv("LIVE_DATA_URL", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    assert Settings(_env_file=None).live_data_url == ""
    monkeypatch.setenv("RENDER", "true")
    assert Settings(_env_file=None).live_data_url == LIVE_DATA_RELEASE
