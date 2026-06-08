"""
Derived lookup indexes
======================
Built once per pipeline refresh from a :class:`PipelineResult`; provide the fast
lookups the payload + detail builders need (release lineage, allocations by release,
rework/MRB by part-op, swatch map, external releases by id).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

from .pipeline import PipelineResult
from .swatches import load_swatch_map


@dataclass
class Indexes:
    internal_to_top: dict          # any release id -> top-level external release id
    alloc_by_top: dict             # top id -> list of alloc row dicts
    alloc_by_relid: dict           # exact Release ID -> list of alloc row dicts
    rework_by_partop: dict         # (part, op) -> list of rework/mrb row dicts
    swatch_map: dict
    ext_by_id: dict                # external Release ID -> release row dict


def build_indexes(result: PipelineResult) -> Indexes:
    internal_df = result.internal_df
    internal_to_top: dict = {}
    if not internal_df.empty:
        parent_of = dict(
            zip(internal_df["Release ID"].astype(int),
                internal_df["Parent Release ID"].astype(int))
        )
        ext_ids = set(result.releases_with_id["Release ID"].astype(int))
        for iid in internal_df["Release ID"].astype(int):
            top = int(iid)
            seen = set()
            while top not in ext_ids and top in parent_of and top not in seen:
                seen.add(top)
                top = int(parent_of[top])
            internal_to_top[int(iid)] = top

    alloc = result.alloc_df
    alloc_by_top: dict = defaultdict(list)
    alloc_by_relid: dict = defaultdict(list)
    for row in alloc.to_dict("records"):
        rid = row.get("Release ID")
        if rid is None or (isinstance(rid, float) and pd.isna(rid)):
            continue
        rid = int(rid)
        alloc_by_relid[rid].append(row)
        top = internal_to_top.get(rid, rid)
        alloc_by_top[top].append(row)

    rework_by_partop: dict = defaultdict(list)
    if not result.rework_mrb.empty:
        for row in result.rework_mrb.to_dict("records"):
            key = (row.get("Part Number"), row.get("Operation Code"))
            rework_by_partop[key].append(row)

    ext_by_id = {int(r["Release ID"]): r
                 for r in result.releases_with_id.to_dict("records")}

    return Indexes(
        internal_to_top=internal_to_top,
        alloc_by_top=dict(alloc_by_top),
        alloc_by_relid=dict(alloc_by_relid),
        rework_by_partop=dict(rework_by_partop),
        swatch_map=load_swatch_map(),
        ext_by_id=ext_by_id,
    )
