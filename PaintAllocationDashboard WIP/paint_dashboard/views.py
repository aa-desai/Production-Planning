"""
Shared saved-views bank (design §7a, R12)
=========================================
Personal saved views live in the browser's ``localStorage`` (handled client-side). This
module backs the **shared "common bank"**: one JSON file per named view in
``<shared dir>/Views/`` (``{name, filters, creator, updatedAt}``). Any planner can add a
view and apply anyone's; **only the creator may overwrite or delete** their own
(conflict-free, mirroring the old per-file overrides pattern). Stdlib-only.
"""

from __future__ import annotations

import getpass
import json
import re
import time
from pathlib import Path

from . import log
from .config import shared_dir

_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def views_dir() -> Path:
    return shared_dir() / "Views"


def current_user() -> str:
    try:
        return getpass.getuser() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _fname(name: str) -> str:
    return (_SAFE.sub("_", name.strip())[:80] or "view")


def list_views() -> list[dict]:
    """All shared views (each ``{name, filters, creator, updatedAt}``), name-sorted."""
    d = views_dir()
    out: list[dict] = []
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning("Skipping unreadable shared view %s: %s", p.name, e)
    return sorted(out, key=lambda v: str(v.get("name", "")).lower())


def save_view(name: str, filters, requester: str) -> dict:
    """Create/overwrite a shared view. Only the original creator may overwrite an existing one."""
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "reason": "name required"}
    d = views_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / (_fname(name) + ".json")
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cur = {}
        if cur.get("creator") and cur.get("creator") != requester:
            return {"ok": False, "reason": "owned", "creator": cur.get("creator")}
    doc = {"name": name, "filters": filters, "creator": requester,
           "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    tmp.replace(p)
    log.info("Shared view saved: %s (by %s)", name, requester)
    return {"ok": True, "view": doc}


def delete_view(name: str, requester: str) -> dict:
    """Delete a shared view — only its creator may."""
    p = views_dir() / (_fname(str(name or "")) + ".json")
    if not p.exists():
        return {"ok": True}
    try:
        cur = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cur = {}
    if cur.get("creator") and cur.get("creator") != requester:
        return {"ok": False, "reason": "owned", "creator": cur.get("creator")}
    try:
        p.unlink()
    except OSError as e:
        return {"ok": False, "reason": str(e)}
    return {"ok": True}
