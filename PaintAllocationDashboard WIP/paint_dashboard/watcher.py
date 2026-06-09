"""
ERP auto-update watcher
=======================
Background daemon that rebuilds the pipeline when new raw files are pulled from the
ERP. Polls the max raw-data mtime; once a pull settles (debounce), triggers
``STATE.refresh()``. The browser's poll then picks up the new payload automatically.
"""

from __future__ import annotations

import threading
import time

from . import log
from .datasource import _raw_data_mtime_epoch, latest_raw_data_mtime
from .state import STATE

WATCH_POLL_SEC = 15       # how often to check the raw-data folders
WATCH_DEBOUNCE_SEC = 12   # require the mtime to be stable this long before rebuilding
RECONCILE_HEARTBEAT_SEC = 300  # re-read + reconcile the runlist every 5 min (design §15)


def start_watcher() -> None:
    """Background daemon: rebuild when new raw files are pulled from the ERP.

    Polls the max raw-data mtime. A new pull bumps the mtime; we wait until it
    stops moving (DEBOUNCE) so we don't read a half-written export, then trigger
    ``STATE.refresh()`` (which has its own retry + retain-on-failure). The
    browser's poll picks up the new payload automatically.
    """
    def loop():
        pending = None
        pending_since = 0.0
        while True:
            time.sleep(WATCH_POLL_SEC)
            try:
                cur = _raw_data_mtime_epoch()
            except Exception:  # noqa: BLE001
                continue
            if cur <= STATE.source_mtime:
                pending = None          # nothing newer than the current build
                continue
            if cur != pending:
                pending = cur            # files still arriving — keep waiting
                pending_since = time.monotonic()
                continue
            if time.monotonic() - pending_since >= WATCH_DEBOUNCE_SEC:
                log.info("Raw data changed — auto-refreshing…")
                try:
                    STATE.refresh()
                    log.info("Auto-refresh complete (Data Pulled At %s).", latest_raw_data_mtime())
                except Exception as e:  # noqa: BLE001
                    log.warning("Auto-refresh failed (will retry next tick): %s", e)
                pending = None
    threading.Thread(target=loop, name="erp-watcher", daemon=True).start()
    log.info("ERP auto-update watcher started (poll %ss, debounce %ss).",
             WATCH_POLL_SEC, WATCH_DEBOUNCE_SEC)


def start_reconcile_heartbeat(interval_sec: int = RECONCILE_HEARTBEAT_SEC) -> None:
    """Background daemon: re-read inventory + reconcile the runlist every *interval_sec*.

    Independent of the ERP watcher (which only fires on a new pull). A periodic
    ``STATE.refresh()`` re-reads inventory/releases and runs reconciliation, so containers
    that have been run drop off the floor runlist (and the planner's draft) even when no new
    ERP files arrived and nobody clicks Refresh. ``STATE.refresh`` is serialised by its own
    lock, so this never collides with a manual Refresh or the watcher.
    """
    def loop():
        while True:
            time.sleep(interval_sec)
            try:
                STATE.refresh()
                log.info("Reconcile heartbeat: re-read + reconciled runlist.")
            except Exception as e:  # noqa: BLE001
                log.warning("Reconcile heartbeat failed (will retry next tick): %s", e)
    threading.Thread(target=loop, name="reconcile-heartbeat", daemon=True).start()
    log.info("Runlist reconcile heartbeat started (every %ss).", interval_sec)
