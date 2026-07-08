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


def _log_dir() -> str:
    """Folder to write logs into: a **machine-local, non-synced** folder.

    Logs previously lived beside the exe / entry script, but that folder is typically a
    OneDrive library synced across machines — so every coworker's instance wrote the *same*
    synced log file, producing ``*.log-<MACHINE>.N`` conflict copies and rename races. Keeping
    logs local avoids that. Resolver is inlined (``LOCALAPPDATA`` + home fallback) so it runs at
    import time without importing ``config`` (which imports ``log`` from here — a cycle).
    Mirrors :func:`config.local_dir`; the ``[paths] local_dir`` ini override is applied there, not
    here (logging is configured before the ini is read)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
    d = os.path.join(base, "PaintAllocationDashboard") if base \
        else os.path.join(os.path.expanduser("~"), ".paint_allocation_dashboard")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        # Fall back to the old behaviour (beside the exe / entry script) if the local dir
        # can't be created, so logging still has somewhere to go.
        d = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
            else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return d


def _prog_name() -> str:
    """A per-program base name so the 3 exes (planner + 2 viewers) don't fight over one
    log file (multi-process RotatingFileHandler rotation would race)."""
    if getattr(sys, "frozen", False):
        base = os.path.basename(sys.executable)
    else:
        base = os.path.basename(sys.argv[0] or "paint_dashboard")
    return os.path.splitext(base)[0] or "paint_dashboard"


_LOG_DIR = _log_dir()
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
# 2.1.0: multi-release selection/push, reconcile heartbeat + last-EC/PC-op gate, editor
# grouping/collapse/ack/reset, toast notifications, publish-when-empty, EC-eligibility fix.
# 2.2.0: overdue release detection + faint red wash in the queue (global past-due + same-date
# duplicate collisions, gated to ship date <= today), P6 internal-lead-time -1-day shift
# (display/overdue only), the daily Volvo-Trucks churn-snapshot pool (computed + logged; not yet
# wired into the wash), the queue inventory add-date range, the "Any"/"All" condition filters
# (replacing "OR"), and a global loading bar replacing the sticky per-button animations.
# 2.2.1: queue leftmost indicator changed from the concern pip to an inventory-age caution sign
# (yellow triangle when the oldest allocated container is >= 4 days old; blank otherwise).
# 2.2.2: runlist editor per-item delete — selection checkboxes + dual-purpose pane button
# ("Delete (N)" for selected, else "Clear"); new POST /runlist/delete.
# 2.2.3: fixed the runlist "wiped on data pull" bug — the planner-local draft (and logs) now live
# in a machine-local, NON-SYNCED folder (config.local_dir / %LOCALAPPDATA%) instead of the shared
# OneDrive run dir, so concurrent instances on other machines no longer overwrite each other via
# OneDrive sync (one-time migration seeds the local draft from the old draft/live). Plus a
# visual-only "ran" checkbox on the PC/EC floor pages (per-browser localStorage; dim+strikethrough).
# 2.2.4: (a) Pre-Production quick filter — Part_Status from Part Attributes SQL surfaced per release
# (`partStatus`; Production-wins de-dup for the ~3% of parts with conflicting attribute rows); a
# tri-state queue chip cycles off → Pre-Production only → hide Pre-Production, persisted in views.
# (b) "Kick" button — force-take the writer lock from a foreign owner (POST /runlist/kick → lock.seize).
__version__ = "2.2.4"

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
