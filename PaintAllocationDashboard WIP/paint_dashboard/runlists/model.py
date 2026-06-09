"""
Runlist data model (design §10)
===============================
A :class:`RunItem` is the unit of a runlist. The floor sees only ``partNo / serial /
location / allocQty``; the rest is internal bookkeeping (lineage, the paint op this item
is queued for — used by reconciliation — and whether it was auto-pulled to cover a PC→EC
deficit).

A published/draft *document* is a plain dict (JSON-friendly): an ordered ``pc`` list and
an ordered ``ec`` list of run-item dicts, plus a little metadata. PC grouping
(colour → release) is derived from item fields at render time, preserving list order;
explicit per-level ordering arrives with the reorder tab (P7).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

SCHEMA_VERSION = 1
TARGETS = ("pc", "ec")
SOURCE_MANUAL = "manual"
SOURCE_AUTO_EC = "auto-ec-deficit"


@dataclass
class RunItem:
    # --- pushed to the floor ---
    target: str                              # "pc" | "ec"
    partNo: str
    serial: str
    location: str
    allocQty: int
    # --- internal bookkeeping ---
    releaseId: Optional[int] = None
    customer: str = ""
    shipDate: str = ""                       # ISO date
    powderColour: str = ""                   # PC grouping; "" for EC / none
    part: str = ""                           # the container's part (reconciliation)
    queuedPaintSeq: Optional[int] = None     # seq of the EC/PC op this item runs (reconciliation)
    source: str = SOURCE_MANUAL              # "manual" | "auto-ec-deficit"
    acknowledged: bool = False               # planner ticked an auto-added EC as reviewed (§13)
    runItemId: str = field(default_factory=lambda: uuid.uuid4().hex)
    pushedAt: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunItem":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


def new_doc(pc_items, ec_items, *, app_version: str,
            owner: Optional[dict] = None, published_at: Optional[str] = None) -> dict:
    """Build a JSON-serialisable runlist document from ordered PC + EC item lists."""
    return {
        "schema": SCHEMA_VERSION,
        "appVersion": app_version,
        "publishedAt": published_at or datetime.now().isoformat(timespec="seconds"),
        "owner": owner or {},
        "pc": [it.to_dict() for it in pc_items],
        "ec": [it.to_dict() for it in ec_items],
    }


def items_from_doc(doc: Optional[dict], target: str) -> list[RunItem]:
    """Ordered :class:`RunItem` list for *target* (``"pc"``/``"ec"``) from a document."""
    return [RunItem.from_dict(d) for d in (doc or {}).get(target, [])]
