import json
import shlex
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from app.notifications.base import MessagePayload, NotificationResult
from app.services.qq_agent_mail_service import parse_recipients, send_qq_agent_mail


def _truncate_error(error: str, max_length: int = 200) -> str:
    return " ".join(error.split())[:max_length]


def _format_weixin_message(payload: MessagePayload) -> str:
    weixin_body = getattr(payload, "weixin_body", None)
    if isinstance(weixin_body, str) and weixin_body.strip():
        return weixin_body.strip()
    title = payload.title.strip()
    body = payload.body.strip() if payload.body else ""
    if title and body:
        return f"{title}\n\n{body}"
    return title or body


def _is_digest_payload(payload: MessagePayload) -> bool:
    from app.digests.types import DigestMessagePayload

    return isinstance(payload, DigestMessagePayload)


def _render_weixin_digest_image(payload: MessagePayload, directory: str) -> Path:
    from app.digests.image import render_digest_jpeg

    image_path = Path(directory) / f"digest-{uuid4().hex}.jpg"
    return render_digest_jpeg(payload, image_path)  # type: ignore[arg-type]


@dataclass(frozen=True)
class QqAgentMailNotifier:
    outlet_id: str
    recipients: str | None
    command: str
    timeout_seconds: float
    channel: str = "email"

    def send(self, payload: MessagePayload) -> NotificationResult:
        html_body = getattr(payload, "html_body", None)
        body_format = "html" if isinstance(html_body, str) and html_body.strip() else "plain"
        body = html_body if body_format == "html" else payload.message_body
        result = send_qq_agent_mail(
            recipients=parse_recipients(self.recipients),
            subject=payload.title,
            body=body,
            body_format=body_format,
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

    def send(self, payload: MessagePayload) -> NotificationResult:
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
            _format_weixin_message(payload),
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


@dataclass(frozen=True)
class HermesHttpNotifier:
    outlet_id: str
    target: str | None
    url: str | None
    timeout_seconds: float
    image_directory: str | None = None
    channel: str = "weixin"

    def send(self, payload: MessagePayload) -> NotificationResult:
        if not self.target:
            return NotificationResult(ok=False, error="hermes_weixin_target_not_configured")
        if not self.url:
            return NotificationResult(ok=False, error="hermes_bridge_url_not_configured")

        media_path: Path | None = None
        message = _format_weixin_message(payload)
        if self.image_directory and _is_digest_payload(payload):
            try:
                media_path = _render_weixin_digest_image(payload, self.image_directory)
                message = ""
            except Exception:
                # Preserve a single-message Weixin fallback if image rendering is unavailable.
                message = message[:1800]

        request_json = {
            "to": self.target,
            "message": message,
        }
        if media_path is not None:
            request_json["media_name"] = media_path.name
        try:
            response = httpx.post(
                self.url,
                json=request_json,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException:
            return NotificationResult(ok=False, error="hermes_http_timeout")
        except httpx.HTTPError as exc:
            return NotificationResult(ok=False, error=_truncate_error(str(exc)))
        finally:
            if media_path is not None:
                with suppress(OSError):
                    media_path.unlink()

        output = response.text.strip()
        try:
            payload_json = response.json() if output else {}
        except ValueError:
            return NotificationResult(ok=False, error="hermes_http_invalid_response")

        if response.status_code >= 400:
            error = payload_json.get("error") or output or f"hermes_http_status_{response.status_code}"
            return NotificationResult(ok=False, error=_truncate_error(str(error)))
        if payload_json.get("error"):
            return NotificationResult(ok=False, error=_truncate_error(str(payload_json["error"])))
        if payload_json.get("success") or payload_json.get("skipped"):
            return NotificationResult(ok=True)
        return NotificationResult(ok=False, error="hermes_http_not_successful")
