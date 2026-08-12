from app.notifications.config import NotificationOutletDefinition
from app.notifications.factory import build_notifier
from app.notifications.notifiers import HermesHttpNotifier


def test_qqbot_http_outlet_uses_qqbot_target(monkeypatch):
    monkeypatch.setattr("app.notifications.factory.settings.hermes_qqbot_target", "qqbot:c2c:u1")
    monkeypatch.setattr("app.notifications.factory.settings.hermes_weixin_target", "weixin:u2")

    notifier = build_notifier(
        NotificationOutletDefinition(
            outlet_id="hermes_qqbot",
            type="hermes_http",
            channel="qqbot",
        )
    )

    assert isinstance(notifier, HermesHttpNotifier)
    assert notifier.target == "qqbot:c2c:u1"
    assert notifier.channel == "qqbot"


def test_explicit_hermes_target_takes_precedence(monkeypatch):
    monkeypatch.setattr("app.notifications.factory.settings.hermes_qqbot_target", "qqbot:c2c:u1")

    notifier = build_notifier(
        NotificationOutletDefinition(
            outlet_id="hermes_qqbot",
            type="hermes_http",
            channel="qqbot",
            target="qqbot:group:g1",
        )
    )

    assert isinstance(notifier, HermesHttpNotifier)
    assert notifier.target == "qqbot:group:g1"
