"""
Runlist draft authoring + publish (design §11, §16)
===================================================
Pure operations over the **draft** runlist document (the planner's working copy) plus the
**publish** step that copies the draft to the shared live file — gated by the writer lock.

Kept stdlib-only and dependency-injected (callers pass already-resolved :class:`RunItem`s),
so this module never imports the pipeline/pandas. Selection→item resolution, the qty popup,
the over-allocation cascade (P4) and the PC→EC deficit (P5) live in the planner server layer
and feed resolved items in here.
"""

from __future__ import annotations

from typing import Optional

from .. import __version__
from . import lock, store
from .model import SOURCE_AUTO_EC, SOURCE_MANUAL, RunItem, items_from_doc, new_doc

# Fields a push request may supply per container; the server stamps runItemId / pushedAt /
# source itself (never trusts the client for those).
_INPUT_FIELDS = ("partNo", "serial", "location", "allocQty", "releaseId",
                 "customer", "shipDate", "powderColour", "part", "queuedPaintSeq")


def _assign(it: dict, rel: dict, qty: int) -> dict:
    d = dict(it)
    d["allocQty"] = int(qty)
    d["releaseId"] = rel["releaseId"]
    d["customer"] = rel.get("customer", d.get("customer", ""))
    d["shipDate"] = rel.get("shipDate", d.get("shipDate", ""))
    return d


def cascade_items(items: list[dict], releases_fifo: list[dict], placed: dict) -> tuple[list[dict], dict]:
    """Distribute pushed container qty across same-part releases in FIFO order (design §12, R7).

    Fills the selected release up to its remaining balance, then spills the surplus into the
    next same-part releases (capping each at its balance) — splitting the boundary container
    into multiple run-items. Under-allocation is untouched. Any remainder beyond every
    release's balance is **never dropped**: it stays on the last release and is reported.

    Args:
        items: pushed container dicts (``allocQty``, ``serial``, ``releaseId``, …), in order.
        releases_fifo: ``[{releaseId, relBal, customer, shipDate}]`` starting at the selected
            release, then subsequent same-part releases in ship-date FIFO order.
        placed: ``{releaseId: qty already in the draft for this target}`` (reduces capacity).
    """
    report = {"cascaded": 0, "overflow": 0, "releasesUsed": []}
    if not releases_fifo:
        return list(items), report
    caps = {r["releaseId"]: max(int(r["relBal"]) - int(placed.get(r["releaseId"], 0)), 0)
            for r in releases_fifo}
    first_id = releases_fifo[0]["releaseId"]
    out: list[dict] = []
    used: list = []
    ri = 0
    cap = caps[first_id]
    for it in items:
        qty = int(it.get("allocQty") or 0)
        if qty <= 0:
            continue
        while qty > 0 and ri < len(releases_fifo):
            if cap <= 0:
                ri += 1
                if ri >= len(releases_fifo):
                    break
                cap = caps[releases_fifo[ri]["releaseId"]]
                continue
            r = releases_fifo[ri]
            take = min(qty, cap)
            out.append(_assign(it, r, take))
            if r["releaseId"] not in used:
                used.append(r["releaseId"])
            if r["releaseId"] != first_id:
                report["cascaded"] += take
            qty -= take
            cap -= take
        if qty > 0:  # no balance left anywhere — keep it (never drop), report overflow
            r = releases_fifo[-1]
            out.append(_assign(it, r, qty))
            if r["releaseId"] not in used:
                used.append(r["releaseId"])
            report["overflow"] += qty
    report["releasesUsed"] = used
    return out, report


def run_item_from_input(target: str, d: dict, source: str = SOURCE_MANUAL) -> RunItem:
    """Build a :class:`RunItem` from a push-request container dict (sanitized).

    ``source`` defaults to manual; pass ``SOURCE_AUTO_EC`` for PC→EC deficit auto-adds.
    """
    target = target.lower()
    if target not in ("pc", "ec"):
        raise ValueError("target must be 'pc' or 'ec'")
    kw = {k: d.get(k) for k in _INPUT_FIELDS if k in d}
    kw["target"] = target
    kw["partNo"] = str(kw.get("partNo") or "")
    kw["serial"] = str(kw.get("serial") or "")
    kw["location"] = str(kw.get("location") or "")
    kw["allocQty"] = int(kw.get("allocQty") or 0)
    kw["source"] = source
    return RunItem(**kw)


