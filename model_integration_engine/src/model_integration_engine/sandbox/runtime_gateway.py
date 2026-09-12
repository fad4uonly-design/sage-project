"""Fixed-route runtime gateway for sandboxed behavioral probes."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class RuntimeGatewayConfig:
    upstream_endpoint: str
    allowed_paths: tuple[str, ...] = ("/api/chat", "/api/version")

    def __post_init__(self) -> None:
        endpoint = self.upstream_endpoint.strip().rstrip("/")
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "upstream_endpoint must be an absolute http(s) URL"
            )
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError(
                "upstream_endpoint must not include a path, query, or fragment"
            )
        object.__setattr__(self, "upstream_endpoint", endpoint)

        for path in self.allowed_paths:
            if not path.startswith("/") or "?" in path or "#" in path:
                raise ValueError("allowed paths must be absolute route paths")


class RuntimeGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MIE-Runtime-Gateway/0.1.0"

    def _config(self) -> RuntimeGatewayConfig:
        value = getattr(self.server, "mie_gateway_config", None)
        if not isinstance(value, RuntimeGatewayConfig):
            raise RuntimeError("gateway configuration is unavailable")
        return value

    def _reject(self, status: int, message: str) -> None:
        body = json.dumps(
            {"error": message},
            separators=(",", ":"),
        ).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _forward(self) -> None:
        config = self._config()
        path = urlsplit(self.path).path

        if path not in config.allowed_paths:
            self._reject(404, "route is not permitted")
            return

        if self.command not in {"GET", "POST"}:
            self._reject(405, "method is not permitted")
            return

        body = None

        if self.command == "POST":
            raw_length = self.headers.get("Content-Length")

            try:
                length = int(raw_length or "0")
            except ValueError:
                self._reject(400, "invalid content length")
                return

            if length < 0 or length > 16 * 1024 * 1024:
                self._reject(413, "request body too large")
                return

            body = self.rfile.read(length)

        upstream_url = f"{config.upstream_endpoint}{path}"

        request = urllib.request.Request(
            upstream_url,
            data=body,
            method=self.command,
            headers={
                "Content-Type": self.headers.get(
                    "Content-Type",
                    "application/json",
                ),
                "Accept": self.headers.get(
                    "Accept",
                    "application/json",
                ),
                "User-Agent": "MIE-Runtime-Gateway/0.1.0",
                "Connection": "close",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=120,
            ) as response:
                payload = response.read()
                status = int(response.status)
                content_type = response.headers.get(
                    "Content-Type",
                    "application/octet-stream",
                )

        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = int(exc.code)
            content_type = exc.headers.get(
                "Content-Type",
                "application/octet-stream",
            )

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ):
            self._reject(
                502,
                "approved runtime endpoint is unavailable",
            )
            return

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        self._forward()

    def do_PUT(self) -> None:  # noqa: N802
        self._reject(405, "method is not permitted")

    def do_PATCH(self) -> None:  # noqa: N802
        self._reject(405, "method is not permitted")

    def do_DELETE(self) -> None:  # noqa: N802
        self._reject(405, "method is not permitted")

    def do_CONNECT(self) -> None:  # noqa: N802
        self._reject(405, "method is not permitted")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._reject(405, "method is not permitted")

    def do_HEAD(self) -> None:  # noqa: N802
        self._reject(405, "method is not permitted")

    def log_message(self, message: str, *args: object) -> None:
        return


if __name__ == "__main__":
    import argparse
    from http.server import ThreadingHTTPServer

    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()

    server = ThreadingHTTPServer(
        (args.host, args.port),
        RuntimeGatewayHandler,
    )
    server.mie_gateway_config = RuntimeGatewayConfig(
        upstream_endpoint=args.upstream,
        allowed_paths=("/api/chat",),
    )
    server.serve_forever()

