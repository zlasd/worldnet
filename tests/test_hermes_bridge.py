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


def test_default_media_directory_is_platform_neutral(monkeypatch):
    bridge = _bridge_module()
    monkeypatch.delenv("HERMES_BRIDGE_MEDIA_DIRECTORY", raising=False)

    assert str(bridge._media_root()).endswith("/home/ubuntu/worldnet-data/notification-media")


@pytest.mark.parametrize(
    "target,expected",
    [
        ("qqbot:c2c:user-openid", ("c2c", "user-openid")),
        ("qqbot:group:group-openid", ("group", "group-openid")),
    ],
)
def test_parse_qqbot_target(target, expected):
    assert _bridge_module()._parse_qqbot_target(target) == expected


@pytest.mark.parametrize("target", ["qqbot:channel:id", "qqbot:c2c:", "weixin:user"])
def test_parse_qqbot_target_rejects_unsupported_target(target):
    with pytest.raises(ValueError, match="qqbot_target_invalid"):
        _bridge_module()._parse_qqbot_target(target)


def test_send_qqbot_uploads_and_sends_image(tmp_path, monkeypatch):
    bridge = _bridge_module()
    monkeypatch.setenv("QQ_APP_ID", "app-id")
    monkeypatch.setenv("QQ_CLIENT_SECRET", "secret")
    image = tmp_path / "digest.jpg"
    image.write_bytes(b"jpeg")
    calls = []

    def fake_post(url, payload, token=None):
        calls.append((url, payload, token))
        if url == bridge.QQ_TOKEN_URL:
            return {"access_token": "access-token"}
        if url.endswith("/files"):
            return {"file_info": "uploaded-file"}
        return {"id": "message-id"}

    monkeypatch.setattr(bridge, "_qqbot_post", fake_post)

    result = bridge._send_qqbot("qqbot:c2c:user-openid", "", image)

    assert result["success"] is True
    assert result["message_id"] == "message-id"
    assert calls[1][1]["file_data"] == "anBlZw=="
    assert calls[2][1]["media"] == {"file_info": "uploaded-file"}


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
