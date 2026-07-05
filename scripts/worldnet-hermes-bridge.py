#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_ALLOWED_CIDRS = "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
MAX_BODY_BYTES = 1024 * 1024


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

        target = str(request_json.get("to") or os.environ.get("HERMES_WEIXIN_TARGET") or "")
        message = str(request_json.get("message") or "")
        if not target:
            _json_response(self, 400, {"error": "target_not_configured"})
            return
        if not message.strip():
            _json_response(self, 400, {"error": "message_empty"})
            return

        hermes_bin = os.environ.get("HERMES_BIN", "/home/ubuntu/.local/bin/hermes")
        timeout_seconds = float(os.environ.get("HERMES_BRIDGE_SEND_TIMEOUT_SECONDS", "30"))
        try:
            completed = subprocess.run(
                [hermes_bin, "send", "--to", target, "--json", message],
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
