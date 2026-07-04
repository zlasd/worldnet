from pathlib import Path

import pytest

from app.notifications.config import load_notification_outlets


def _write_config_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_load_notification_outlets_merges_default_and_custom_directories(tmp_path):
    default_dir = tmp_path / "default"
    custom_dir = tmp_path / "custom"

    _write_config_file(
        default_dir / "builtins.yaml",
        """
        outlets:
          - outlet_id: qq_agent_mail
            type: qq_agent_mail
            enabled: false
            channel: email
          - outlet_id: hermes_weixin
            type: hermes_send
            enabled: true
            channel: weixin
            target: weixin:old
        """,
    )
    _write_config_file(
        custom_dir / "overrides.yaml",
        """
        outlets:
          - outlet_id: qq_agent_mail
            enabled: true
          - outlet_id: hermes_weixin
            target: weixin:new
        """,
    )

    outlets = load_notification_outlets(default_dir=default_dir, custom_dir=custom_dir)

    assert [outlet.outlet_id for outlet in outlets] == ["hermes_weixin", "qq_agent_mail"]
    assert outlets[0].target == "weixin:new"
    assert outlets[1].type == "qq_agent_mail"
    assert outlets[1].channel == "email"


def test_load_notification_outlets_skips_disabled_custom_override(tmp_path):
    default_dir = tmp_path / "default"
    custom_dir = tmp_path / "custom"

    _write_config_file(
        default_dir / "builtins.yaml",
        """
        outlets:
          - outlet_id: qq_agent_mail
            type: qq_agent_mail
            enabled: true
        """,
    )
    _write_config_file(
        custom_dir / "overrides.yaml",
        """
        outlets:
          - outlet_id: qq_agent_mail
            enabled: false
        """,
    )

    assert load_notification_outlets(default_dir=default_dir, custom_dir=custom_dir) == []


def test_load_notification_outlets_validates_outlet_id(tmp_path):
    default_dir = tmp_path / "default"
    _write_config_file(
        default_dir / "invalid.yaml",
        """
        outlets:
          - type: qq_agent_mail
            enabled: true
        """,
    )

    with pytest.raises(ValueError, match="valid outlet_id"):
        load_notification_outlets(default_dir=default_dir, custom_dir=tmp_path / "custom")


def test_load_notification_outlets_validates_timeout(tmp_path):
    default_dir = tmp_path / "default"
    _write_config_file(
        default_dir / "invalid.yaml",
        """
        outlets:
          - outlet_id: qq_agent_mail
            type: qq_agent_mail
            timeout_seconds: 0
        """,
    )

    with pytest.raises(ValueError, match="greater than 0"):
        load_notification_outlets(default_dir=default_dir, custom_dir=tmp_path / "custom")