def eligible_items(detail: dict, target: str, items: list[dict]) -> tuple[list[dict], int]:
    """Drop containers already **in or past** the target paint op (design §11, R17).

    A push only takes containers that still *need* the op: **PC** drops any selected container
    that is in/past a PC op, **EC** drops any in/past an EC op. Eligibility is judged by the
    container's current op ``seq`` vs. the **earliest** matching paint op on that container's own
    routing level (sub-routings are gated by their own EC/PC op, not the parent's). A routing
    with no such paint op gates nothing. Pure over the detail tree from ``build_detail_tree``.

    Returns ``(kept_items, skipped_count)``.
    """
    tok = "PC" if str(target).lower() == "pc" else "EC" if str(target).lower() == "ec" else ""
    if not tok or not detail:
        return list(items), 0

    # serial -> (current op seq, gate = earliest `tok`-op seq on that serial's routing level).
    gates: dict = {}

    def _walk(node: dict) -> None:
        ops = node.get("ops", [])
        # Match the engine's CASE-SENSITIVE paint-op test: real paint ops are "EC-…"/"PC-…"
        # (uppercase prefix). Upper-casing here would wrongly treat ops like "Inspection" or
        # "Receive" (lowercase "ec") as EC ops and block the op right before real e-coat.
        tok_seqs = [o["seq"] for o in ops if tok in str(o.get("op", ""))]
        gate = min(tok_seqs) if tok_seqs else None
        for o in ops:
            for c in o.get("containers", []):
                gates[str(c.get("serial"))] = (o["seq"], gate)
            for sub in o.get("subRoutings", []):
                _walk(sub)

    _walk(detail)
    kept: list[dict] = []
    skipped = 0
    for it in items:
        sg = gates.get(str(it.get("serial")))
        if sg is not None and sg[1] is not None and sg[0] >= sg[1]:
            skipped += 1            # in or past the target paint op → never repaint
            continue
        kept.append(it)
    return kept, skipped


def ec_deficit_items(detail: dict, pc_run_qty: int, release: dict) -> tuple[list[dict], dict]:
    """PC→EC deficit auto-fill (design §13, R4).

    Only for a release part whose routing has **both** an EC and a PC op (EC before PC). The
    PC run needs feedstock that has already been e-coated; "PC-ready" qty = allocated qty at
    ops from the EC op up to (not incl.) the PC op. If the PC run qty exceeds that, walk the
    still-needs-EC containers (ops before the EC op) in allocation order and emit EC run-items
    to cover the deficit (splitting the last). Returns ``(ec_item_dicts, report)``.

    Pure: ``detail`` is the (pandas-free) detail tree from ``build_detail_tree``.
    """
    ops = detail.get("ops", []) if detail else []
    # Case-sensitive like the engine (real paint ops are "EC-…"/"PC-…"); see eligible_items.
    ec_seqs = [o["seq"] for o in ops if "EC" in str(o.get("op", ""))]
    pc_seqs = [o["seq"] for o in ops if "PC" in str(o.get("op", ""))]
    if not ec_seqs or not pc_seqs:
        return [], {"applicable": False}
    ec_seq, pc_seq = min(ec_seqs), min(pc_seqs)
    if ec_seq >= pc_seq:
        return [], {"applicable": False}

    pc_ready = sum(int(c.get("allocatedHere") or 0)
                   for o in ops if ec_seq <= o["seq"] < pc_seq
                   for c in o.get("containers", []))
    deficit = max(int(pc_run_qty) - pc_ready, 0)
    if deficit <= 0:
        return [], {"applicable": True, "deficit": 0, "pcReady": pc_ready}

    items: list[dict] = []
    need = deficit
    for o in sorted(ops, key=lambda o: o["seq"]):     # allocation order: upstream-first
        if o["seq"] >= ec_seq:
            continue
        for c in o.get("containers", []):
            q = int(c.get("allocatedHere") or 0)
            if q <= 0 or need <= 0:
                continue
            take = min(q, need)
            need -= take
            items.append({"partNo": c.get("part"), "serial": c.get("serial"),
                          "location": c.get("location"), "allocQty": take,
                          "releaseId": release.get("releaseId"), "customer": release.get("customer"),
                          "shipDate": release.get("shipDate"), "powderColour": "",
                          "part": c.get("part"), "queuedPaintSeq": ec_seq})
    return items, {"applicable": True, "deficit": deficit, "pcReady": pc_ready,
                   "covered": deficit - max(need, 0), "shortfall": max(need, 0)}


