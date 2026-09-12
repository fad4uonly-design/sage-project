from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest
from model_integration_engine.sandbox.runtime_gateway import (
    RuntimeGatewayConfig,
    RuntimeGatewayHandler,
)


class _GatewayServer(ThreadingHTTPServer):
    allow_reuse_address = True


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/chat":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        payload = json.loads(body.decode("utf-8"))
        response = {
            "ok": True,
            "model": payload["model"],
            "path": self.path,
        }
        raw = json.dumps(response).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, message: str, *args: object) -> None:
        return


def _server(
    handler: type[BaseHTTPRequestHandler],
    *,
    upstream: str | None = None,
):
    server = _GatewayServer(("127.0.0.1", 0), handler)

    if upstream is not None:
        server.mie_gateway_config = RuntimeGatewayConfig(
            upstream_endpoint=upstream,
            allowed_paths=("/api/chat",),
        )

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_gateway_rejects_unapproved_route() -> None:
    server, thread = _server(
        RuntimeGatewayHandler,
        upstream="http://127.0.0.1:1",
    )
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/version",
            method="GET",
        )

        with pytest.raises(Exception) as exc:
            urlopen(request, timeout=2)

        assert getattr(exc.value, "code", None) == 404
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_gateway_forwards_approved_chat_route() -> None:
    upstream, upstream_thread = _server(_FakeUpstreamHandler)
    gateway, gateway_thread = _server(
        RuntimeGatewayHandler,
        upstream=f"http://127.0.0.1:{upstream.server_port}",
    )

    try:
        body = json.dumps(
            {
                "model": "qwen3:4b",
                "messages": [
                    {"role": "user", "content": "gateway-test"},
                ],
                "stream": False,
            }
        ).encode("utf-8")

        request = Request(
            f"http://127.0.0.1:{gateway.server_port}/api/chat",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))

        assert response.status == 200
        assert payload == {
            "ok": True,
            "model": "qwen3:4b",
            "path": "/api/chat",
        }
    finally:
        gateway.shutdown()
        gateway_thread.join(timeout=2)
        gateway.server_close()

        upstream.shutdown()
        upstream_thread.join(timeout=2)
        upstream.server_close()


def test_gateway_config_rejects_non_absolute_upstream() -> None:
    with pytest.raises(ValueError):
        RuntimeGatewayConfig("127.0.0.1:11434")
