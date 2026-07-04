import json
import shlex
import subprocess
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class MailSendResult:
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class CliResult:
    ok: bool
    output: str = ""
    error: str | None = None


def parse_recipients(raw_recipients: str | None) -> list[str]:
    if not raw_recipients:
        return []
    return [
        recipient.strip()
        for recipient in raw_recipients.replace(";", ",").split(",")
        if recipient.strip()
    ]


def build_notification_email_body(title: str, body: str | None) -> str:
    content = body.strip() if body else "No summary provided."
    return f"{title}\n\n{content}"


def send_qq_agent_mail(
    *,
    recipients: list[str],
    subject: str,
    body: str,
) -> MailSendResult:
    if not recipients:
        return MailSendResult(ok=False, error="qq_agent_mail_to_not_configured")

    command = shlex.split(settings.qq_agent_mail_cli_command)
    if not command:
        return MailSendResult(ok=False, error="qq_agent_mail_cli_command_not_configured")

    base_args = [
        *command,
        "message",
        "+send",
        "--subject",
        subject,
        "--body",
        body,
        "--body-format",
        "plain",
    ]
    for recipient in recipients:
        base_args.extend(["--to", recipient])

    first_result = _run_cli(base_args)
    if not first_result.ok:
        return MailSendResult(ok=False, error=first_result.error)

    first_payload = _parse_cli_json(first_result.output)
    if first_payload is None:
        return MailSendResult(ok=False, error="qq_agent_mail_invalid_confirmation_response")

    data = first_payload.get("data") or {}
    if data.get("confirmation_required"):
        confirmation_token = data.get("confirmation_token")
        if not confirmation_token:
            return MailSendResult(ok=False, error="qq_agent_mail_confirmation_token_missing")
        second_result = _run_cli([*base_args, "--confirmation-token", confirmation_token])
        if not second_result.ok:
            return MailSendResult(ok=False, error=second_result.error)
        second_payload = _parse_cli_json(second_result.output)
        if second_payload is None:
            return MailSendResult(ok=False, error="qq_agent_mail_invalid_send_response")
        return _mail_result_from_payload(second_payload)

    return _mail_result_from_payload(first_payload)


def _run_cli(args: list[str]) -> CliResult:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=settings.qq_agent_mail_timeout_seconds,
        )
    except FileNotFoundError:
        return CliResult(ok=False, error="agently_cli_not_found")
    except subprocess.TimeoutExpired:
        return CliResult(ok=False, error="agently_cli_timeout")

    output = completed.stdout.strip()
    if completed.returncode != 0:
        error = (completed.stderr or output or "agently_cli_failed").strip()
        return CliResult(ok=False, error=_truncate_error(error))

    return CliResult(ok=True, output=output)


def _parse_cli_json(raw_output: str | None) -> dict | None:
    if not raw_output:
        return None
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _truncate_error(error: str, max_length: int = 200) -> str:
    error = " ".join(error.split())
    return error[:max_length]


def _mail_result_from_payload(payload: dict) -> MailSendResult:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if payload.get("queued") or data.get("queued") or payload.get("ok"):
        return MailSendResult(ok=True)
    return MailSendResult(ok=False, error="qq_agent_mail_send_not_queued")
