"""
Payload + detail builders (design §3, §4, §5)
=============================================
Read-only dashboard (design v10): concern is auto-only, no overrides, no writable
shared state. Everything here is derived from the in-memory :class:`PipelineResult`
and served to the browser — the ship-date queue payload and the on-demand routing
detail tree.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

import pandas as pd

from . import __version__
from .coverage import _bucket_rows, concern_from_coverage, natural_key
from .datasource import latest_raw_data_mtime
from .engine import graph_allocator_v2 as ga
from .indexes import Indexes
from .pipeline import PipelineResult
from .serialization import _jsonsafe, _ship_iso
from .swatches import paint_badge

# Set on each pipeline run so ``ga_is_past_last_paint`` can read ``last_paint_seq``
# without threading the graph through every card-building call.
CURRENT_GRAPH: Optional["ga.Graph"] = None


def set_current_graph(graph: Optional["ga.Graph"]) -> None:
    """Point the module-level graph at the latest pipeline result (called on refresh)."""
    global CURRENT_GRAPH
    CURRENT_GRAPH = graph


def ga_is_past_last_paint(part: str, seq: int) -> bool:
    lp = CURRENT_GRAPH.last_paint_seq.get(part) if CURRENT_GRAPH else None
    return bool(lp is not None and seq >= lp)


# "Inventory at P10" filter: a container is "at P10" if it is P10-owned, or it is
# a P6 container that has physically transferred to the P10 location (the same
# "Modineer - P10" location test the trusted elim_p6_releases used).
P10_PLANT = "P10"
P10_LOCATION = "Modineer - P10"


def _container_at_p10(c: "ga.Container") -> bool:
    return str(c.container_plant) == P10_PLANT or str(c.location) == P10_LOCATION


def build_queue_payload(result: PipelineResult, idx: Indexes,
                        releases_override: "Optional[object]" = None) -> dict:
    """releases[] for the Release Queue, ship-date ASC (design §3.1).

    ``releases_override`` (a dashboard-annotated copy of ``releases_with_id`` from
    :mod:`paint_dashboard.overdue`) carries the P6-shifted ``Ship Date``, a
    ``Ship To`` column and an ``Overdue`` flag. When absent (annotate failed), we
    fall back to the raw engine frame and rows simply have ``overdue=False``.
    """
    flag_lookup = result.paint_flags.set_index("Part Number")
    rel = (releases_override if releases_override is not None
           else result.releases_with_id).copy()
    rel["_ship_iso"] = rel["Ship Date"].map(_ship_iso)
    rel = rel.sort_values(["Ship Date", "Customer", "Part Number"], kind="stable")

    # dedupeIdx within identical (customer, part, ship, relBal)
    seen: dict = defaultdict(int)
    releases = []
    parents_with_children = set(idx.internal_to_top.values())

    # Precompute, per release part, whether ANY container in the part's entire
    # routing subtree (own routing + recursively-consumed components) sits at P10.
    # One pass to find parts that hold P10 inventory; then a cached subtree test.
    graph = result.graph
    parts_with_p10_inv = {
        n.part for n in graph.nodes.values()
        if any(_container_at_p10(c) for c in n.containers)
    }
    _p10_cache: dict[str, bool] = {}

    def _subtree_has_p10(part: str) -> bool:
        if part not in _p10_cache:
            reach = ga.reachable_parts(graph, {part})
            _p10_cache[part] = bool(reach & parts_with_p10_inv)
        return _p10_cache[part]

    # serial -> inventory Add Date, for the per-release add-date range shown in the queue.
    serial_add: dict = {}
    for n in graph.nodes.values():
        for c in n.containers:
            ad = getattr(c, "add_date", None)
            if ad is None:
                continue
            try:
                ts = pd.Timestamp(ad)
            except (ValueError, TypeError):
                continue
            if not pd.isna(ts):
                serial_add[str(c.serial)] = ts

    for r in rel.to_dict("records"):
        rid = int(r["Release ID"])
        part = r["Part Number"]
        cust = str(r.get("Customer", ""))
        ship = r["_ship_iso"]
        rel_bal = int(r["Rel Bal"])
        dk = (cust, part, ship, rel_bal)
        ddx = seen[dk]
        seen[dk] += 1
        nk = natural_key(cust, part, ship, rel_bal, ddx)

        rows = idx.alloc_by_top.get(rid, [])
        add_dates = [serial_add[s] for s in
                     {str(rr.get("Serial No")) for rr in rows} if s in serial_add]
        add_lo = min(add_dates).strftime("%Y-%m-%d") if add_dates else None
        add_hi = max(add_dates).strftime("%Y-%m-%d") if add_dates else None
        cov = _bucket_rows(rows)
        cov["short"] = max(rel_bal - cov["pastPaint"] - cov["paintable"] - cov["pipeline"], 0)
        concern = concern_from_coverage(cov, rel_bal)

        ec = bool(flag_lookup["Ecoat"].get(part, False))
        pc = bool(flag_lookup["Powdercoat"].get(part, False))
        colour = flag_lookup["Powder Colour"].get(part, "None")
        badge = paint_badge(ec, pc, colour, idx.swatch_map)

        releases.append({
            "naturalKey": nk,
            "releaseId": rid,
            "releasePlant": str(r.get("Release Plant", "") or ""),
            "customer": cust,
            "part": part,
            "shipTo": str(r.get("Ship To", "") or ""),
            "shipDate": ship,
            "addDateLo": add_lo,
            "addDateHi": add_hi,
            "relBal": rel_bal,
            "overdue": bool(r.get("Overdue", False)),
            "p10Inventory": _subtree_has_p10(part),
            "coverage": cov,
            "concernAuto": concern,
            "paintBadge": badge,
            "hasPaintedSubcomponents": rid in parents_with_children,
        })

    # Ship-date ASC (primary), then OLDEST inventory add date first within each ship-date
    # block; releases with no add date sort last. ("" ship/add -> high sentinel = last.)
    releases.sort(key=lambda x: (x["shipDate"] or "9999-99-99",
                                 x["addDateLo"] or "9999-99-99",
                                 x["customer"], x["part"]))

    customers = sorted({r["customer"] for r in releases if r["customer"]})
    return {
        "appVersion": __version__,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataPulledAt": latest_raw_data_mtime(),
        "releaseCount": len(releases),
        "releases": releases,
        "customers": customers,
        "readOnly": True,
    }


# ---- on-demand detail tree (design §3.2, §4.2, §4.4) ----------------------
def _container_card(c: "ga.Container", node: "ga.Node", alloc_rows_by_serial: dict,
                    alloc_total_by_serial: dict) -> dict:
    serial = str(c.serial)
    allocated_here = int(alloc_rows_by_serial.get(serial, 0))
    # "Allocated elsewhere" = this physical container is consumed by some OTHER release
    # (its total allocation across all releases exceeds what this release takes here). Drives
    # the greying in the selected-release view (R20).
    allocated_total = int(alloc_total_by_serial.get(serial, 0))
    past = ga_is_past_last_paint(node.part, node.seq)
    return {
        "serial": serial,
        "part": c.part,
        "location": str(c.location),
        "qty": int(c.quantity),
        "allocatedHere": allocated_here,
        "allocatedElsewhere": bool(allocated_total - allocated_here > 0),
        "pastPaint": bool(past),
        "addDate": _jsonsafe(c.add_date),
        "containerPlant": str(c.container_plant),
        "nextOp": str(c.next_operation),
        "isReworkMrb": False,
    }


def _routing_chain(graph: "ga.Graph", part: str) -> list["ga.Node"]:
    """Ops final-first (top of pane), following upstream routing edges."""
    node = graph.final_op.get(part)
    chain = []
    while node is not None:
        chain.append(node)
        node = node.upstream
    return chain  # final .. first


def build_detail_tree(result: PipelineResult, idx: Indexes, release_id: int,
                      rel_bal: int, depth: int = 0) -> Optional[dict]:
    graph = result.graph
    # find the part for this release id (external or internal)
    if release_id in idx.ext_by_id:
        part = idx.ext_by_id[release_id]["Part Number"]
    else:
        irow = result.internal_df[result.internal_df["Release ID"] == release_id]
        if irow.empty:
            return None
        part = irow.iloc[0]["Part Number"]

    chain = _routing_chain(graph, part)
    if not chain:
        return None

    # first paint seq for collapse default
    paint_seqs = [n.seq for n in chain if ("EC" in str(n.operation) or "PC" in str(n.operation))]
    first_paint_seq = min(paint_seqs) if paint_seqs else None

    # this release's allocations indexed by (op, serial)
    rows = idx.alloc_by_relid.get(release_id, [])
    alloc_by_op_serial: dict = defaultdict(dict)
    for r in rows:
        alloc_by_op_serial[str(r.get("Operation Code"))][str(r.get("Serial No"))] = \
            alloc_by_op_serial[str(r.get("Operation Code"))].get(str(r.get("Serial No")), 0) \
            + int(r.get("Allocated Qty") or 0)

    # internal releases (sub-routings) consumed at each op of THIS release
    subs_by_op: dict = defaultdict(list)
    if not result.internal_df.empty:
        kids = result.internal_df[result.internal_df["Parent Release ID"] == release_id]
        for k in kids.to_dict("records"):
            subs_by_op[str(k.get("Consumed At Op"))].append(k)

    ops_payload = []
    for n in chain:
        op = str(n.operation)
        is_paint = ("EC" in op) or ("PC" in op)
        serial_alloc = alloc_by_op_serial.get(op, {})
        cards = [_container_card(c, n, serial_alloc, idx.alloc_qty_by_serial)
                 for c in n.containers]
        # Order within the op: allocated-to-this-release first, then free (unallocated),
        # then containers allocated to other releases (greyed) last — stable otherwise (R21).
        cards.sort(key=lambda c: (0 if c["allocatedHere"] > 0 else 1,
                                  1 if c["allocatedElsewhere"] else 0))
        # rework/mrb display-only
        rwk = idx.rework_by_partop.get((part, op), [])
        rework_cards = [{
            "serial": str(x.get("Serial No", "")),
            "part": x.get("Part Number"),
            "location": str(x.get("Location", "")),
            "qty": int(x.get("Quantity") or 0),
            "allocatedHere": 0,
            "allocatedElsewhere": False,
            "pastPaint": False,
            "addDate": _jsonsafe(x.get("Add Date")),
            "containerPlant": str(x.get("Container Plant", "")),
            "nextOp": str(x.get("Next Operation", "")),
            "isReworkMrb": True,
            "status": str(x.get("Container Status", "")),
        } for x in rwk]

        net = sum(c["allocatedHere"] for c in cards)
        pp_qty = sum(c["allocatedHere"] for c in cards if c["pastPaint"])
        tot = sum(c["allocatedHere"] for c in cards) or 0
        pp_share = (pp_qty / tot) if tot else 0.0

        collapsed = (first_paint_seq is not None and n.seq < first_paint_seq - 1)

        # sub-routings consumed here
        sub_trees = []
        for k in subs_by_op.get(op, []):
            child_id = int(k["Release ID"])
            child_bal = int(k.get("Rel Bal") or 0)
            child_tree = build_detail_tree(result, idx, child_id, child_bal, depth + 1)
            if child_tree is not None:
                child_tree["consumedAtOp"] = op
                child_tree["bomScaledNet"] = child_bal
                sub_trees.append(child_tree)

        ops_payload.append({
            "op": op,
            "seq": n.seq,
            "isPaintOp": is_paint,
            "netQty": net,
            "collapsed": collapsed,
            "pastPaintShare": round(pp_share, 3),
            "containers": cards,
            "reworkCards": rework_cards,
            "reworkQty": sum(c["qty"] for c in rework_cards),
            "subRoutings": sub_trees,
        })

    # coverage for this (sub)release for the header bar
    top_rows = idx.alloc_by_top.get(release_id, rows)
    cov = _bucket_rows(top_rows if release_id in idx.ext_by_id else rows)
    cov["short"] = max(rel_bal - cov["pastPaint"] - cov["paintable"] - cov["pipeline"], 0)

    return {
        "partNo": part,
        "releaseId": release_id,
        "relBal": rel_bal,
        "coverage": cov,
        "concernAuto": concern_from_coverage(cov, rel_bal),
        "ops": ops_payload,
    }
