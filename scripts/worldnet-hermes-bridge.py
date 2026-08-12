#!/usr/bin/env python3
from __future__ import annotations

import base64
import ipaddress
import json
import os
import subprocess
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_ALLOWED_CIDRS = "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
MAX_BODY_BYTES = 1024 * 1024
MAX_MEDIA_BYTES = 8 * 1024 * 1024
ALLOWED_MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
QQ_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
QQ_API_BASE = "https://api.sgroup.qq.com"


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _allowed_networks() -> list[ipaddress._BaseNetwork]:
    raw = os.environ.get("HERMES_BRIDGE_ALLOWED_CIDRS", DEFAULT_ALLOWED_CIDRS)
    return [ipaddress.ip_network(item.strip()) for item in raw.split(",") if item.strip()]


def _client_allowed(client_host: str) -> bool:
    try:
        client_ip = ipaddress.ip_address(client_host)
    except ValueError:
        return False
    if hasattr(client_ip, "ipv4_mapped") and client_ip.ipv4_mapped:
        client_ip = client_ip.ipv4_mapped
    return any(client_ip in network for network in _allowed_networks())


def _media_root() -> Path:
    return Path(
        os.environ.get(
            "HERMES_BRIDGE_MEDIA_DIRECTORY",
            "/home/ubuntu/worldnet-data/notification-media",
        )
    ).resolve()


def _resolve_media_path(media_name: object) -> Path | None:
    if media_name is None or str(media_name).strip() == "":
        return None
    name = str(media_name).strip()
    if name != Path(name).name:
        raise ValueError("media_name_invalid")
    media_root = _media_root()
    media_path = (media_root / name).resolve()
    if media_path.parent != media_root:
        raise ValueError("media_path_not_allowed")
    if media_path.suffix.lower() not in ALLOWED_MEDIA_SUFFIXES:
        raise ValueError("media_type_not_allowed")
    if not media_path.is_file():
        raise ValueError("media_not_found")
    if media_path.stat().st_size <= 0 or media_path.stat().st_size > MAX_MEDIA_BYTES:
        raise ValueError("media_size_invalid")
    return media_path


