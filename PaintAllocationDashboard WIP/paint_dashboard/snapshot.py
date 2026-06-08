r"""
Snapshot cache — shared pool (design §7, R11)
=============================================
A small JSON cache of the queue payload so the dashboard opens instantly, before the
live in-memory rebuild finishes.

Snapshots are written to a **shared pool** (``<shared dir>/Snapshots/``) named
``Dashboard Snapshot - <version> - <ComputerID> - <YYYY-MM-DD_HHMMSS>.json`` (time = the
pipeline-run init time). After each write the pool is pruned to the **5 most-recent files
overall** (across all machines — a busy machine may evict another's older snapshot, R11).
On startup the newest snapshot is read for an instant open.

Defaults to a local ``Snapshots\`` subfolder of the run dir; point ``[shared] dir`` at a
OneDrive/network folder to share the pool between machines.
"""

from __future__ import annotations

import json
import platform
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import __version__, log
from .config import shared_dir

SNAPSHOT_DIR = shared_dir() / "Snapshots"
SNAPSHOT_GLOB = "Dashboard Snapshot - *.json"
KEEP_SNAPSHOTS = 5


def _computer_id() -> str:
    """Filesystem-safe machine identifier for the snapshot filename."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", platform.node() or "unknown")


def _snapshot_name(when: datetime) -> str:
    return f"Dashboard Snapshot - {__version__} - {_computer_id()} - {when:%Y-%m-%d_%H%M%S}.json"


_TS_RE = re.compile(r" - (\d{4}-\d{2}-\d{2}_\d{6})\.json$")


def _snapshot_time(p: Path) -> str:
    """The embedded ``YYYY-MM-DD_HHMMSS`` build time from the filename (sortable).

    Used for ordering instead of mtime: it is the authoritative "when initialized" time and
    is immune to OneDrive rewriting file mtimes on sync. Fixed-width, so a lexicographic
    sort is chronological.
    """
    m = _TS_RE.search(p.name)
    return m.group(1) if m else ""


def _pool_files() -> list[Path]:
    """Snapshot files in the pool, newest first (by embedded build time, mtime tiebreak)."""
    try:
        files = list(SNAPSHOT_DIR.glob(SNAPSHOT_GLOB))
    except OSError:
        return []
    return sorted(files, key=lambda p: (_snapshot_time(p), p.stat().st_mtime), reverse=True)


def _prune_snapshots() -> None:
    """Keep only the KEEP_SNAPSHOTS most-recent files; tolerate concurrent pruning."""
    for old in _pool_files()[KEEP_SNAPSHOTS:]:
        try:
            old.unlink()
        except OSError:
            pass  # another machine may have pruned it first — fine


def write_snapshot(payload: dict, when: Optional[datetime] = None) -> None:
    when = when or datetime.now()
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        dest = SNAPSHOT_DIR / _snapshot_name(when)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(dest)
        log.info("Snapshot cached: %s", dest.name)
        _prune_snapshots()
    except Exception as e:  # noqa: BLE001
        log.warning("Could not write snapshot: %s", e)


def read_snapshot() -> Optional[dict]:
    """Newest snapshot in the pool, or None if the pool is empty / unreadable."""
    files = _pool_files()
    if not files:
        return None
    newest = files[0]
    try:
        return json.loads(newest.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read snapshot %s: %s", newest.name, e)
        return None
