from app.core.config import settings
from app.notifications.base import Notifier
from app.notifications.config import NotificationOutletDefinition, load_notification_outlets
from app.notifications.notifiers import HermesHttpNotifier, HermesSendNotifier, QqAgentMailNotifier


def build_notifier(definition: NotificationOutletDefinition) -> Notifier:
    if definition.type == "qq_agent_mail":
        return QqAgentMailNotifier(
            outlet_id=definition.outlet_id,
            channel=definition.channel or "email",
            recipients=definition.recipients or settings.qq_agent_mail_to,
            command=definition.command or settings.qq_agent_mail_cli_command,
            timeout_seconds=definition.timeout_seconds or settings.qq_agent_mail_timeout_seconds,
        )

    if definition.type == "hermes_send":
        return HermesSendNotifier(
            outlet_id=definition.outlet_id,
            channel=definition.channel or "weixin",
            target=definition.target or settings.hermes_weixin_target,
            command=definition.command or settings.hermes_send_command,
            timeout_seconds=definition.timeout_seconds or settings.hermes_send_timeout_seconds,
        )

    if definition.type == "hermes_http":
        return HermesHttpNotifier(
            outlet_id=definition.outlet_id,
            channel=definition.channel or "weixin",
            target=definition.target or settings.hermes_weixin_target,
            url=definition.url or settings.hermes_bridge_url,
            timeout_seconds=definition.timeout_seconds or settings.hermes_send_timeout_seconds,
        )

    raise ValueError(f"Unsupported notification outlet type: {definition.type}")


def build_notifiers(
    default_dir: str | None = None,
    custom_dir: str | None = None,
) -> list[Notifier]:
    return [
        build_notifier(definition)
        for definition in load_notification_outlets(default_dir=default_dir, custom_dir=custom_dir)
    ]
