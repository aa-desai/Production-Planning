"""
In-memory application state (read-only; refreshed by POST /refresh)
===================================================================
Holds the current :class:`PipelineResult`, its derived indexes, and the queue
payload. ``refresh`` re-runs allocation and swaps everything in atomically, with
retain-on-failure semantics, serialised so a manual Refresh and the auto-update
watcher never run the pipeline concurrently.

Graph/allocation split (design §3.1, R13/R14): the routing/BOM-derived
:class:`DailyInputs` are cached and rebuilt only on the first run of the local day
(or on demand via ``refresh(rebuild_graph=True)``); each refresh re-loads inventory +
releases and re-allocates against those cached inputs.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime
from typing import Optional

from . import __version__, log
from .datasource import _raw_data_mtime_epoch
from .indexes import Indexes, build_indexes
from .payload import build_queue_payload, set_current_graph
from .pipeline import DailyInputs, PipelineResult, load_daily_inputs, run_allocation
from .runlists import lock as rlock, push as rpush, reconcile as rrec, store as rstore
from .runlists.model import items_from_doc, new_doc
from .snapshot import write_snapshot


class AppState:
    def __init__(self):
        self.result: Optional[PipelineResult] = None
        self.idx: Optional[Indexes] = None
        self.queue_payload: Optional[dict] = None
        self.daily: Optional[DailyInputs] = None  # cached routing/BOM-derived inputs (per local day)
        self.lock = threading.Lock()              # guards the payload swap
        self.refresh_lock = threading.Lock()      # serialises refreshes (manual + watcher)
        self.source_mtime = 0.0                   # raw-data mtime the current payload was built from

    def _ensure_daily(self, force: bool = False) -> DailyInputs:
        """Return today's cached :class:`DailyInputs`, (re)building if stale or *force*.

        Rebuild triggers (R14): no cache yet, the cache is from an earlier local day,
        or an explicit force (the "Rebuild graph" button). Mid-day routing/BOM changes
        are intentionally NOT auto-detected — they need the force path.
        Caller holds ``refresh_lock``.
        """
        today = date.today()
        d = self.daily
        if force or d is None or d.built_date != today:
            why = "forced" if force else ("first build" if d is None else "new day")
            log.info("Building daily inputs (%s)...", why)
            self.daily = load_daily_inputs()
        else:
            log.info("Reusing daily inputs from %s (built %s)", d.built_date, d.built_at.strftime("%H:%M:%S"))
        return self.daily

    def refresh(self, retries: int = 1, rebuild_graph: bool = False) -> dict:
        """Re-allocate + rebuild payloads atomically. Retain-on-failure.

        Serialised by ``refresh_lock`` so a manual Refresh and the auto-update watcher
        never run concurrently. ``rebuild_graph=True`` forces the daily inputs to rebuild
        (the "Rebuild graph" button / first run of a new day).
        """
        with self.refresh_lock:
            last_err = None
            for attempt in range(retries + 1):
                # Capture the source mtime BEFORE the read so a pull that lands
                # mid-build is caught by the next watcher tick rather than lost.
                src = _raw_data_mtime_epoch()
                started = datetime.now()  # snapshot filename timestamp = build init time
                try:
                    daily = self._ensure_daily(force=rebuild_graph)
                    result = run_allocation(daily)
                    idx = build_indexes(result)
                    payload = build_queue_payload(result, idx)
                    with self.lock:
                        self.result, self.idx, self.queue_payload = result, idx, payload
                        set_current_graph(result.graph)
                        self.source_mtime = src
                    write_snapshot(payload, started)
                    self._reconcile_runlist(result)
                    return payload
                except (PermissionError, OSError) as e:
                    last_err = e
                    log.warning("Refresh attempt %d failed (locked file?): %s", attempt + 1, e)
                    time.sleep(2)
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    log.exception("Refresh failed: %s", e)
                    break
            raise RuntimeError(f"Pipeline refresh failed: {last_err}")


    def _reconcile_runlist(self, result) -> None:
        """Drop/reduce containers that have been run, on each refresh (design §15). Best-effort.

        If we hold the writer lock, republish the reconciled list so the floor views drop
        completed containers automatically.
        """
        try:
            sidx = rrec.build_serial_index(result)
            draft = rpush.load_draft()
            draft, rep = rrec.reconcile_doc(draft, sidx)
            rpush.save_draft(draft)
            if any(rep[t]["removed"] or rep[t]["reduced"] for t in ("pc", "ec")):
                log.info("Runlist reconcile: pc=%s ec=%s", rep["pc"], rep["ec"])
            if rlock.own():
                live = new_doc(items_from_doc(draft, "pc"), items_from_doc(draft, "ec"),
                               app_version=__version__, owner=rlock.read_owner() or {})
                rstore.write_live(live)
        except Exception as e:  # noqa: BLE001
            log.warning("Runlist reconcile skipped: %s", e)


STATE = AppState()
