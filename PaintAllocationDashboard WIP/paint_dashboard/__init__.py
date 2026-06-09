r"""Paint Allocation Dashboard (READ-ONLY)
======================================
Interactive, in-memory replacement for the ``Allocation_V2.csv`` Excel workflow.

The dashboard re-runs the V2 graph-allocation pipeline in memory and serves a
two-pane, read-only view from a local ``http.server``. No UI action mutates any
file; the only file written is a local, per-machine snapshot cache
(``paint_allocation_dashboard_snapshot.json``) — a derived performance file.

This package is fully self-contained under ``PaintAllocationDashboard\``: the
allocation engine it runs lives in :mod:`paint_dashboard.engine` (a vendored copy
of the trusted ``graph_allocator_V2`` / ``allocation_common`` modules).

Module map
----------
* :mod:`~paint_dashboard.config`        — config file + run-dir / project-root paths.
* :mod:`~paint_dashboard.bootstrap`     — resolve the project root, point the engine at it.
* :mod:`~paint_dashboard.pipeline`      — ``run_pipeline`` -> ``PipelineResult``.
* :mod:`~paint_dashboard.parity`        — optional parity check vs the on-disk CSV.
* :mod:`~paint_dashboard.datasource`    — raw-data mtime helpers ("Data Pulled At").
* :mod:`~paint_dashboard.coverage`      — coverage bucketing + concern classification.
* :mod:`~paint_dashboard.serialization` — JSON-safe scalar coercion.
* :mod:`~paint_dashboard.swatches`      — powder-colour swatch map + paint badges.
* :mod:`~paint_dashboard.indexes`       — derived lookup indexes over a ``PipelineResult``.
* :mod:`~paint_dashboard.payload`       — queue payload + on-demand detail tree.
* :mod:`~paint_dashboard.snapshot`      — local snapshot cache read/write.
* :mod:`~paint_dashboard.state`         — in-memory ``AppState`` (refresh under lock).
* :mod:`~paint_dashboard.watcher`       — ERP auto-update watcher.
* :mod:`~paint_dashboard.server`        — read-only HTTP endpoints.
* :mod:`~paint_dashboard.ui`            — embedded single-page UI.
* :mod:`~paint_dashboard.app`           — ``main`` / ``run`` entry point.

Design + build log: ``DESIGN.md`` / ``PROGRESS.md`` (in the PaintAllocationDashboard folder).
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
import time


def _run_dir() -> str:
    """Folder to write logs into: beside the frozen exe, else the launcher's folder
    (the ``PaintAllocationDashboard*`` dir that holds the entry script)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _prog_name() -> str:
    """A per-program base name so the 3 exes (planner + 2 viewers) don't fight over one
    log file (multi-process RotatingFileHandler rotation would race)."""
    if getattr(sys, "frozen", False):
        base = os.path.basename(sys.executable)
    else:
        base = os.path.basename(sys.argv[0] or "paint_dashboard")
    return os.path.splitext(base)[0] or "paint_dashboard"


_LOG_DIR = _run_dir()
LOG_FILE = os.path.join(_LOG_DIR, _prog_name() + ".log")
FAULT_FILE = os.path.join(_LOG_DIR, _prog_name() + "_fault.log")

# Console + a rotating FILE handler so logs (and any crash traceback) survive the window
# closing. ``basicConfig`` is idempotent — a later call from the vendored engine is a no-op.
_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
try:
    _handlers.append(logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8", delay=True))
except OSError:
    pass  # e.g. OneDrive lock / permission — keep console logging regardless

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_handlers,
)
# A logging hiccup (e.g. OneDrive briefly locking the file) must never crash the app.
logging.raiseExceptions = False

# Application version (SemVer; see DESIGN.md §V). MAJOR = capability epoch
# (1 = read-only dashboard, 2 = + PC/EC runlists). In-development builds toward the
# next release carry a "-dev" suffix; drop it when that version is complete & verified.
__version__ = "2.0.0-dev"

# Shared logger name, matching the original single-file module.
log = logging.getLogger("paint_dashboard")


# ---- Crash capture: persist the traceback for ANY unhandled failure ------------------
def _log_uncaught(exc_type, exc, tb) -> None:
    """Last-resort hook for an unhandled MAIN-thread exception (KeyboardInterrupt passes
    through to the default handler so Ctrl-C still exits quietly)."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    log.critical("UNCAUGHT EXCEPTION (main thread)", exc_info=(exc_type, exc, tb))


def _log_thread_uncaught(args) -> None:
    """Unhandled exception in a worker thread (server request, watcher, heartbeat).
    These don't normally close the window, but a silently dying thread can explain odd
    behaviour — record it."""
    if issubclass(args.exc_type, SystemExit):
        return
    name = args.thread.name if args.thread else "?"
    log.critical("UNCAUGHT EXCEPTION (thread %s)", name,
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


sys.excepthook = _log_uncaught
threading.excepthook = _log_thread_uncaught

# faulthandler catches HARD/native crashes (a segfault from pandas / numpy / calamine, a
# stack overflow, etc.) that bypass Python's exception machinery and would otherwise close
# the window with no trace. Dump a C-level traceback (all threads) to a dedicated file kept
# open for the process lifetime.
try:
    _fault_fp = open(FAULT_FILE, "a", encoding="utf-8")
    _fault_fp.write("\n==== session start %s  pid %s  %s ====\n"
                    % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), _prog_name()))
    _fault_fp.flush()
    faulthandler.enable(file=_fault_fp, all_threads=True)
except OSError:
    pass

__all__ = ["log", "__version__", "LOG_FILE", "FAULT_FILE"]