def load_draft() -> dict:
    """The current draft document, or a fresh empty one."""
    return store.read_draft() or new_doc([], [], app_version=__version__)


def save_draft(draft: dict) -> None:
    store.write_draft(draft)


def add_items(draft: dict, target: str, items: list[RunItem]) -> dict:
    """Append resolved run-items to a target list (order preserved). Mutates + returns draft."""
    target = target.lower()
    if target not in ("pc", "ec"):
        raise ValueError("target must be 'pc' or 'ec'")
    draft.setdefault(target, [])
    draft[target] = list(draft[target]) + [it.to_dict() for it in items]
    return draft


def reorder(draft: dict, target: str, order_ids: list) -> dict:
    """Reorder a target's items to match *order_ids* (run-item ids). Items not listed keep
    their relative order at the end (safety). Mutates + returns draft."""
    target = target.lower()
    items = draft.get(target, [])
    by_id = {d.get("runItemId"): d for d in items}
    seen: set = set()
    new: list = []
    for rid in order_ids:
        d = by_id.get(rid)
        if d is not None and rid not in seen:
            new.append(d)
            seen.add(rid)
    for d in items:
        if d.get("runItemId") not in seen:
            new.append(d)
    draft[target] = new
    return draft


def remove_item(draft: dict, run_item_id: str) -> dict:
    for t in ("pc", "ec"):
        draft[t] = [d for d in draft.get(t, []) if d.get("runItemId") != run_item_id]
    return draft


def acknowledge(draft: dict, run_item_id: str, value: bool = True) -> bool:
    """Mark a draft run-item acknowledged (planner reviewed an auto-added EC, §13).

    Returns whether a matching item was found. Mutates the draft in place.
    """
    for t in ("pc", "ec"):
        for d in draft.get(t, []):
            if d.get("runItemId") == run_item_id:
                d["acknowledged"] = bool(value)
                return True
    return False


def clear(draft: dict, target: Optional[str] = None) -> dict:
    for t in (("pc", "ec") if target is None else (target,)):
        draft[t] = []
    return draft


def reset_to_live(draft: dict, target: Optional[str] = None) -> dict:
    """Revert a target's draft list to the **live** published runlist (design §16, Reset).

    Discards the planner's unpublished reordering/edits for that target and restores exactly
    what the floor currently sees. ``target=None`` resets both. Mutates + returns the draft.
    """
    live = store.read_live() or {}
    for t in (("pc", "ec") if target is None else (target,)):
        draft[t] = [dict(d) for d in live.get(t, [])]
    return draft


def _owner_meta() -> dict:
    o = lock.read_owner() or {}
    return {k: o.get(k) for k in ("machine", "user", "instance")}


def publish(draft: dict) -> dict:
    """Publish draft → live, if we hold (or can take over) the writer lock.

    Returns ``{"ok": True, "publishedAt", "counts"}`` on success, or
    ``{"ok": False, "reason": "locked", "owner": {...}}`` if another instance owns it.
    """
    # If nothing is published yet there's no floor view to protect — take the lock outright so a
    # stale/foreign lock can't block the very first publish. Otherwise the normal takeover rules
    # apply (a live foreign owner blocks us).
    if store.read_live() is None:
        lock.seize()
    elif not lock.try_takeover():
        owner = lock.read_owner() or {}
        return {"ok": False, "reason": "locked",
                "owner": {k: owner.get(k) for k in ("machine", "user", "heartbeatAt")}}
    live = new_doc(items_from_doc(draft, "pc"), items_from_doc(draft, "ec"),
                   app_version=__version__, owner=_owner_meta())
    store.write_live(live)
    lock.start_heartbeat()
    return {"ok": True, "publishedAt": live["publishedAt"],
            "counts": {"pc": len(live["pc"]), "ec": len(live["ec"])}}
