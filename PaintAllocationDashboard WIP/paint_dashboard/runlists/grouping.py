"""
PC runlist grouping (design §8, §17)
====================================
Pure helper that turns an ordered list of PC :class:`RunItem` into the
``Current colour → Releases → containers`` shape the PC floor page renders, preserving
the runlist's order at every level (colours, releases, and items appear in
first-encountered order) and rolling up ``allocQty`` totals.

Stdlib-only (no pandas/engine) so the floor viewer can use it directly.
"""

from __future__ import annotations

from .model import RunItem


def group_pc(items: list[RunItem]) -> list[dict]:
    """Group ordered PC run-items into ``[{colour, qty, releases:[{..., items:[]}]}]``.

    Order is preserved: a colour/release appears at the position of its first item.
    Releases are keyed by ``releaseId`` (falling back to the part when absent).
    """
    out: list[dict] = []
    by_colour: dict[str, dict] = {}
    for it in items:
        col = it.powderColour or "Unknown"
        c = by_colour.get(col)
        if c is None:
            c = {"colour": col, "qty": 0, "releases": [], "_rel": {}}
            by_colour[col] = c
            out.append(c)
        rkey = it.releaseId if it.releaseId is not None else "part:" + str(it.part)
        r = c["_rel"].get(rkey)
        if r is None:
            r = {
                "releaseId": it.releaseId,
                "customer": it.customer,
                "part": it.part,
                "shipDate": it.shipDate,
                "qty": 0,
                "items": [],
            }
            c["_rel"][rkey] = r
            c["releases"].append(r)
        qty = int(it.allocQty or 0)
        r["items"].append(it.to_dict())
        r["qty"] += qty
        c["qty"] += qty
    for c in out:
        del c["_rel"]  # internal index, not part of the rendered shape
    return out
