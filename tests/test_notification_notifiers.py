import subprocess
from types import SimpleNamespace

from app.notifications.base import NotificationPayload
from app.notifications.notifiers import HermesSendNotifier, QqAgentMailNotifier
from app.services.qq_agent_mail_service import parse_recipients


def _payload() -> NotificationPayload:
    return NotificationPayload(
        event_id="event-1",
        title="Policy update",
        body="A policy update was published.",
        priority="p2",
        instrument_id=None,
        dedupe_key="policy_change:None:now",
    )


def test_parse_recipients_accepts_commas_and_semicolons():
    assert parse_recipients("a@example.com, b@example.com;c@example.com") == [
        "a@example.com",
        "b@example.com",
        "c@example.com",
    ]


def test_qq_agent_mail_notifier_completes_confirmation_flow(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "--confirmation-token" in args:
            return SimpleNamespace(returncode=0, stdout='{"queued": true}', stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout='{"data":{"confirmation_required":true,"confirmation_token":"ctk_1"}}',
            stderr="",
        )

    monkeypatch.setattr("app.services.qq_agent_mail_service.subprocess.run", fake_run)

    notifier = QqAgentMailNotifier(
        outlet_id="qq_agent_mail",
        recipients="desk@example.com",
        command="agently-cli",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is True
    assert len(calls) == 2
    assert calls[0][:3] == ["agently-cli", "message", "+send"]
    assert calls[1][-2:] == ["--confirmation-token", "ctk_1"]


def test_qq_agent_mail_notifier_records_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "app.services.qq_agent_mail_service.subprocess.run",
        lambda *_, **__: SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    )
    notifier = QqAgentMailNotifier(
        outlet_id="qq_agent_mail",
        recipients="desk@example.com",
        command="agently-cli",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is False
    assert result.error == "qq_agent_mail_invalid_confirmation_response"


def test_qq_agent_mail_notifier_records_timeout(monkeypatch):
    def raise_timeout(*_, **__):
        raise subprocess.TimeoutExpired(cmd="agently-cli", timeout=30)

    monkeypatch.setattr("app.services.qq_agent_mail_service.subprocess.run", raise_timeout)
    notifier = QqAgentMailNotifier(
        outlet_id="qq_agent_mail",
        recipients="desk@example.com",
        command="agently-cli",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is False
    assert result.error == "agently_cli_timeout"


def test_hermes_send_notifier_sends_message(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='{"success": true}', stderr="")

    monkeypatch.setattr("app.notifications.notifiers.subprocess.run", fake_run)
    notifier = HermesSendNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        command="/usr/local/bin/worldnet-hermes-send",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is True
    assert calls == [
        [
            "/usr/local/bin/worldnet-hermes-send",
            "--to",
            "weixin:user",
            "--json",
            "Policy update\n\nA policy update was published.",
        ]
    ]


def test_hermes_send_notifier_records_error_json(monkeypatch):
    monkeypatch.setattr(
        "app.notifications.notifiers.subprocess.run",
        lambda *_, **__: SimpleNamespace(returncode=0, stdout='{"error": "bad target"}', stderr=""),
    )
    notifier = HermesSendNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        command="worldnet-hermes-send",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is False
    assert result.error == "bad target"


def test_hermes_send_notifier_records_timeout(monkeypatch):
    def raise_timeout(*_, **__):
        raise subprocess.TimeoutExpired(cmd="worldnet-hermes-send", timeout=30)

    monkeypatch.setattr("app.notifications.notifiers.subprocess.run", raise_timeout)
    notifier = HermesSendNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        command="worldnet-hermes-send",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is False
    assert result.error == "hermes_send_timeout"
