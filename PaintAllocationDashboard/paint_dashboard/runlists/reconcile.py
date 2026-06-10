"""
Runlist reconciliation on refresh + heartbeat (design §15, R2)
=============================================================
When the planner re-reads the data (manual Refresh, or the 5-minute reconcile heartbeat),
containers that have been **run** since the last build are removed from the runlist (and
ones that were *partly* run have their run qty reduced). A release stays on the list until
its balance is met — we never drop a whole release, only its individual containers.

A container is treated as **run** when, in the fresh inventory, it has reached **the last
paint op of its target** on its own routing — for the **EC** list, the last EC op; for the
**PC** list, the last PC op (``node.seq ≥ last-op seq``, mirroring the app-wide
"past last paint" test in :func:`payload.ga_is_past_last_paint`) — or its serial is gone
from allocatable inventory. Otherwise, if its on-hand quantity has dropped below the queued
run qty, the item is **reduced** to what's left.

``build_serial_index`` + ``build_last_paint_seqs`` read the fresh ``PipelineResult.graph``
(pandas object) — but the pure ``reconcile_items`` takes plain dicts, so the reconciliation
logic stays testable and the floor viewer never imports any of this.
"""

from __future__ import annotations

from typing import Optional


def build_serial_index(result) -> dict:
    """``serial -> {seq, qty, part}`` for every container attached in the fresh graph."""
    idx: dict[str, dict] = {}
    for node in result.graph.nodes.values():
        for c in node.containers:
            idx[str(c.serial)] = {"seq": node.seq, "qty": int(c.quantity), "part": c.part}
    return idx


def build_last_paint_seqs(result) -> tuple[dict, dict]:
    """``(last_ec_seq, last_pc_seq)`` per part — the flow-seq of the LAST EC / PC routing op.

    These are the per-target removal gates: a runlist container at/past its part's last EC
    (resp. PC) op has been e-coated (resp. powder-coated) and drops off that list.
    """
    last_ec: dict[str, int] = {}
    last_pc: dict[str, int] = {}
    for (part, op), node in result.graph.nodes.items():
        # Case-sensitive like the engine's last_paint_seq: real paint ops are "EC-…"/"PC-…".
        # Upper-casing would mis-count ops like "Inspection"/"Receive" (lowercase "ec") as EC.
        o = str(op)
        if "EC" in o and node.seq > last_ec.get(part, -1):
            last_ec[part] = node.seq
        if "PC" in o and node.seq > last_pc.get(part, -1):
            last_pc[part] = node.seq
    return last_ec, last_pc


def reconcile_items(items: list[dict], serial_index: dict,
                    last_op_by_part: Optional[dict] = None) -> tuple[list[dict], dict]:
    """Drop run containers, reduce partially-run ones. Returns ``(kept_items, report)``.

    ``last_op_by_part`` maps a container's part → the flow-seq of the last paint op for this
    target (last EC op for the EC list, last PC op for the PC list). A container whose current
    seq is **at or past** that op is treated as run. When the map is absent or has no entry for
    the part, we fall back to the queued paint op (strictly-past) so reconciliation is still safe.
    """
    last_op_by_part = last_op_by_part or {}
    out: list[dict] = []
    report = {"removed": 0, "reduced": 0, "kept": 0, "runQtyRemoved": 0, "removedSerials": []}
    for it in items:
        serial = str(it.get("serial"))
        aq = int(it.get("allocQty") or 0)
        info = serial_index.get(serial)
        if info is None:                                   # gone from inventory → run
            report["removed"] += 1
            report["runQtyRemoved"] += aq
            report["removedSerials"].append(serial)
            continue
        gate = last_op_by_part.get(info.get("part"))
        if gate is not None:
            past = info["seq"] >= int(gate)                # at/past the last EC/PC op → run
        else:
            qps = it.get("queuedPaintSeq")
            past = qps is not None and info["seq"] > int(qps)
        if past:
            report["removed"] += 1
            report["runQtyRemoved"] += aq
            report["removedSerials"].append(serial)
            continue
        avail = int(info["qty"])
        if avail <= 0:
            report["removed"] += 1
            report["runQtyRemoved"] += aq
            report["removedSerials"].append(serial)
            continue
        if avail < aq:                                     # partially run → reduce to what's left
            d = dict(it)
            d["allocQty"] = avail
            out.append(d)
            report["reduced"] += 1
            report["runQtyRemoved"] += (aq - avail)
        else:
            out.append(it)
            report["kept"] += 1
    return out, report


def reconcile_doc(doc: dict, serial_index: dict,
                  last_ec: Optional[dict] = None, last_pc: Optional[dict] = None) -> tuple[dict, dict]:
    """Reconcile both targets of a runlist document in place. Returns ``(doc, report)``.

    PC items are gated by the last PC op (``last_pc``); EC items by the last EC op (``last_ec``).
    """
    report: dict = {}
    doc["pc"], report["pc"] = reconcile_items(doc.get("pc", []), serial_index, last_pc)
    doc["ec"], report["ec"] = reconcile_items(doc.get("ec", []), serial_index, last_ec)
    return doc, report
