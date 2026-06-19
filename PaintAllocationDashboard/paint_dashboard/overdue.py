"""
Overdue release detection + Volvo churn snapshots (dashboard layer)
===================================================================
Post-processes the engine's ``releases_with_id`` frame WITHOUT touching the
vendored allocation engine. It adds two things the planner queue needs:

* a per-release ``Overdue`` flag (drives the faint red wash in the queue), and
* a daily *Volvo Trucks* snapshot pool used to detect releases that Volvo
  "rolled" a day later (schedule churn).

``Overdue`` is the OR of:

* **4.1 (global, all customers):** the (P6-shifted) ``Ship Date`` is before today.
* **4.3 (global):** two or more releases share
  ``(Customer, Part Number, Ship To, Ship Date)`` after the shift -- we cannot
  tell which quantity came from which day, so *both* are flagged.
* **4.2 (Volvo, computed + logged only -- NOT wired into the flag yet):** the
  ``(Part Number, Ship To)`` is in ``volvo_late`` (see :func:`_run_churn`). This
  needs two days of snapshots and is being validated before it paints rows.

P6 (``Release Plant == "P6"``) ship dates are reduced by one calendar day to
reflect internal lead time. This is **display / overdue only** -- the vendored
engine's FIFO allocation still uses the original dates.

Everything here is *best-effort*: the caller wraps :func:`annotate` so any failure
degrades to "no overdue flags", and the snapshot/churn step is independently guarded
so a missing/locked shared folder (or day one, with no previous snapshot) can never
break a refresh.

Design + build log: ``DESIGN.md`` / ``PROGRESS.md``.
"""

from __future__ import annotations

import glob
import json
import os
import tempfile
from datetime import date, timedelta

import pandas as pd

from . import log
from .config import shared_dir

VOLVO_CUSTOMER = "Volvo Trucks"
P6_PLANT = "P6"
FWD_WINDOW_DAYS = 4          # forward outlook to bridge a weekend (Thu pull reaches Mon)
_KEEP_SNAPSHOTS = 2          # keep only current + previous pull's snapshot


# ---- Volvo snapshot store (shared, date-keyed, atomic) -----------------------
def _churn_dir() -> str:
    """``<shared>\\Snapshots\\volvo_churn`` -- the date-keyed Volvo snapshot pool."""
    return os.path.join(str(shared_dir()), "Snapshots", "volvo_churn")


