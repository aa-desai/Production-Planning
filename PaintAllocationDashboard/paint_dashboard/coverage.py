"""
Coverage bucketing + concern classification (design §5.2)
=========================================================
Pure functions that turn a release's allocation rows into the four coverage
buckets and the auto-only concern class shown in the queue.
"""

from __future__ import annotations


def _bucket_rows(rows: list[dict]) -> dict:
    """Bucket a release's alloc rows into coverage buckets (design §5.2)."""
    past = paintable = pipeline = 0
    for r in rows:
        q = int(r.get("Allocated Qty") or 0)
        if r.get("Past Last Paint Op") in (True, "True", "true", 1):
            past += q
        else:
            nxt = str(r.get("Next Operation") or "")
            if "EC" in nxt or "PC" in nxt:
                paintable += q
            else:
                pipeline += q
    return {"pastPaint": past, "paintable": paintable, "pipeline": pipeline}


def concern_from_coverage(cov: dict, rel_bal: int) -> str:
    p, a, l = cov["pastPaint"], cov["paintable"], cov["pipeline"]
    if p >= rel_bal:
        return "good"
    if p + a >= rel_bal:
        return "low"
    if p + a + l >= rel_bal:
        return "medium"
    return "high"


def natural_key(customer, part, ship_iso, rel_bal, dedupe_idx) -> str:
    return f"{customer}__{part}__{ship_iso}__{rel_bal}__{dedupe_idx}"
