import json
import shlex
import subprocess
from dataclasses import dataclass

from app.notifications.base import NotificationPayload, NotificationResult
from app.services.qq_agent_mail_service import parse_recipients, send_qq_agent_mail


def _truncate_error(error: str, max_length: int = 200) -> str:
    return " ".join(error.split())[:max_length]


@dataclass(frozen=True)
class QqAgentMailNotifier:
    outlet_id: str
    recipients: str | None
    command: str
    timeout_seconds: float
    channel: str = "email"

    def send(self, payload: NotificationPayload) -> NotificationResult:
        result = send_qq_agent_mail(
            recipients=parse_recipients(self.recipients),
            subject=payload.title,
            body=payload.message_body,
            command=self.command,
            timeout_seconds=self.timeout_seconds,
        )
        return NotificationResult(ok=result.ok, error=result.error)


@dataclass(frozen=True)
class HermesSendNotifier:
    outlet_id: str
    target: str | None
    command: str
    timeout_seconds: float
    channel: str = "weixin"

    def send(self, payload: NotificationPayload) -> NotificationResult:
        if not self.target:
            return NotificationResult(ok=False, error="hermes_weixin_target_not_configured")

        command = shlex.split(self.command)
        if not command:
            return NotificationResult(ok=False, error="hermes_send_command_not_configured")

        args = [
            *command,
            "--to",
            self.target,
            "--json",
            payload.message_body,
        ]
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                check=False,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError:
            return NotificationResult(ok=False, error="hermes_send_command_not_found")
        except subprocess.TimeoutExpired:
            return NotificationResult(ok=False, error="hermes_send_timeout")

        output = completed.stdout.strip()
        if completed.returncode != 0:
            error = (completed.stderr or output or "hermes_send_failed").strip()
            return NotificationResult(ok=False, error=_truncate_error(error))

        try:
            payload_json = json.loads(output) if output else {}
        except json.JSONDecodeError:
            return NotificationResult(ok=False, error="hermes_send_invalid_response")

        if payload_json.get("error"):
            return NotificationResult(ok=False, error=_truncate_error(str(payload_json["error"])))
        if payload_json.get("success") or payload_json.get("skipped"):
            return NotificationResult(ok=True)
        return NotificationResult(ok=False, error="hermes_send_not_successful")