def _iso(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _read_snap(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_snap_atomic(path: str, data: dict) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _prune(dirpath: str, keep: int = _KEEP_SNAPSHOTS) -> None:
    files = sorted(glob.glob(os.path.join(dirpath, "*.json")))  # date-named -> lexical == chronological
    for old in files[:-keep]:
        try:
            os.remove(old)
        except OSError:
            pass


def _latest_prev_snapshot(dirpath: str, today: date) -> dict | None:
    """Most recent snapshot with a pull date strictly before *today* (may be days
    back -- e.g. Monday's previous is Thursday's, which the 4-day window covers)."""
    best = None
    best_date = None
    for path in glob.glob(os.path.join(dirpath, "*.json")):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            d = date.fromisoformat(name)
        except ValueError:
            continue
        if d < today and (best_date is None or d > best_date):
            snap = _read_snap(path)
            if snap is not None:
                best, best_date = snap, d
    return best


def _volvo_window_rows(rel: pd.DataFrame, today: date) -> list[dict]:
    """Volvo-Trucks (Part No, Ship To, Ship Date) keys for ship dates in
    [today-1 .. today+4] -- the slice we persist each day."""
    lo, hi = today - timedelta(days=1), today + timedelta(days=FWD_WINDOW_DAYS)
    out: list[dict] = []
    v = rel[rel["Customer"].astype(str) == VOLVO_CUSTOMER]
    for r in v.to_dict("records"):
        sd = r.get("Ship Date")
        if pd.isna(sd):
            continue
        try:
            if not (lo <= sd <= hi):
                continue
        except TypeError:
            continue
        out.append({
            "part": str(r.get("Part Number", "")),
            "shipTo": str(r.get("Ship To", "") or ""),
            "ship": _iso(sd),
        })
    return out


def _keyset(rows: list[dict], due: date) -> set:
    """(part, shipTo) keys whose ship date == *due*."""
    iso = due.isoformat()
    return {(r["part"], r["shipTo"]) for r in rows if r.get("ship") == iso}


def _run_churn(curr_rows: list[dict], prev_snap: dict, today: date) -> set:
    """Detect Volvo releases that rolled a day later (design: churn pipeline).

    * ``missing_yday``  = in prev[due today-1] but gone from curr[due today-1].
    * ``appeared_today``= in curr[due today]   but absent from prev[due today].
    * ``volvo_late``    = their intersection on (Part No, Ship To).

    Quantities are ignored. Returns ``volvo_late`` (logged this release; not yet
    wired into the ``Overdue`` flag)."""
    prev_rows = prev_snap.get("rows", [])
    yday = today - timedelta(days=1)
    missing_yday = _keyset(prev_rows, yday) - _keyset(curr_rows, yday)
    appeared_today = _keyset(curr_rows, today) - _keyset(prev_rows, today)
    return missing_yday & appeared_today


def _snapshot_and_churn(rel: pd.DataFrame, today: date) -> None:
    """First run of the local day only: persist today's Volvo snapshot and (if a
    previous snapshot exists) compute + log ``volvo_late``. Later runs the same day
    no-op (the file already exists)."""
    d = _churn_dir()
    today_path = os.path.join(d, f"{today.isoformat()}.json")
    if os.path.exists(today_path):
        return  # already snapshotted today -> churn runs once per day

    rows = _volvo_window_rows(rel, today)
    prev = _latest_prev_snapshot(d, today)  # read BEFORE writing today's file
    _write_snap_atomic(today_path, {"pullDate": today.isoformat(), "rows": rows})
    _prune(d)

    if prev is None:
        log.info("Volvo churn: no previous snapshot yet (day one) -- saved %d rows, churn skipped",
                 len(rows))
        return
    late = _run_churn(rows, prev, today)
    log.info("Volvo churn: prev=%s -> volvo_late=%d %s (not yet washing)",
             prev.get("pullDate"), len(late), sorted(late)[:20])


# ---- overdue flag ------------------------------------------------------------
def _compute_overdue(rel: pd.DataFrame, today: date) -> pd.Series:
    """4.1 (past-due, global) OR 4.3 (duplicate same-date release, both flagged).

    Nothing **due in the future** is ever overdue — the flag is gated to releases due
    today or earlier, so a future-dated same-date duplicate (e.g. a Volvo 6/24 pair)
    is not washed."""
    sd = rel["Ship Date"]
    due = sd.map(lambda d: (not pd.isna(d)) and d <= today)   # due today or earlier
    past = sd.map(lambda d: (not pd.isna(d)) and d < today)

    keycols = ["Customer", "Part Number", "Ship To", "Ship Date"]
    dup = rel.groupby(keycols, dropna=False)["Release ID"].transform("size") >= 2

    return (due & (past | dup)).fillna(False).astype(bool)


def annotate(result, today: date | None = None) -> pd.DataFrame:
    """Return a copy of ``result.releases_with_id`` with a P6-shifted ``Ship Date``,
    an ``Overdue`` flag, and a guaranteed ``Ship To`` column -- and, as a side effect,
    capture the day's Volvo snapshot + churn. The vendored engine is not touched."""
    today = today or date.today()
    rel = result.releases_with_id.copy()
    if "Ship To" not in rel.columns:
        rel["Ship To"] = ""

    # Volvo snapshot + churn use the ORIGINAL (customer-stated) ship dates.
    try:
        _snapshot_and_churn(rel, today)
    except Exception as e:  # noqa: BLE001 -- best-effort; must never break a refresh
        log.warning("Volvo churn step skipped: %s", e)

    # P6 internal lead-time shift (display / overdue only; allocation keeps originals).
    p6 = rel["Release Plant"].astype(str) == P6_PLANT
    rel.loc[p6, "Ship Date"] = rel.loc[p6, "Ship Date"].map(
        lambda d: (d - timedelta(days=1)) if not pd.isna(d) else d
    )

    rel["Overdue"] = _compute_overdue(rel, today)
    return rel
