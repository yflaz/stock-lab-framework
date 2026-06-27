from __future__ import annotations

import json
import mimetypes
import os
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.config import load_config
from core.state_builder import initial_state, save_current_state
from core.state_store import SECTOR_PATH, STATE_PATH, load_json
from core.stock_analysis import analyze_a_share_stock

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
HTML_PATH = STATIC / "dashboard.html"
MOBILE_HTML_PATH = STATIC / "mobile.html"


def load_state_payload(refresh: bool = False) -> dict:
    if refresh:
        return save_current_state(load_config())
    if STATE_PATH.exists():
        return load_json(STATE_PATH, {})
    return initial_state(load_config())


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        return


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _safe_write(self, body: bytes) -> None:
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            return

    def _send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._safe_write(body)

    def _send_file(self, path: Path, status: int = 200) -> None:
        if not path.exists():
            return self._send_json({"ok": False, "error": f"Missing file: {path.name}"}, HTTPStatus.NOT_FOUND)
        body = path.read_bytes()
        ctype, _ = mimetypes.guess_type(str(path))
        self.send_response(status)
        self.send_header("Content-Type", (ctype or "text/plain") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self._safe_write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/health":
            return self._send_json({"ok": True, "service": "stock-lab-new"})
        if path == "/api/state":
            return self._send_json(load_state_payload(refresh=query.get("refresh") == ["1"]))
        if path == "/api/analyze_stock":
            symbol = str((query.get("symbol") or [""])[0]).strip()
            try:
                return self._send_json(analyze_a_share_stock(symbol))
            except ValueError as exc:
                return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        if path == "/api/sectors":
            return self._send_json(load_json(SECTOR_PATH, []))
        if path in {"/", "/dashboard", "/index.html"}:
            return self._send_file(HTML_PATH)
        if path in {"/m", "/m/", "/m/index.html"}:
            return self._send_file(MOBILE_HTML_PATH)
        if path.startswith("/static/"):
            rel = path.removeprefix("/static/").replace("\\", "/")
            target = (STATIC / rel).resolve()
            if STATIC.resolve() not in target.parents and target != STATIC.resolve():
                return self._send_json({"ok": False, "error": "Forbidden"}, HTTPStatus.FORBIDDEN)
            return self._send_file(target)
        return self._send_json({"ok": False, "error": f"Unknown path: {path}"}, HTTPStatus.NOT_FOUND)


def main() -> None:
    host = os.getenv("STOCK_LAB_HOST", "0.0.0.0")
    port = int(os.getenv("STOCK_LAB_PORT", "8765"))
    try:
        server = ReusableThreadingHTTPServer((host, port), DashboardHandler)
    except OSError as exc:
        if getattr(exc, "errno", None) in {98, 10048}:
            print(f"Port {port} is already in use. Set STOCK_LAB_PORT to another value.")
            raise SystemExit(2)
        raise
    print(f"Stock Lab New dashboard serving on http://127.0.0.1:{port}/dashboard")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
