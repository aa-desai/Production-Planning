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

from . import FAULT_FILE, LOG_FILE, bootstrap, log
from .config import CONFIG
from .parity import parity_check
from .server import DashboardServer, Handler, _free_port
from .snapshot import read_snapshot
from .state import STATE
from .watcher import start_reconcile_heartbeat, start_watcher


def main() -> None:
    log.info("Paint Allocation Dashboard starting (read-only, design v10)")
    log.info("Log file: %s", LOG_FILE)
    log.info("Native-crash log (faulthandler): %s", FAULT_FILE)

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
        # Periodic re-read + runlist reconciliation (every 5 min) so run containers drop off
        # the floor/planner lists even without a new ERP pull or a manual Refresh (design §15).
        start_reconcile_heartbeat(int(CONFIG.get("reconcile_heartbeat_sec", 300)))

    host = CONFIG.get("host", "127.0.0.1")
    port = CONFIG.get("port") or _free_port()
    httpd = DashboardServer((host, port), Handler)
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
    """Console entry: run :func:`main`, keeping the window open on a hard failure so the
    operator can read the error (the full traceback is also written to ``LOG_FILE``)."""
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log.exception("Dashboard failed: %s", e)
        log.critical("See the log file for the full traceback: %s", LOG_FILE)
        try:
            input("Press Enter to close...")
        except (EOFError, OSError):
            pass  # no interactive console — the file log still has the traceback
        sys.exit(1)


if __name__ == "__main__":
    run()
