import subprocess
from datetime import datetime
from types import SimpleNamespace

import httpx

from app.digests.types import DigestMessagePayload, DigestSelectedItem
from app.notifications.base import NotificationPayload
from app.notifications.notifiers import HermesHttpNotifier, HermesSendNotifier, QqAgentMailNotifier
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


def _title_only_payload() -> NotificationPayload:
    return NotificationPayload(
        event_id="event-1",
        title="Policy update",
        body=None,
        priority="p2",
        instrument_id=None,
        dedupe_key="policy_change:None:now",
    )


def _digest_payload() -> DigestMessagePayload:
    return DigestMessagePayload(
        title="WorldNet 重要事项日报",
        body="时间窗口：2026-07-08T00:00Z - 2026-07-09T00:00Z\n\n总摘要。",
        window_start=datetime(2026, 7, 8, 0, 0),
        window_end=datetime(2026, 7, 9, 0, 0),
        summary="总摘要。",
        items=[
            DigestSelectedItem(
                event_id="event-1",
                rank=1,
                priority="p2",
                title="油价上涨",
                summary="布伦特原油价格上涨，能源板块波动加大。",
            ),
            DigestSelectedItem(
                event_id="event-2",
                rank=2,
                priority="p3",
                title="AI 产业更新",
                summary="算力基础设施需求保持高位。",
            ),
        ],
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
    assert calls[0][calls[0].index("--body-format") + 1] == "plain"
    assert calls[1][-2:] == ["--confirmation-token", "ctk_1"]


def test_qq_agent_mail_notifier_sends_digest_as_html(monkeypatch):
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

    result = notifier.send(_digest_payload())

    assert result.ok is True
    assert calls[0][calls[0].index("--body-format") + 1] == "html"
    body = calls[0][calls[0].index("--body") + 1]
    assert "<html>" in body
    assert "事件 ID" not in body
    assert "2026-07-08T00:00Z" in body
    assert "1. [P2] 油价上涨" in body
    assert 'class="rank"' not in body
    assert 'class="priority"' not in body


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


def test_hermes_send_notifier_sends_title_only_as_single_message(monkeypatch):
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

    result = notifier.send(_title_only_payload())

    assert result.ok is True
    assert calls[0][-1] == "Policy update"


def test_hermes_send_notifier_sends_digest_titles_and_summaries(monkeypatch):
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

    result = notifier.send(_digest_payload())

    assert result.ok is True
    message = calls[0][-1]
    assert "布伦特原油价格上涨" in message
    assert "1. [P2] 油价上涨" in message
    assert "2. [P3] AI 产业更新" in message
    assert "事件 ID" not in message
    assert "event-1" not in message


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


def test_hermes_http_notifier_sends_message(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr("app.notifications.notifiers.httpx.post", fake_post)
    notifier = HermesHttpNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        url="http://host.docker.internal:15307/send",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is True
    assert calls == [
        (
            "http://host.docker.internal:15307/send",
            {
                "json": {
                    "to": "weixin:user",
                    "message": "Policy update\n\nA policy update was published.",
                },
                "timeout": 30,
            },
        )
    ]


def test_hermes_http_notifier_sends_title_only_as_single_message(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr("app.notifications.notifiers.httpx.post", fake_post)
    notifier = HermesHttpNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        url="http://host.docker.internal:15307/send",
        timeout_seconds=30,
    )

    result = notifier.send(_title_only_payload())

    assert result.ok is True
    assert calls[0][1]["json"]["message"] == "Policy update"


def test_hermes_http_notifier_sends_digest_titles_and_summaries(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr("app.notifications.notifiers.httpx.post", fake_post)
    notifier = HermesHttpNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        url="http://host.docker.internal:15307/send",
        timeout_seconds=30,
    )

    result = notifier.send(_digest_payload())

    assert result.ok is True
    message = calls[0][1]["json"]["message"]
    assert "算力基础设施需求保持高位" in message
    assert "2. [P3] AI 产业更新" in message
    assert "事件 ID" not in message


def test_hermes_http_notifier_sends_digest_as_one_image(monkeypatch, tmp_path):
    calls = []

    def fake_render(payload, directory):
        output_path = tmp_path / "digest-test.jpg"
        output_path.write_bytes(b"jpeg-data")
        return output_path

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        media_path = tmp_path / kwargs["json"]["media_name"]
        assert media_path.read_bytes() == b"jpeg-data"
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr("app.notifications.notifiers._render_weixin_digest_image", fake_render)
    monkeypatch.setattr("app.notifications.notifiers.httpx.post", fake_post)
    notifier = HermesHttpNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        url="http://host.docker.internal:15307/send",
        timeout_seconds=30,
        image_directory=str(tmp_path),
    )

    result = notifier.send(_digest_payload())

    assert result.ok is True
    assert calls[0][1]["json"]["message"] == ""
    assert calls[0][1]["json"]["media_name"].endswith(".jpg")
    assert list(tmp_path.iterdir()) == []


def test_hermes_http_notifier_falls_back_to_one_short_message(monkeypatch, tmp_path):
    calls = []

    def failed_render(*args, **kwargs):
        raise RuntimeError("render failed")

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr("app.notifications.notifiers._render_weixin_digest_image", failed_render)
    monkeypatch.setattr("app.notifications.notifiers.httpx.post", fake_post)
    notifier = HermesHttpNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        url="http://host.docker.internal:15307/send",
        timeout_seconds=30,
        image_directory=str(tmp_path),
    )

    result = notifier.send(_digest_payload())

    assert result.ok is True
    assert "media_name" not in calls[0][1]["json"]
    assert 0 < len(calls[0][1]["json"]["message"]) <= 1800


def test_hermes_http_notifier_records_error_json(monkeypatch):
    monkeypatch.setattr(
        "app.notifications.notifiers.httpx.post",
        lambda *_, **__: httpx.Response(200, json={"error": "bad target"}),
    )
    notifier = HermesHttpNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        url="http://host.docker.internal:15307/send",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is False
    assert result.error == "bad target"


def test_hermes_http_notifier_records_http_status_error(monkeypatch):
    monkeypatch.setattr(
        "app.notifications.notifiers.httpx.post",
        lambda *_, **__: httpx.Response(403, json={"error": "client_not_allowed"}),
    )
    notifier = HermesHttpNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        url="http://host.docker.internal:15307/send",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is False
    assert result.error == "client_not_allowed"


def test_hermes_http_notifier_records_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "app.notifications.notifiers.httpx.post",
        lambda *_, **__: httpx.Response(200, text="not-json"),
    )
    notifier = HermesHttpNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        url="http://host.docker.internal:15307/send",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is False
    assert result.error == "hermes_http_invalid_response"


def test_hermes_http_notifier_records_timeout(monkeypatch):
    def raise_timeout(*_, **__):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.notifications.notifiers.httpx.post", raise_timeout)
    notifier = HermesHttpNotifier(
        outlet_id="hermes_weixin",
        target="weixin:user",
        url="http://host.docker.internal:15307/send",
        timeout_seconds=30,
    )

    result = notifier.send(_payload())

    assert result.ok is False
    assert result.error == "hermes_http_timeout"
