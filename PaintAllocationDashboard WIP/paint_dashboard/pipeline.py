"""
In-memory V2 allocation pipeline
================================
Re-runs the V2 allocation pipeline in memory, mirroring ``ga.main()`` but writing no
CSV. Returns a :class:`PipelineResult` holding every object the dashboard needs.

The pipeline is split into two phases (design §3.1, R13/R14):

* :func:`load_daily_inputs` — the routing/BOM-derived, **inventory-independent** part
  (process routing, exploded BOM, part attributes, paint flags, painted set). This is
  expensive to load but changes rarely, so the caller caches it per local day and rebuilds
  it only on the first run of the day or on demand (the "Rebuild graph" button).
* :func:`run_allocation` — the per-refresh part: (re)load inventory + releases, build the
  graph from the cached daily inputs + fresh inventory, then anchor + allocate.

:func:`run_pipeline` runs both back-to-back (used for a cold run / parity check).
The allocation *logic* in the vendored engine is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from . import log
from .engine import allocation_common as common
from .engine import graph_allocator_v2 as ga


# ---------------------------------------------------------------------------
# Daily (inventory-independent) inputs — built once per local day, then cached
# ---------------------------------------------------------------------------
@dataclass
class DailyInputs:
    process_routing: pd.DataFrame   # full routing, all parts, with Internal Op No
    exploded_bom: pd.DataFrame      # raw exploded BOM
    part_attributes: pd.DataFrame   # part attributes (revision-suffixed)
    paint_flags: pd.DataFrame       # Ecoat / Powdercoat / Powder Colour per part
    painted_set: set                # parts that are e-coated or powder-coated
    built_date: date                # local date these inputs were built for
    built_at: datetime              # wall-clock time they were built


def load_daily_inputs() -> DailyInputs:
    """Load the routing/BOM-derived inputs and compute paint flags (design §3.1).

    Inventory-independent, so the caller caches this per local day. Mirrors the
    front half of ``ga.main()``; no inventory or releases are read here.
    """
    log.info("Loading daily inputs (routing / BOM / attributes / paint flags)...")
    process_routing = ga.load_full_process_routing()
    exploded_bom = common.clean_folder(common.path_bom_exploded, common.do_nothing)
    part_attributes = ga.load_part_attributes()
    log.info("Daily inputs: routing_rows=%d bom_rows=%d", len(process_routing), len(exploded_bom))

    # Paint flags + painted-part universe.
    paint_flags = ga.build_part_paint_flags(process_routing, exploded_bom, part_attributes)
    painted_set: set[str] = set(
        paint_flags.loc[paint_flags["Ecoat"] | paint_flags["Powdercoat"], "Part Number"]
    )
    log.info("Daily inputs ready: painted_parts=%d", len(painted_set))

    now = datetime.now()
    return DailyInputs(
        process_routing=process_routing,
        exploded_bom=exploded_bom,
        part_attributes=part_attributes,
        paint_flags=paint_flags,
        painted_set=painted_set,
        built_date=now.date(),
        built_at=now,
    )


# ---------------------------------------------------------------------------
# Pipeline result container
# ---------------------------------------------------------------------------
@dataclass
class PipelineResult:
    graph: "ga.Graph"
    anchors: list
    alloc_df: pd.DataFrame          # painted-only allocation rows (parity w/ Allocation_V2.csv)
    internal_df: pd.DataFrame       # internal releases emitted during traversal
    releases_with_id: pd.DataFrame  # external releases w/ FIFO Release ID
    paint_flags: pd.DataFrame       # Ecoat / Powdercoat / Powder Colour per part
    rework_mrb: pd.DataFrame        # sidelined containers (display-only)
    inventory_raw: pd.DataFrame
    process_routing: pd.DataFrame
    painted_set: set = field(default_factory=set)


def run_allocation(daily: DailyInputs) -> PipelineResult:
    """Per-refresh allocation: (re)load inventory + releases, build the graph from the
    cached *daily* inputs + fresh inventory, then anchor + allocate. Writes no CSV.

    Mirrors the back half of ``ga.main()``. A fresh ``ga.Graph`` is built each call (with
    fresh container state), so the previously-served graph is never mutated.
    """
    process_routing = daily.process_routing
    exploded_bom = daily.exploded_bom
    paint_flags = daily.paint_flags
    painted_set = daily.painted_set

    log.info("Loading inventory + releases...")
    inventory_raw = common.load_inventory()
    releases_raw = ga.load_releases_no_p6_elim()
    log.info("Loaded: inventory=%d releases=%d", len(inventory_raw), len(releases_raw))

    # Sideline Rework / MRB (never allocated; re-attached for display only).
    rework_mrb_mask = (
        inventory_raw["Operation Code"].astype(str).str.contains("Rework", case=False, na=False)
        | inventory_raw["Container Status"].isin(["MRB", "Rework", "Rework Subcontract"])
    )
    rework_mrb = inventory_raw[rework_mrb_mask].copy()
    inventory_alloc = inventory_raw[~rework_mrb_mask].copy()
    log.info("Set aside %d Rework/MRB; %d remain for allocation", len(rework_mrb), len(inventory_alloc))

    inventory = common.add_prev_next_operation(inventory_alloc, process_routing)

    log.info("Building graph...")
    graph = ga.build_graph(process_routing, exploded_bom, inventory, painted_set)
    log.info(
        "Graph: nodes=%d painted_parts=%d parts_with_routing=%d unattached=%d",
        len(graph.nodes), len(graph.painted_parts), len(graph.final_op), len(graph.unattached),
    )

    # Paint-reachability release filter (all plants).
    before_paint = len(releases_raw)
    releases_raw = ga.filter_releases_by_paint(releases_raw, graph)
    log.info("Paint filter: %d -> %d releases", before_paint, len(releases_raw))

    release_parts_in_graph = set(releases_raw["Part Number"]) & set(graph.final_op)
    releases = releases_raw[
        releases_raw["Part Number"].isin(release_parts_in_graph)
    ].reset_index(drop=True)

    log.info("Anchoring + allocating...")
    anchors, releases_with_id = ga.anchor_releases(graph, releases)
    alloc_df, internal_df, _combined = ga.allocate_via_graph(graph, anchors, releases_with_id)

    # Attach release-part paint flags exactly as ga.main does, then keep painted rows.
    flag_lookup = paint_flags.set_index("Part Number")
    key = alloc_df["Release Part Number"].where(
        alloc_df["Release Part Number"].notna(), alloc_df["Container Part Number"]
    )
    alloc_df["Ecoat"] = key.map(flag_lookup["Ecoat"]).fillna(False).astype(bool)
    alloc_df["Powdercoat"] = key.map(flag_lookup["Powdercoat"]).fillna(False).astype(bool)
    pc_map = key.map(flag_lookup["Powder Colour"])
    alloc_df["Powder Colour"] = pc_map.where(pc_map.notna(), "None")
    before = len(alloc_df)
    alloc_df = alloc_df[alloc_df["Ecoat"] | alloc_df["Powdercoat"]].reset_index(drop=True)
    log.info("Dropped %d non-painted rows (%d remain)", before - len(alloc_df), len(alloc_df))

    return PipelineResult(
        graph=graph,
        anchors=anchors,
        alloc_df=alloc_df,
        internal_df=internal_df,
        releases_with_id=releases_with_id,
        paint_flags=paint_flags,
        rework_mrb=rework_mrb,
        inventory_raw=inventory_raw,
        process_routing=process_routing,
        painted_set=painted_set,
    )


def run_pipeline() -> PipelineResult:
    """Cold run: build daily inputs then allocate, in one call (used for parity / a
    one-shot run). Routine refreshes call :func:`run_allocation` with cached daily inputs."""
    return run_allocation(load_daily_inputs())