def _qqbot_post(url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"QQBot {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout = float(os.environ.get("HERMES_BRIDGE_SEND_TIMEOUT_SECONDS", "30"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"qqbot_http_{exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"qqbot_network_error: {exc.reason}") from exc
    try:
        result = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("qqbot_invalid_response") from exc
    if not isinstance(result, dict):
        raise RuntimeError("qqbot_invalid_response")
    return result


def _parse_qqbot_target(target: str) -> tuple[str, str]:
    parts = target.split(":", 2)
    if len(parts) != 3 or parts[0] != "qqbot" or parts[1] not in {"c2c", "group"}:
        raise ValueError("qqbot_target_invalid")
    target_id = parts[2].strip()
    if not target_id or any(character in target_id for character in "/?#"):
        raise ValueError("qqbot_target_invalid")
    return parts[1], target_id


def _send_qqbot(target: str, message: str, media_path: Path | None) -> dict[str, Any]:
    scope, target_id = _parse_qqbot_target(target)
    app_id = os.environ.get("QQ_APP_ID", "").strip()
    client_secret = os.environ.get("QQ_CLIENT_SECRET", "").strip()
    if not app_id or not client_secret:
        raise ValueError("qqbot_credentials_not_configured")

    token_result = _qqbot_post(
        os.environ.get("QQ_TOKEN_URL", QQ_TOKEN_URL),
        {"appId": app_id, "clientSecret": client_secret},
    )
    access_token = str(token_result.get("access_token") or "")
    if not access_token:
        raise RuntimeError("qqbot_access_token_missing")

    collection = "users" if scope == "c2c" else "groups"
    api_base = os.environ.get("QQ_API_BASE", QQ_API_BASE).rstrip("/")
    if media_path is not None:
        encoded = base64.b64encode(media_path.read_bytes()).decode("ascii")
        upload = _qqbot_post(
            f"{api_base}/v2/{collection}/{target_id}/files",
            {"file_type": 1, "srv_send_msg": False, "file_data": encoded},
            access_token,
        )
        file_info = upload.get("file_info") or (upload.get("data") or {}).get("file_info")
        if not file_info:
            raise RuntimeError("qqbot_media_upload_missing_file_info")
        send_payload: dict[str, Any] = {
            "msg_type": 7,
            "media": {"file_info": file_info},
            "msg_seq": 1,
        }
        if message.strip():
            send_payload["content"] = message.strip()[:4000]
    else:
        send_payload = {"msg_type": 0, "content": message.strip()[:4000], "msg_seq": 1}
    sent = _qqbot_post(
        f"{api_base}/v2/{collection}/{target_id}/messages",
        send_payload,
        access_token,
    )
    return {
        "success": True,
        "platform": "qqbot",
        "chat_id": target_id,
        "message_id": sent.get("id"),
    }


class HermesBridgeHandler(BaseHTTPRequestHandler):
    server_version = "WorldNetHermesBridge/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("HERMES_BRIDGE_LOG_REQUESTS", "").lower() in {"1", "true", "yes"}:
            super().log_message(format, *args)

    def _reject_external_clients(self) -> bool:
        client_host = self.client_address[0]
        if _client_allowed(client_host):
            return False
        _json_response(self, 403, {"error": "client_not_allowed"})
        return True

    def do_GET(self) -> None:
        if self._reject_external_clients():
            return
        if self.path != "/health":
            _json_response(self, 404, {"error": "not_found"})
            return
        _json_response(self, 200, {"success": True})

    def do_POST(self) -> None:
        if self._reject_external_clients():
            return
        if self.path != "/send":
            _json_response(self, 404, {"error": "not_found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            _json_response(self, 400, {"error": "invalid_content_length"})
            return
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            _json_response(self, 413, {"error": "invalid_body_size"})
            return

        try:
            request_body = self.rfile.read(content_length).decode("utf-8")
            request_json = json.loads(request_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _json_response(self, 400, {"error": "invalid_json"})
            return

        target = str(request_json.get("to") or os.environ.get("HERMES_DEFAULT_TARGET") or "")
        message = str(request_json.get("message") or "")
        if not target:
            _json_response(self, 400, {"error": "target_not_configured"})
            return
        try:
            media_path = _resolve_media_path(request_json.get("media_name"))
        except ValueError as exc:
            _json_response(self, 400, {"error": str(exc)})
            return
        if not message.strip() and media_path is None:
            _json_response(self, 400, {"error": "message_empty"})
            return

        if target.startswith("qqbot:"):
            try:
                response_json = _send_qqbot(target, message, media_path)
            except ValueError as exc:
                _json_response(self, 400, {"error": str(exc)})
                return
            except RuntimeError as exc:
                _json_response(self, 502, {"error": str(exc)})
                return
            _json_response(self, 200, response_json)
            return

        hermes_message = message.strip()
        if media_path is not None:
            media_tag = f"MEDIA:{media_path}"
            hermes_message = f"{hermes_message}\n{media_tag}" if hermes_message else media_tag

        hermes_bin = os.environ.get("HERMES_BIN", "/home/ubuntu/.local/bin/hermes")
        timeout_seconds = float(os.environ.get("HERMES_BRIDGE_SEND_TIMEOUT_SECONDS", "30"))
        try:
            completed = subprocess.run(
                [hermes_bin, "send", "--to", target, "--json", hermes_message],
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            _json_response(self, 500, {"error": "hermes_bin_not_found"})
            return
        except subprocess.TimeoutExpired:
            _json_response(self, 504, {"error": "hermes_send_timeout"})
            return

        output = completed.stdout.strip()
        if completed.returncode != 0:
            error = (completed.stderr or output or "hermes_send_failed").strip()
            _json_response(self, 502, {"error": error})
            return

        try:
            response_json = json.loads(output) if output else {"success": True}
        except json.JSONDecodeError:
            _json_response(self, 502, {"error": "hermes_invalid_response"})
            return
        _json_response(self, 200, response_json)


def main() -> None:
    host = os.environ.get("HERMES_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("HERMES_BRIDGE_PORT", "15307"))
    server = ThreadingHTTPServer((host, port), HermesBridgeHandler)
    print(f"worldnet-hermes-bridge listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
