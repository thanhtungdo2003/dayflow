"""Local web UI server (stdlib only).

Security model — the vault's contents are served to a browser, so the server:
* binds to 127.0.0.1 only;
* requires a random per-run token on every /api call, sent in the `X-WA-Token` header. The
  browser receives it in the URL fragment (never sent to the server or logged) when the user
  opens the UI from the tray. A custom header also forces a CORS preflight, which we never
  approve, so other websites cannot call the API (CSRF);
* rejects requests whose Host is not our loopback address (DNS rebinding) and cross-origin
  requests carrying a foreign Origin;
* serves only a fixed allow-list of static files, with a strict CSP and no caching;
* never logs request paths or bodies.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
MAX_BODY = 1_000_000
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class Api(Protocol):
    def handle(self, method: str, path: str, query: dict[str, str], body: dict[str, Any]) -> tuple[int, Any]: ...


class WebServer:
    def __init__(self, api: Api, port: int = 8765, static_dir: Path = STATIC_DIR):
        self.api = api
        self.requested_port = port
        self.static_dir = static_dir
        self.token = secrets.token_urlsafe(32)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else 0

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def url(self, view: str = "") -> str:
        return f"{self.origin}/#t={self.token}" + (f"&v={view}" if view else "")

    def start(self) -> bool:
        if self._httpd is not None:
            return True
        handler = type("Handler", (_Handler,), {"server_ref": self})
        for port in (self.requested_port, 0):  # fall back to any free port if ours is taken
            try:
                self._httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
                break
            except OSError:
                log.warning("web port %d unavailable", port)
        if self._httpd is None:
            return False
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="web", daemon=True)
        self._thread.start()
        log.info("web UI listening on 127.0.0.1:%d", self.port)
        return True

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        log.info("web UI stopped")


class _Handler(BaseHTTPRequestHandler):
    server_ref: WebServer
    server_version = "WorkAgent"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        pass  # privacy: never log paths (dates, ids) or anything else about requests

    # --- verbs ------------------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def do_OPTIONS(self) -> None:  # noqa: N802 - CORS preflight: always refused
        self._send(403, {"error": "forbidden"})

    # --- core -------------------------------------------------------------------------------

    def _dispatch(self, method: str) -> None:
        srv = self.server_ref
        allowed_hosts = {f"127.0.0.1:{srv.port}", f"localhost:{srv.port}"}
        if self.headers.get("Host", "") not in allowed_hosts:
            return self._send(421, {"error": "bad_host"})
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in allowed_hosts}:
            return self._send(403, {"error": "bad_origin"})
        url = urlsplit(self.path)
        if not url.path.startswith("/api/"):
            if method != "GET":
                return self._send(405, {"error": "method"})
            return self._static(url.path)
        token = self.headers.get("X-WA-Token", "")
        if not hmac.compare_digest(token.encode(), srv.token.encode()):
            return self._send(401, {"error": "token"})
        body: dict[str, Any] = {}
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, {"error": "too_large"})
        if length:
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._send(415, {"error": "json_only"})
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                return self._send(400, {"error": "bad_json"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "bad_json"})
        query = dict(parse_qsl(url.query))
        status, payload = srv.api.handle(method, url.path, query, body)
        self._send(status, payload)

    def _static(self, path: str) -> None:
        entry = STATIC_FILES.get(path)
        if entry is None:
            return self._send(404, {"error": "not_found"})
        name, ctype = entry
        try:
            data = (self.server_ref.static_dir / name).read_bytes()
        except OSError:
            return self._send(404, {"error": "not_found"})
        self._write(200, data, ctype)

    def _send(self, status: int, payload: Any) -> None:
        self._write(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _write(self, status: int, data: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)
