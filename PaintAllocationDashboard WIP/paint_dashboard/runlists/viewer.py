"""
Floor runlist viewer (stdlib-only) — design §9, §17, §18
========================================================
A tiny, pipeline-free HTTP server for a shop-floor screen. It reads the shared,
planner-published ``runlist_live.json`` and serves a read-only PC or EC floor page that
polls for updates. No pandas / engine — so the packaged viewer exe stays tiny (R15).

Endpoints:
* ``GET /``             — the floor page (PC or EC).
* ``GET /runlist.json`` — the current runlist for this view (PC grouped; EC flat) + metadata.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .. import __version__, log
from ..config import CONFIG
from .grouping import group_pc
from .model import items_from_doc
from .store import live_path, read_live
from .ui import EC_PAGE, PC_PAGE


def _runlist_json(target: str) -> dict:
    """The published runlist for *target* shaped for its floor page (+ metadata)."""
    doc = read_live() or {}
    out = {"target": target, "appVersion": doc.get("appVersion"), "publishedAt": doc.get("publishedAt")}
    if target == "pc":
        out["groups"] = group_pc(items_from_doc(doc, "pc"))
    else:
        out["items"] = [it.to_dict() for it in items_from_doc(doc, "ec")]
    return out


def _make_handler(target: str):
    page = PC_PAGE if target == "pc" else EC_PAGE

    class ViewerHandler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quieter console
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/runlist.json":
                body = json.dumps(_runlist_json(target)).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

    return ViewerHandler


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run_viewer(target: str) -> None:
    target = target.lower()
    if target not in ("pc", "ec"):
        raise SystemExit("Runlist viewer target must be 'pc' or 'ec'.")
    label = target.upper()
    log.info("Paint %s Runlist viewer starting (read-only floor view, v%s)", label, __version__)
    log.info("Reading shared runlist: %s", live_path())

    host = CONFIG.get("host", "127.0.0.1")
    port = CONFIG.get("port") or _free_port()
    httpd = ThreadingHTTPServer((host, port), _make_handler(target))
    url = f"http://{host}:{port}/"
    log.info("Serving %s runlist at %s  (Ctrl+C / close window to stop)", label, url)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        httpd.shutdown()


def run(target: str) -> None:
    """Console entry: run the viewer, keeping the window open on a hard failure."""
    try:
        run_viewer(target)
    except Exception as e:  # noqa: BLE001
        log.exception("Runlist viewer failed: %s", e)
        input("Press Enter to close...")
        sys.exit(1)
