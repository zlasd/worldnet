from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _bridge_module():
    path = Path(__file__).parents[1] / "scripts" / "worldnet-hermes-bridge.py"
    spec = importlib.util.spec_from_file_location("worldnet_hermes_bridge", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_media_path_accepts_file_inside_configured_directory(tmp_path, monkeypatch):
    bridge = _bridge_module()
    monkeypatch.setenv("HERMES_BRIDGE_MEDIA_DIRECTORY", str(tmp_path))
    image = tmp_path / "digest.jpg"
    image.write_bytes(b"jpeg")

    assert bridge._resolve_media_path(image.name) == image.resolve()


@pytest.mark.parametrize(
    "name,error",
    [
        ("../secret.jpg", "media_name_invalid"),
        ("digest.txt", "media_type_not_allowed"),
        ("missing.jpg", "media_not_found"),
    ],
)
def test_resolve_media_path_rejects_unsafe_or_missing_media(tmp_path, monkeypatch, name, error):
    bridge = _bridge_module()
    monkeypatch.setenv("HERMES_BRIDGE_MEDIA_DIRECTORY", str(tmp_path))

    with pytest.raises(ValueError, match=error):
        bridge._resolve_media_path(name)
