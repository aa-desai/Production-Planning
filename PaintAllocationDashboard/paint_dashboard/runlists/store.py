"""
Runlist persistence (design §10)
================================
Atomic read/write for the two runlist files:

* **draft** — planner-local (``<local dir>/runlist_draft.json``); where edits land, survives
  a planner restart. Stored in a **machine-local, non-synced** folder (:func:`config.local_dir`),
  NOT the OneDrive run dir — otherwise concurrent instances on other machines overwrite it via
  OneDrive sync and the runlist gets wiped on a data pull.
* **live** — shared/published (``<shared dir>/Runlists/runlist_live.json``); what the floor
  viewers read. Only the lock owner writes it (lock enforcement is a later step).

Stdlib-only so the floor viewer exes stay tiny (R15).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .. import log
from ..config import local_dir, run_dir, shared_dir

LIVE_NAME = "runlist_live.json"
DRAFT_NAME = "runlist_draft.json"


def runlist_dir() -> Path:
    """Shared folder holding the published runlist (and, later, the writer lock)."""
    return shared_dir() / "Runlists"


def live_path() -> Path:
    return runlist_dir() / LIVE_NAME


def draft_path() -> Path:
    return local_dir() / DRAFT_NAME


def _legacy_draft_path() -> Path:
    """Where the draft used to live (the OneDrive run dir) — read once for migration."""
    return run_dir() / DRAFT_NAME


def _has_items(doc: Optional[dict]) -> bool:
    return bool(doc) and bool(doc.get("pc") or doc.get("ec"))


def _ensure_local_draft() -> None:
    """One-time migration: seed the new machine-local draft if it doesn't exist yet.

    Preference order so an upgrading planner doesn't appear to lose its list:
    the old OneDrive draft (if it still has items) → the shared **live** runlist → nothing.
    Best-effort; any failure just leaves the local draft absent (treated as empty downstream).
    """
    local = draft_path()
    if local.exists():
        return
    try:
        legacy = _read(_legacy_draft_path())
        seed = legacy if _has_items(legacy) else read_live()
        if _has_items(seed):
            _atomic_write(local, seed)
            log.info("Migrated runlist draft to machine-local store: %s", local)
    except Exception as e:  # noqa: BLE001
        log.warning("Local draft migration skipped: %s", e)


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
    _ensure_local_draft()  # first read after upgrade seeds the local draft from legacy/live
    return _read(draft_path())
