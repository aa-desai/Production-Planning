"""
Entry point
===========
Wires the pieces together: resolve the project root, fast-open from the snapshot
cache, build live in memory, optionally self-check parity, start the auto-update
watcher, then serve the read-only dashboard.

CLI flags: ``--no-browser`` (don't open a browser), ``--no-watch`` (disable the ERP
watcher), ``--parity`` (run the parity check), ``--config <path>`` (explicit config).
"""

from __future__ import annotations

import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from . import bootstrap, log
from .config import CONFIG
from .parity import parity_check
from .server import Handler, _free_port
from .snapshot import read_snapshot
from .state import STATE
from .watcher import start_watcher


def main() -> None:
    log.info("Paint Allocation Dashboard starting (read-only, design v10)")

    # Resolve the project root and point the vendored engine at it (must precede
    # any pipeline run).
    bootstrap.configure()

    # Fast open from snapshot if present, then build fresh in memory.
    cached = read_snapshot()
    if cached:
        STATE.queue_payload = cached
        log.info("Loaded cached snapshot (%s releases) for instant open.",
                 cached.get("releaseCount"))

    STATE.refresh()  # build live; overwrites cache
    if "--parity" in sys.argv:
        parity_check(STATE.result)

    # Auto-update when new ERP files are pulled (config: [refresh] auto_update).
    if CONFIG.get("auto_update", True) and "--no-watch" not in sys.argv:
        start_watcher()

    host = CONFIG.get("host", "127.0.0.1")
    port = CONFIG.get("port") or _free_port()
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    log.info("Serving dashboard at %s  (Ctrl+C / close window to stop)", url)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        httpd.shutdown()


def run() -> None:
    """Console entry: run :func:`main`, keeping the window open on a hard failure."""
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log.exception("Dashboard failed: %s", e)
        input("Press Enter to close...")
        sys.exit(1)


if __name__ == "__main__":
    run()
