"""
Single-writer lock for the runlist (design §14, R6/R16)
=======================================================
Only one planner instance may write the shared ``runlist_live.json``. A lock file
``runlist_owner.lock`` on the shared path records the owner + a heartbeat. The owner
rewrites the heartbeat every 10 minutes. Takeover is **event-driven** (triggered when a
non-owner tries to author/publish), gated by a **missed-heartbeat confirmation**: if the
current owner's heartbeat is stale, the contender waits a short window and re-checks before
seizing the lock. Stdlib-only (the viewers don't write, but this keeps deps light).

Identity is per *process* (a fresh ``instance`` token), so two instances on the same machine
are distinguished. Writes are atomic; simultaneous seizes resolve last-writer-wins and are
re-verified after the write.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import log
from .store import runlist_dir

LOCK_NAME = "runlist_owner.lock"
HEARTBEAT_SEC = 600   # owner rewrites the heartbeat every 10 minutes (R16)
STALE_SEC = 900       # a heartbeat older than this = missed beat (10 min + 5 min grace)
CONFIRM_SEC = 20      # re-check window before seizing a stale lock (missed-heartbeat confirmation)

_INSTANCE_ID = uuid.uuid4().hex  # unique per process
_hb_thread: Optional[threading.Thread] = None


def lock_path() -> Path:
    return runlist_dir() / LOCK_NAME


def _identity() -> dict:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "unknown"
    return {"machine": platform.node() or "unknown", "user": user,
            "pid": os.getpid(), "instance": _INSTANCE_ID}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def read_owner() -> Optional[dict]:
    p = lock_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read runlist lock: %s", e)
        return None


def _is_mine(info: Optional[dict]) -> bool:
    return bool(info) and info.get("instance") == _INSTANCE_ID


def _same_principal(info: Optional[dict]) -> bool:
    """Same machine + user as us — the same planner, just a different process.

    Single-writer is enforced per *planner identity*, not per process: two instances on one
    machine under one user are effectively the same person (a leftover window, a relaunch).
    Any of our own processes may therefore (re)claim the lock without the missed-heartbeat
    dance — only a genuinely *foreign* live owner (different machine or user) blocks us.
    """
    if not info:
        return False
    me = _identity()
    return (str(info.get("machine", "")).casefold() == str(me["machine"]).casefold()
            and str(info.get("user", "")).casefold() == str(me["user"]).casefold())


def is_stale(info: Optional[dict], now: Optional[float] = None) -> bool:
    """True if there is no live owner (missing lock or heartbeat older than STALE_SEC)."""
    if not info:
        return True
    now = time.time() if now is None else now
    return (now - float(info.get("heartbeatEpoch", 0))) > STALE_SEC


def own() -> bool:
    return _is_mine(read_owner())


def _write_lock() -> None:
    """Atomically (over)write the lock as owned by us, refreshing the heartbeat."""
    now = time.time()
    cur = read_owner()
    acquired = float(cur["acquiredEpoch"]) if _is_mine(cur) and "acquiredEpoch" in cur else now
    info = _identity()
    info.update({"acquiredEpoch": acquired, "acquiredAt": _iso(acquired),
                 "heartbeatEpoch": now, "heartbeatAt": _iso(now)})
    p = lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(info), encoding="utf-8")
    tmp.replace(p)


def acquire() -> bool:
    """Acquire if the lock is free / stale / already ours. Never seizes a *live* foreign lock.

    Returns whether we own it afterwards.
    """
    info = read_owner()
    if info is None or _is_mine(info) or _same_principal(info) or is_stale(info):
        _write_lock()
        return own()
    return False


def try_takeover(confirm_sec: Optional[float] = None) -> bool:
    """Event-driven acquire for an authoring/publish action (design §14).

    Free / ours / our own machine+user → take it. Live *foreign* owner → fail. Stale foreign
    owner → wait the missed-heartbeat confirmation window and seize only if the heartbeat
    hasn't advanced.
    """
    confirm_sec = CONFIRM_SEC if confirm_sec is None else confirm_sec
    info = read_owner()
    if info is None or _is_mine(info) or _same_principal(info):
        # Our own identity (this process, or another of our windows) — reclaim immediately.
        _write_lock()
        return own()
    if not is_stale(info):
        return False  # a different planner (machine/user) is alive and owns it
    hb0 = info.get("heartbeatEpoch", 0)
    if confirm_sec:
        time.sleep(confirm_sec)
    info2 = read_owner()
    if info2 is None or _is_mine(info2):
        _write_lock()
        return own()
    if is_stale(info2) and info2.get("heartbeatEpoch", 0) == hb0:
        log.info("Seizing stale runlist lock from %s/%s (last beat %s)",
                 info2.get("machine"), info2.get("user"), info2.get("heartbeatAt"))
        _write_lock()
        return own()
    return False  # owner came back to life during the confirm window


def seize() -> bool:
    """Unconditionally claim the lock (last-writer-wins), then return whether we own it.

    Used only when there is **no published runlist** to protect (the first publish ever), so a
    stale or foreign lock left behind must not block getting the floor view started.
    """
    _write_lock()
    return own()


def heartbeat() -> bool:
    """Refresh the heartbeat iff we still own the lock. Returns whether we own it."""
    if own():
        _write_lock()
        return True
    return False


def start_heartbeat() -> None:
    """Start the background heartbeat thread (idempotent). Beats only while we own the lock."""
    global _hb_thread
    if _hb_thread is not None:
        return

    def loop():
        while True:
            time.sleep(HEARTBEAT_SEC)
            try:
                heartbeat()
            except Exception as e:  # noqa: BLE001
                log.warning("Runlist heartbeat failed: %s", e)

    _hb_thread = threading.Thread(target=loop, name="runlist-heartbeat", daemon=True)
    _hb_thread.start()
    log.info("Runlist heartbeat started (every %ss).", HEARTBEAT_SEC)


def release() -> None:
    """Release the lock if we own it (best-effort, for a clean shutdown)."""
    if own():
        try:
            lock_path().unlink()
        except OSError:
            pass
