"""
Runlist persistence (design §10)
================================
Atomic read/write for the two runlist files:

* **draft** — planner-local (``<run dir>/runlist_draft.json``); where edits land, survives
  a planner restart.
* **live** — shared/published (``<shared dir>/Runlists/runlist_live.json``); what the floor
  viewers read. Only the lock owner writes it (lock enforcement is a later step).

Stdlib-only so the floor viewer exes stay tiny (R15).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .. import log
from ..config import run_dir, shared_dir

LIVE_NAME = "runlist_live.json"
DRAFT_NAME = "runlist_draft.json"


def runlist_dir() -> Path:
    """Shared folder holding the published runlist (and, later, the writer lock)."""
    return shared_dir() / "Runlists"


def live_path() -> Path:
    return runlist_dir() / LIVE_NAME


def draft_path() -> Path:
    return run_dir() / DRAFT_NAME


def _atomic_write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read %s: %s", path.name, e)
        return None


def write_live(doc: dict) -> None:
    _atomic_write(live_path(), doc)
    log.info("Runlist published: %s (pc=%d ec=%d)",
             LIVE_NAME, len(doc.get("pc", [])), len(doc.get("ec", [])))


def read_live() -> Optional[dict]:
    return _read(live_path())


def write_draft(doc: dict) -> None:
    _atomic_write(draft_path(), doc)


def read_draft() -> Optional[dict]:
    return _read(draft_path())
