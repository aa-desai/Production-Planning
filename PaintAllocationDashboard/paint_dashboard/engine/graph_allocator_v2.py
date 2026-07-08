"""
Graph-based Inventory Allocation (V2)
=====================================
Drop-in alternative to ``inventory_to_release_allocation.py`` that models the full
multi-plant routing + multi-level BOM as a single graph and runs allocation as
one upstream traversal. Internal releases for painted sub-components are
generated only for the portion of a release that cannot be covered by the
parent's on-hand inventory past the operation that consumes those components.

This module imports the trusted cleaning / routing / part-data helpers from
``inventory_to_release_allocation`` and adds the graph builder + allocator on top.
Output files all carry a ``_V2`` suffix so the existing production CSVs are
never overwritten.

Run from the project root::

    venv/Scripts/python.exe "Python Script/graph_allocator_V2.py"

Inputs (read-only) — raw ERP exports under the project root, resolved via the
trusted module's ``path_*`` constants (``Inventory P6/``, ``Inventory/``,
``Releases/``, ``Process Routings/``, ``Part Attributes/``, ``BOM/Exploded BOM/``).
All are ``.xlsx`` read through ``engine="calamine"``.

Outputs land in ``Allocations/`` as:

* ``Inventory_V2.csv``   — cleaned, allocation-eligible inventory (enriched with
  prev/next op + routing plant).
* ``Releases_V2.csv``    — external customer releases + the internal releases
  generated for painted sub-components (carry ``Parent Release ID`` /
  ``Consumed At Op`` / ``Parent Part``).
* ``Allocation_V2.csv``  — the painted allocation rows (one per container↔release
  allocation, plus unallocated painted-container rows). Now also carries the
  dashboard's ``Filter: …`` columns (Customer / EC / PC / Colour / Inventory at
  P10 / Condition / Ship Date) — see ``attach_filter_columns``.
* ``Rework_MRB_V2.csv``  — Rework / MRB containers, set aside and never allocated.

Full input/output/column/dependency reference: ``graph_allocator_V2_README.md``
(next to this file).
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Shared ERP-data layer (allocation_common)
# ---------------------------------------------------------------------------
# VENDORED COPY — the source of truth for this engine is the trusted
# ``Python Script\graph_allocator_V2.py``. This copy is bundled inside the dashboard
# package so the tool is fully self-contained (no dependency on the external
# ``Python Script\`` folder). The ONLY change from the original is the import below
# (absolute ``from allocation_common`` -> package-relative ``from .allocation_common``);
# the allocation logic is identical to the trusted module.

from .allocation_common import (  # noqa: E402
    BASE,
    P10_LOCATION,
    PLANT_P10,
    add_prev_next_operation,
    apply_revision_suffix,
    clean_folder,
    clean_process_routing_file,
    clean_release_file,
    do_nothing,
    extract_plant_from_source_file,
    internal_op_nos,
    load_inventory,
    output_allocation_check,
    path_attributes,
    path_bom_exploded,
    path_process_routings,
    path_releases,
)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

SENTINEL_SHIP_DATE = datetime(9999, 12, 31)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Container:
    serial: str
    part: str
    operation: str
    quantity: int
    remaining: int
    location: str
    container_plant: str
    add_date: object
    next_operation: str


@dataclass
class ComponentEdge:
    target: "Node"
    multiplier: float
    consume_op_text: str


@dataclass
class Node:
    part: str
    operation: str
    internal_op_no: int
    seq: int = 0  # 0-based position of this op within the part's routing flow
    containers: list[Container] = field(default_factory=list)
    component_edges: list[ComponentEdge] = field(default_factory=list)
    upstream: Optional["Node"] = None  # routing edge: previous op (lower Internal Op No)


@dataclass
class Graph:
    nodes: dict[tuple[str, str], Node]
    final_op: dict[str, Node]
    painted_parts: set[str]
    # Containers whose (part, op) could not be matched to any routing node,
    # even via the base-name fallback. Surfaced as unallocated so no painted
    # container is silently dropped.
    unattached: list[Container] = field(default_factory=list)
    # part -> flow-sequence position of the LAST routing op whose name contains
    # "EC" or "PC". Used for the "Past Last Paint Op" flag.
    last_paint_seq: dict[str, int] = field(default_factory=dict)


@dataclass
class ReleaseAnchor:
    release_id: object
    part: str
    rel_bal: int
    ship_date: object
    customer: str
    release_plant: str
    is_internal: bool = False
    parent_release_id: Optional[object] = None
    # passthrough = a non-painted intermediate. Its inventory absorbs demand so
    # we don't over-build its painted children, but its consumption is NOT
    # recorded as an allocation row and NOT charged to any release balance.
    passthrough: bool = False
    # The top-level customer release part this (possibly internal) demand traces
    # back to. For external releases this equals ``part``; for internal releases
    # it is propagated down so allocations show which top-level release they serve.
    root_part: Optional[str] = None


# ---------------------------------------------------------------------------
# Routing loader that keeps non-painted intermediates in scope
# ---------------------------------------------------------------------------


def load_full_process_routing() -> pd.DataFrame:
    """Load routing for ALL parts (not just painted), then assign Internal Op No.

    The standard ``load_process_routing`` filters to painted parts via
    ``routing_painted_parts``. The graph model needs non-painted intermediates
    so it can reach painted grandchildren, so we skip that filter and prune
    later via graph reachability.
    """
    routing = clean_folder(path_process_routings, clean_process_routing_file)
    routing = extract_plant_from_source_file(routing, "Routing Plant")
    routing = routing.drop_duplicates(
        subset=["Part Number", "Operation", "Routing Plant"], keep="first"
    )
    routing = internal_op_nos(routing)
    return routing


def load_part_attributes() -> pd.DataFrame:
    """Load Part Attributes, rebuilding ``Part Number`` from Part No + Revision.

    The raw export ships a ``Part Number`` column that omits the revision
    (e.g. ``"12604123"`` rather than ``"12604123-Rev-A"``), which fails to join
    against the revision-suffixed part numbers used everywhere else. We
    reconstruct it from the separate ``Part No`` / ``Revision`` columns using
    the same convention as the inventory and routing cleaners.
    """
    attrs = clean_folder(path_attributes, do_nothing)
    if "Part No" in attrs.columns and "Revision" in attrs.columns:
        mask = attrs["Revision"].notna() & (attrs["Revision"].astype(str).str.strip() != "")
        attrs = apply_revision_suffix(attrs, "Part No", "Revision", mask)
    return attrs


# ---------------------------------------------------------------------------
# Op-string normalisation between BOM and routing
# ---------------------------------------------------------------------------


def normalize_bom_op(op_no_code: object) -> str:
    """Strip the leading ``"<num> - "`` from a BOM ``Op No - Code`` value.

    BOM uses ``"10 - MIG Weld - WIP"``; routing's ``Operation`` is just
    ``"MIG Weld - WIP"``. Confirmed by probing both files.
    """
    if pd.isna(op_no_code):
        return ""
    s = str(op_no_code)
    parts = s.split(" - ", 1)
    if len(parts) == 2 and parts[0].strip().isdigit():
        return parts[1]
    return s


def op_base_name(operation: object) -> str:
    """Drop the trailing status segment from an operation string.

    Operations are ``"<Name> - <Status>"`` where Status is WIP / FG / ea / etc.
    The base name (everything before the final ``" - "``) identifies the
    physical operation regardless of WIP/FG status. Used only as a *fallback*
    after exact matching fails, so multi-pass ops (``"Pressbrake - WIP"`` vs
    ``"Pressbrake - WIP 2"``) are never accidentally merged.
    """
    s = str(operation)
    parts = s.rsplit(" - ", 1)
    return parts[0] if len(parts) == 2 else s


# ---------------------------------------------------------------------------
# Per-part paint flags + powder colour
# ---------------------------------------------------------------------------


def build_part_paint_flags(
    process_routing: pd.DataFrame,
    exploded_bom_raw: pd.DataFrame,
    part_attributes: pd.DataFrame,
) -> pd.DataFrame:
    """Compute Ecoat / Powdercoat / Powder Colour per Part Number.

    Definitions (per the user):

    * **Ecoat**     = the part has an EC operation in its own routing, OR it is
      the *only* component consumed during an EC operation of some parent.
    * **Powdercoat** = the part has a PC operation in its own routing, OR it is
      the *only* component consumed during a PC operation of some parent.
    * **Powder Colour** = if Powdercoat: the colour from Part Attributes, or
      ``"Not Found"`` when the part has no attribute row / null colour;
      otherwise ``"None"``.

    The "only consumed component" rule captures parts whose own routing has no
    paint op because the paint op lives on the next part number in the chain
    (e.g. a bare ``-R`` part loaded alone into EC-Load becomes the ``-010``
    part). Those parts are still physically painted.
    """
    op = process_routing["Operation"].astype(str)
    own = (
        process_routing.assign(
            _ec=op.str.contains("EC", na=False).values,
            _pc=op.str.contains("PC", na=False).values,
        )
        .groupby("Part Number")[["_ec", "_pc"]]
        .any()
    )
    has_own_ec = set(own.index[own["_ec"]])
    has_own_pc = set(own.index[own["_pc"]])

    # Sole-consumed-component flags from the raw exploded BOM.
    bom = exploded_bom_raw[
        exploded_bom_raw["Component Part-Rev"].notna()
        & exploded_bom_raw["Op No - Code"].notna()
    ].copy()
    bom["_op"] = bom["Op No - Code"].map(normalize_bom_op)

    sole_ec: set[str] = set()
    sole_pc: set[str] = set()
    comp_sets = bom.groupby(["BOM Part-Rev", "_op"])["Component Part-Rev"].agg(
        lambda s: list(pd.unique(s.dropna()))
    )
    for (_parent, op_name), comps in comp_sets.items():
        if len(comps) != 1:
            continue
        comp = comps[0]
        if "EC" in str(op_name):
            sole_ec.add(comp)
        if "PC" in str(op_name):
            sole_pc.add(comp)

    # Powder colour lookup, preferring rows with a non-null colour.
    attrs = part_attributes[["Part Number", "Powder Colour"]].copy()
    attrs = attrs.sort_values(
        ["Part Number", "Powder Colour"], na_position="last"
    ).drop_duplicates("Part Number", keep="first")
    colour_map = dict(zip(attrs["Part Number"], attrs["Powder Colour"]))

    # Part_Status lookup (from Part Attributes SQL; the Manual file lacks the column).
    # A part can carry several attribute rows with conflicting statuses (~3% do — e.g. a stale
    # "Pre-Production" record alongside a live "Production" one). Resolve to ONE status by
    # priority so the Pre-Production quick filter is deterministic: a part actually in
    # Production is treated as Production (it won't show under "Pre-Production only" nor be
    # hidden by "No Pre-Production"). Order below = most-authoritative first.
    status_map = _part_status_map(part_attributes)

    all_parts = (
        set(process_routing["Part Number"].dropna())
        | has_own_ec | has_own_pc | sole_ec | sole_pc
    )

    rows = []
    for part in all_parts:
        ecoat = (part in has_own_ec) or (part in sole_ec)
        powdercoat = (part in has_own_pc) or (part in sole_pc)
        if powdercoat:
            colour = colour_map.get(part)
            colour = "Not Found" if (colour is None or pd.isna(colour) or colour == "") else colour
        else:
            colour = "None"
        rows.append(
            {
                "Part Number": part,
                "Ecoat": ecoat,
                "Powdercoat": powdercoat,
                "Powder Colour": colour,
                "Part_Status": status_map.get(part, ""),
            }
        )

    return pd.DataFrame(
        rows, columns=["Part Number", "Ecoat", "Powdercoat", "Powder Colour", "Part_Status"]
    )


# Status priority for de-duping conflicting Part Attributes rows (lower rank wins). Production
# dominates Pre-Production so a part that is in production is never treated as pre-production.
_STATUS_PRIORITY = {
    "Production": 0, "Pre-Production": 1, "Engineering Review": 2,
    "Review": 3, "Quote": 4, "Inactive": 5, "Obsolete": 6,
}


def _part_status_map(part_attributes: pd.DataFrame) -> dict:
    """``Part Number -> resolved Part_Status`` (one status per part, priority-deduped)."""
    if "Part_Status" not in part_attributes.columns:
        return {}
    st = part_attributes[["Part Number", "Part_Status"]].dropna().copy()
    st["Part Number"] = st["Part Number"].astype(str).str.strip()
    st["Part_Status"] = st["Part_Status"].astype(str).str.strip()
    st = st[(st["Part Number"] != "") & (st["Part_Status"] != "")]
    st["_rank"] = st["Part_Status"].map(_STATUS_PRIORITY).fillna(99)
    st = st.sort_values(["Part Number", "_rank"]).drop_duplicates("Part Number", keep="first")
    return dict(zip(st["Part Number"], st["Part_Status"]))


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_graph(
    process_routing: pd.DataFrame,
    exploded_bom_raw: pd.DataFrame,
    inventory: pd.DataFrame,
    painted_parts: Optional[set[str]] = None,
) -> Graph:
    """Build the (part, operation) graph from full routing + raw exploded BOM.

    ``painted_parts`` lets the caller pass the richer paint definition (own EC/PC
    op OR sole-consumed-component of a parent's paint op). When omitted, falls
    back to a routing-only EC/PC definition.
    """
    nodes: dict[tuple[str, str], Node] = {}
    final_op: dict[str, Node] = {}

    # ---- routing edges (upstream-only) + node creation ----
    # process_routing rows within each part are already in flow order because
    # internal_op_nos uses cumcount over the reordered sequence. Don't re-sort
    # by Internal Op No alone (ties at 0 would scramble).
    for part, grp in process_routing.groupby("Part Number", sort=False):
        prev: Optional[Node] = None
        last_node: Optional[Node] = None
        seq = 0
        for _, row in grp.iterrows():
            op = row["Operation"]
            if pd.isna(op):
                continue
            key = (part, op)
            if key in nodes:
                # Duplicate routing row (shouldn't happen post-dedup); ignore.
                continue
            ion = row.get("Internal Op No")
            node = Node(
                part=part,
                operation=op,
                internal_op_no=int(ion) if pd.notna(ion) else 0,
                seq=seq,
            )
            node.upstream = prev
            nodes[key] = node
            prev = node
            last_node = node
            seq += 1
        if last_node is not None:
            final_op[part] = last_node

    # ---- base-name index per part for fallback matching ----
    # Maps part -> base op name -> list of nodes sharing that base name.
    base_index: dict[str, dict[str, list[Node]]] = defaultdict(lambda: defaultdict(list))
    for (part, op), node in nodes.items():
        base_index[part][op_base_name(op)].append(node)

    # ---- attach inventory containers to their nodes (two-tier match) ----
    unattached: list[Container] = []
    for _, inv_row in inventory.iterrows():
        part = inv_row["Part Number"]
        opcode = inv_row["Operation Code"]
        qty = inv_row.get("Quantity")
        if pd.isna(qty):
            continue

        container = Container(
            serial=str(inv_row.get("Serial No", "")),
            part=part,
            operation=opcode,
            quantity=int(qty),
            remaining=int(qty),
            location=str(inv_row.get("Location", "")),
            container_plant=str(inv_row.get("Container Plant", "")),
            add_date=inv_row.get("Add Date"),
            next_operation=str(inv_row.get("Next Operation", "None")),
        )

        # Tier 1: exact (part, op) match.
        node = nodes.get((part, opcode))
        # Tier 2: base-name fallback, only when unambiguous. Catches the
        # WIP<->FG status swap at the final op (container "EC-Unload - WIP"
        # vs routing "EC-Unload - FG") without merging multi-pass ops.
        if node is None:
            candidates = base_index.get(part, {}).get(op_base_name(opcode), [])
            if len(candidates) == 1:
                node = candidates[0]

        if node is None:
            unattached.append(container)
        else:
            node.containers.append(container)

    # Sort containers within each node by Quantity ASC (parity with existing
    # allocator's secondary sort key — smallest containers used first).
    for node in nodes.values():
        node.containers.sort(key=lambda c: c.quantity)

    # ---- component edges from the raw exploded BOM ----
    for _, bom_row in exploded_bom_raw.iterrows():
        parent = bom_row.get("BOM Part-Rev")
        component = bom_row.get("Component Part-Rev")
        op_code = bom_row.get("Op No - Code")
        qty = bom_row.get("BOM Quantity")

        if pd.isna(parent) or pd.isna(component) or pd.isna(op_code) or pd.isna(qty):
            continue

        op_name = normalize_bom_op(op_code)
        parent_key = (parent, op_name)
        parent_node = nodes.get(parent_key)
        if parent_node is None:
            continue

        target = final_op.get(component)
        if target is None:
            # Component has no known routing — treat as raw / out-of-scope.
            continue

        parent_node.component_edges.append(
            ComponentEdge(target=target, multiplier=float(qty), consume_op_text=op_name)
        )

    # ---- painted-part set (for filtering internal-release output rows) ----
    if painted_parts is None:
        painted_parts = set(
            process_routing.loc[
                process_routing["Operation"].astype(str).str.contains("EC|PC", na=False),
                "Part Number",
            ].unique()
        )

    # ---- last paint-op flow position per part ----
    last_paint_seq: dict[str, int] = {}
    for (part, op), node in nodes.items():
        if ("EC" in str(op)) or ("PC" in str(op)):
            if node.seq > last_paint_seq.get(part, -1):
                last_paint_seq[part] = node.seq

    # ---- cycle detection: BOM should be a DAG ----
    _assert_dag(nodes, final_op)

    return Graph(
        nodes=nodes,
        final_op=final_op,
        painted_parts=set(painted_parts),
        unattached=unattached,
        last_paint_seq=last_paint_seq,
    )


def _assert_dag(
    nodes: dict[tuple[str, str], Node],
    final_op: dict[str, Node],
) -> None:
    """Detect cycles created by component edges across part boundaries.

    Routing edges go strictly upstream within one part (no cycles possible).
    Component edges hop between parts and could in theory form a cycle if a
    part transitively consumes itself. Walk part-level reachability and fail
    loudly if a cycle is found.
    """
    part_children: dict[str, set[str]] = defaultdict(set)
    for (part, _op), node in nodes.items():
        for edge in node.component_edges:
            child_part = edge.target.part
            if child_part != part:
                part_children[part].add(child_part)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(lambda: WHITE)

    def dfs(p: str, stack: list[str]) -> None:
        color[p] = GREY
        stack.append(p)
        for c in part_children.get(p, ()):
            if color[c] == GREY:
                cycle = stack[stack.index(c):] + [c]
                raise ValueError(f"BOM cycle detected: {' -> '.join(cycle)}")
            if color[c] == WHITE:
                dfs(c, stack)
        stack.pop()
        color[p] = BLACK

    for p in list(part_children.keys()):
        if color[p] == WHITE:
            dfs(p, [])


# ---------------------------------------------------------------------------
# Reachability pruning — which parts must we keep inventory for?
# ---------------------------------------------------------------------------


def reachable_parts(graph: Graph, release_parts: set[str]) -> set[str]:
    """Set of parts reachable from any release anchor via routing + component edges.

    Used to filter inventory for output and to determine where to emit
    internal-release rows.
    """
    visited: set[str] = set()
    queue: deque[Node] = deque()

    for part in release_parts:
        anchor = graph.final_op.get(part)
        if anchor is not None:
            queue.append(anchor)

    while queue:
        node = queue.popleft()
        visited.add(node.part)
        # Walk every op of this part upstream from this node, queuing the final
        # op of each not-yet-visited component.
        cur: Optional[Node] = node
        while cur is not None:
            for edge in cur.component_edges:
                if edge.target.part not in visited:
                    queue.append(edge.target)
            cur = cur.upstream

    return visited


# ---------------------------------------------------------------------------
# Release loading + P6 filtering by paint reachability
# ---------------------------------------------------------------------------


def load_releases_no_p6_elim() -> pd.DataFrame:
    """Load + clean releases WITHOUT ``elim_p6_releases``.

    The standard ``load_releases`` drops P6 releases unless that part has a P6
    container staged at ``Modineer - P10``. The V2 pipeline replaces that rule
    with a paint-reachability rule (see ``filter_p6_releases_by_paint``), which
    needs the graph, so we defer the P6 filter until after the graph is built.
    """
    releases = clean_folder(path_releases, clean_release_file)
    releases = extract_plant_from_source_file(releases, "Release Plant")
    releases = releases.sort_values("Ship Date").reset_index(drop=True)
    return releases


def filter_releases_by_paint(releases: pd.DataFrame, graph: Graph) -> pd.DataFrame:
    """Keep a release (any plant) only if its graph is painted.

    "Painted" means the released part's full subtree (its own routing plus every
    recursively-consumed component) contains at least one operation whose name
    includes ``EC`` or ``PC``. This replaces ``elim_p6_releases``' old
    "P6 container staged at Modineer - P10" condition and applies the EC/PC test
    uniformly to P10 and P6 releases alike.
    """
    painted_parts = set(graph.last_paint_seq)  # parts with an own EC/PC op
    paint_cache: dict[str, bool] = {}

    def graph_has_paint(part: str) -> bool:
        if part not in paint_cache:
            reach = reachable_parts(graph, {part})
            paint_cache[part] = bool(reach & painted_parts)
        return paint_cache[part]

    keep = [graph_has_paint(row["Part Number"]) for _, row in releases.iterrows()]
    return releases[pd.Series(keep, index=releases.index)].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Release anchoring
# ---------------------------------------------------------------------------


def anchor_releases(
    graph: Graph,
    releases: pd.DataFrame,
) -> tuple[list[ReleaseAnchor], pd.DataFrame]:
    """Build ordered ReleaseAnchor list for releases whose part is in the graph.

    Returns (anchors sorted by Ship Date ASC, releases-with-Release-ID frame).
    """
    rel = releases.copy().reset_index(drop=True)
    rel["Release ID"] = rel.index
    rel = rel.sort_values("Ship Date", kind="stable").reset_index(drop=True)
    rel["Release ID"] = rel.index  # re-stamp after sort so IDs are FIFO

    anchors: list[ReleaseAnchor] = []
    for _, row in rel.iterrows():
        part = row["Part Number"]
        if part not in graph.final_op:
            continue
        anchors.append(
            ReleaseAnchor(
                release_id=int(row["Release ID"]),
                part=part,
                rel_bal=int(row["Rel Bal"]),
                ship_date=row["Ship Date"],
                customer=str(row.get("Customer", "")),
                release_plant=str(row.get("Release Plant", "")),
                is_internal=False,
                root_part=part,
            )
        )
    return anchors, rel


# ---------------------------------------------------------------------------
# Allocation traversal
# ---------------------------------------------------------------------------


def allocate_via_graph(
    graph: Graph,
    anchors: list[ReleaseAnchor],
    releases_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the upstream graph traversal allocation.

    Returns
    -------
    (allocation_rows, internal_release_rows, full_releases_df_with_internal)
    """
    allocation_rows: list[dict] = []
    internal_release_rows: list[dict] = []

    # Mutable Rel Bal tracker per release ID for trace output
    rel_bal_remaining: dict[int, int] = {
        int(a.release_id): a.rel_bal for a in anchors
    }
    # Internal releases generated during traversal — assigned new IDs at the end
    next_internal_id = (
        max([int(a.release_id) for a in anchors], default=-1) + 1
    )

    def is_past_last_paint(part: str, seq: int) -> bool:
        """True if this op is at/after the part's last EC/PC op (by flow seq)."""
        lp = graph.last_paint_seq.get(part)
        return bool(lp is not None and seq >= lp)

    def emit_allocation(
        container: Container,
        anchor: ReleaseAnchor,
        alloc_qty: int,
        node: Node,
    ) -> None:
        allocation_rows.append(
            {
                "Container Part Number": container.part,
                "Release Part Number": anchor.root_part or anchor.part,
                "Serial No": container.serial,
                "Allocated Qty": alloc_qty,
                "Ship Date": anchor.ship_date,
                "Release ID": anchor.release_id,
                # Original Rel Bal straight from the release (internal copy
                # `rel_bal_remaining` is used only to drive allocation, not output).
                "Rel Bal": anchor.rel_bal,
                "Location": container.location,
                "Total Container Quantity": container.quantity,
                "Add Date": container.add_date,
                "Operation Code": container.operation,
                "Next Operation": container.next_operation,
                "Container Plant": container.container_plant,
                "Customer": anchor.customer,
                "Release Plant": anchor.release_plant,
                "Past Last Paint Op": is_past_last_paint(container.part, node.seq),
            }
        )

    def visit(node: Node, demand: int, anchor: ReleaseAnchor) -> int:
        """Allocate at this node, then propagate residual upstream and to components.

        Returns the residual demand that could not be allocated anywhere.
        """
        if demand <= 0:
            return 0

        # 1. Consume containers at this node first.
        for container in node.containers:
            if demand <= 0:
                break
            if container.remaining <= 0:
                continue
            alloc = min(demand, container.remaining)
            container.remaining -= alloc
            demand -= alloc
            # Passthrough (non-painted intermediate): absorb demand only — do not
            # record a row or charge a release balance.
            if not anchor.passthrough:
                emit_allocation(container, anchor, alloc, node)
                rel_bal_remaining[int(anchor.release_id)] -= alloc

        if demand <= 0:
            return 0

        # 2. Fan out component edges (each child component shares the residual,
        #    scaled by BOM Quantity). Each component subgraph traversal mutates
        #    the SHARED container pools, so later releases see less of C too.
        nonlocal next_internal_id
        for edge in node.component_edges:
            child_demand = int(round(demand * edge.multiplier))
            if child_demand <= 0:
                continue
            child_part = edge.target.part
            if child_part in graph.painted_parts:
                # Emit a visible internal-release row for traceability
                internal_id = next_internal_id
                next_internal_id += 1
                internal_release_rows.append(
                    {
                        "Release ID": internal_id,
                        "Customer": (
                            f"Internal-{anchor.customer}"
                            f"-Release ID:{anchor.release_id}"
                        ),
                        "Part Number": child_part,
                        "Rel Bal": child_demand,
                        "Ship Date": anchor.ship_date,
                        "Release Plant": anchor.release_plant,
                        "Parent Release ID": anchor.release_id,
                        "Consumed At Op": node.operation,
                        "Parent Part": anchor.part,
                    }
                )
                rel_bal_remaining[internal_id] = child_demand
                child_anchor = ReleaseAnchor(
                    release_id=internal_id,
                    part=child_part,
                    rel_bal=child_demand,
                    ship_date=anchor.ship_date,
                    customer=(
                        f"Internal-{anchor.customer}"
                        f"-Release ID:{anchor.release_id}"
                    ),
                    release_plant=anchor.release_plant,
                    is_internal=True,
                    parent_release_id=anchor.release_id,
                    root_part=anchor.root_part,
                )
            else:
                # Non-painted intermediate: descend to reach painted grandchildren.
                # Carry the root release's identity forward (so a painted part
                # deeper down still references the original customer release), but
                # mark passthrough so this part's own inventory is absorbed, not
                # charged to any release.
                child_anchor = ReleaseAnchor(
                    release_id=anchor.release_id,
                    part=child_part,
                    rel_bal=child_demand,
                    ship_date=anchor.ship_date,
                    customer=anchor.customer,
                    release_plant=anchor.release_plant,
                    is_internal=anchor.is_internal,
                    parent_release_id=anchor.parent_release_id,
                    passthrough=True,
                    root_part=anchor.root_part,
                )

            visit(edge.target, child_demand, child_anchor)

        # 3. Propagate residual UPSTREAM in this part's routing.
        if node.upstream is not None:
            return visit(node.upstream, demand, anchor)

        # 4. Top of routing reached — residual is genuinely unfilled demand.
        return demand

    # Process anchors in ship-date FIFO order (already sorted).
    for anchor in anchors:
        node = graph.final_op.get(anchor.part)
        if node is None:
            continue
        visit(node, anchor.rel_bal, anchor)

    alloc_df = pd.DataFrame(allocation_rows)
    internal_df = pd.DataFrame(internal_release_rows)

    # ---- emit unallocated container rows with sentinel ship date ----
    # Every painted container must appear in the output. We emit an unallocated
    # row for: (a) node-attached painted containers with leftover quantity, and
    # (b) painted containers that never matched a routing node (orphans).
    def unalloc_row(c: Container, qty: int, reason: str, seq: Optional[int]) -> dict:
        return {
            "Container Part Number": c.part,
            "Release Part Number": None,
            "Serial No": c.serial,
            "Allocated Qty": qty,
            "Ship Date": SENTINEL_SHIP_DATE,
            "Release ID": None,
            "Rel Bal": None,
            "Location": c.location,
            "Total Container Quantity": c.quantity,
            "Add Date": c.add_date,
            "Operation Code": c.operation,
            "Next Operation": c.next_operation,
            "Container Plant": c.container_plant,
            "Customer": None,
            "Release Plant": None,
            "Past Last Paint Op": (
                False if seq is None else is_past_last_paint(c.part, seq)
            ),
            "Unmatched Reason": reason,
        }

    unallocated_rows: list[dict] = []
    for node in graph.nodes.values():
        for c in node.containers:
            if c.remaining > 0 and c.part in graph.painted_parts:
                unallocated_rows.append(unalloc_row(c, c.remaining, "", node.seq))

    # Orphan painted containers (no routing-node match even via fallback).
    for c in graph.unattached:
        if c.part in graph.painted_parts:
            unallocated_rows.append(
                unalloc_row(c, c.remaining, "no routing node for (part, op)", None)
            )

    if unallocated_rows:
        alloc_df = pd.concat(
            [alloc_df, pd.DataFrame(unallocated_rows)], ignore_index=True
        )

    # ---- assertions ----
    if not alloc_df.empty:
        assert (alloc_df["Allocated Qty"] > 0).all(), "Allocation with zero qty"
        per_container = alloc_df.groupby("Serial No")["Allocated Qty"].sum()
        cap = alloc_df.groupby("Serial No")["Total Container Quantity"].first()
        over = per_container > cap
        assert not over.any(), (
            f"Over-allocation for serial(s): {over[over].index.tolist()}"
        )
    if not internal_df.empty:
        assert (internal_df["Rel Bal"] > 0).all(), "Internal release with zero qty"

    # ---- assemble combined releases frame (external + internal) ----
    combined_releases = pd.concat(
        [releases_df, internal_df], ignore_index=True, sort=False
    )

    # ---- sort allocation output by Ship Date, Release Part Number, Release ID ----
    alloc_df["Ship Date"] = pd.to_datetime(alloc_df["Ship Date"], errors="coerce")
    alloc_df = alloc_df.sort_values(
        by=["Ship Date", "Release Part Number", "Release ID"],
        ascending=[True, True, True],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)

    return alloc_df, internal_df, combined_releases


# ---------------------------------------------------------------------------
# Dashboard-parity per-release filter attributes
# ---------------------------------------------------------------------------
# The Paint Allocation Dashboard derives, per release, a coverage breakdown and a
# single "condition", plus an "inventory at P10" test, and exposes those alongside
# the EC / PC / Colour / Customer / Ship-date filters as interactive filters. To keep
# the CSV output logically identical to the dashboard, we compute the same values
# here and emit one ``Filter: xyz`` column per dashboard filter on Allocation_V2.csv.

# Maps the internal coverage class to the dashboard's renamed hide-filter labels:
#   good -> Hide Past Paint, low -> Hide WIP only, medium -> Hide Pipeline only,
#   high -> Hide Empty Pipeline.
CONDITION_LABEL = {
    "good": "Past Paint",
    "low": "WIP only",
    "medium": "Pipeline only",
    "high": "Empty Pipeline",
}

# A container is "at P10" if it is P10-owned, or it is a P6 container that has
# physically transferred to the P10 location. Both values come from allocation_common
# (config-driven; P10_LOCATION is the same literal elim_p6_releases uses).
P10_PLANT = PLANT_P10


def _container_at_p10(c: Container) -> bool:
    return str(c.container_plant) == P10_PLANT or str(c.location) == P10_LOCATION


def _bucket_rows(rows: list[dict]) -> dict:
    """Bucket a release's allocation rows into coverage buckets.

    Quantity at/after the last paint op is "past paint"; everything else is
    "paintable" (the next op is an EC/PC paint op) or "pipeline" (anything else).
    Identical to the dashboard's coverage bucketing.
    """
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
    """good / low / medium / high coverage class, identical to the dashboard."""
    past, paintable, pipeline = cov["pastPaint"], cov["paintable"], cov["pipeline"]
    if past >= rel_bal:
        return "good"
    if past + paintable >= rel_bal:
        return "low"
    if past + paintable + pipeline >= rel_bal:
        return "medium"
    return "high"


def attach_filter_columns(
    alloc_df: pd.DataFrame,
    graph: Graph,
    releases_df: pd.DataFrame,
    internal_df: pd.DataFrame,
) -> pd.DataFrame:
    """Add one ``Filter: xyz`` column per dashboard filter to the allocation rows.

    Coverage / condition / inventory-at-P10 are per-release values: they are
    computed for each external release (rolling internal-release rows up to their
    top-level parent, exactly like the dashboard) and then denormalised onto every
    allocation row that serves that release. EC / PC / Colour / Customer / Ship Date
    mirror the per-row paint flags and release fields already present.
    """
    filter_cols = (
        "Filter: Customer", "Filter: EC", "Filter: PC", "Filter: Colour",
        "Filter: Inventory at P10", "Filter: Condition", "Filter: Ship Date",
    )
    if alloc_df.empty:
        for col in filter_cols:
            alloc_df[col] = pd.Series(dtype="object")
        return alloc_df

    # --- map any release id -> top-level external release id -----------------
    ext_ids = set(releases_df["Release ID"].astype(int))
    internal_to_top: dict[int, int] = {}
    if internal_df is not None and not internal_df.empty:
        parent_of = dict(
            zip(internal_df["Release ID"].astype(int),
                internal_df["Parent Release ID"].astype(int))
        )
        for iid in internal_df["Release ID"].astype(int):
            top = int(iid)
            seen: set[int] = set()
            while top not in ext_ids and top in parent_of and top not in seen:
                seen.add(top)
                top = int(parent_of[top])
            internal_to_top[int(iid)] = top

    def row_top(rid) -> Optional[int]:
        if rid is None or (isinstance(rid, float) and pd.isna(rid)):
            return None
        rid = int(rid)
        return internal_to_top.get(rid, rid)

    # --- per-external-release coverage -> condition --------------------------
    rel_bal_by_id = dict(
        zip(releases_df["Release ID"].astype(int), releases_df["Rel Bal"].astype(int))
    )
    part_by_id = dict(
        zip(releases_df["Release ID"].astype(int), releases_df["Part Number"])
    )
    # Real (top-level) customer per external release. Internal-release allocation
    # rows store a synthetic "Internal-<customer>-Release ID:<id>" customer, so we
    # must resolve the customer from the top-level release the row rolls up to —
    # otherwise filtering by customer would miss every sub-component allocation.
    customer_by_id = dict(
        zip(releases_df["Release ID"].astype(int), releases_df["Customer"].astype(str))
    )

    alloc_by_top: dict[int, list[dict]] = defaultdict(list)
    for rec in alloc_df.to_dict("records"):
        top = row_top(rec.get("Release ID"))
        if top is not None:
            alloc_by_top[top].append(rec)

    condition_by_top: dict[int, str] = {}
    for top, rows in alloc_by_top.items():
        cov = _bucket_rows(rows)
        rb = rel_bal_by_id.get(top, 0)
        cov["short"] = max(rb - cov["pastPaint"] - cov["paintable"] - cov["pipeline"], 0)
        condition_by_top[top] = CONDITION_LABEL[concern_from_coverage(cov, rb)]

    # --- inventory at P10 across the release part's full routing subtree -----
    parts_with_p10_inv = {
        n.part for n in graph.nodes.values()
        if any(_container_at_p10(c) for c in n.containers)
    }
    _p10_cache: dict[str, bool] = {}

    def subtree_has_p10(part: str) -> bool:
        if part not in _p10_cache:
            _p10_cache[part] = bool(reachable_parts(graph, {part}) & parts_with_p10_inv)
        return _p10_cache[part]

    p10_by_top = {top: subtree_has_p10(part_by_id.get(top, "")) for top in alloc_by_top}

    tops = alloc_df["Release ID"].map(row_top)

    # --- emit one column per dashboard filter --------------------------------
    # Customer rolls up to the top-level release (so sub-component rows show the
    # real customer, not "Internal-…"); EC/PC/Colour already describe the release
    # part because Release Part Number carries the top-level root_part forward.
    alloc_df["Filter: Customer"] = tops.map(
        lambda t: customer_by_id.get(t) if t is not None else None
    )
    alloc_df["Filter: EC"] = alloc_df["Ecoat"]
    alloc_df["Filter: PC"] = alloc_df["Powdercoat"]
    alloc_df["Filter: Colour"] = alloc_df["Powder Colour"]
    alloc_df["Filter: Inventory at P10"] = tops.map(
        lambda t: p10_by_top.get(t) if t is not None else None
    )
    alloc_df["Filter: Condition"] = tops.map(
        lambda t: condition_by_top.get(t) if t is not None else None
    )
    alloc_df["Filter: Ship Date"] = (
        pd.to_datetime(alloc_df["Ship Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    )
    return alloc_df


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def write_v2_outputs(
    base_path: Path,
    inventory: pd.DataFrame,
    releases: pd.DataFrame,
    allocation: pd.DataFrame,
) -> None:
    base_path.mkdir(exist_ok=True)
    inventory.to_csv(base_path / "Inventory_V2.csv", index=False)
    releases.to_csv(base_path / "Releases_V2.csv", index=False)
    allocation.to_csv(base_path / "Allocation_V2.csv", index=False)


def main() -> None:
    log.info("V2 pipeline starting")

    log.info("Loading data...")
    inventory_raw = load_inventory()
    releases_raw = load_releases_no_p6_elim()
    process_routing = load_full_process_routing()
    exploded_bom = clean_folder(path_bom_exploded, do_nothing)
    part_attributes = load_part_attributes()

    log.info(
        "Loaded: inventory=%d releases=%d routing_rows=%d bom_rows=%d",
        len(inventory_raw),
        len(releases_raw),
        len(process_routing),
        len(exploded_bom),
    )

    # ---- paint flags up-front so we know the painted-part universe ----
    paint_flags = build_part_paint_flags(process_routing, exploded_bom, part_attributes)
    painted_set: set[str] = set(
        paint_flags.loc[
            paint_flags["Ecoat"] | paint_flags["Powdercoat"], "Part Number"
        ]
    )

    # ---- separate Rework / MRB containers — they sit on their own, never
    #      allocated (per requirement) ----
    rework_mrb_mask = (
        inventory_raw["Operation Code"].astype(str).str.contains("Rework", case=False, na=False)
        | inventory_raw["Container Status"].isin(
            ["MRB", "Rework", "Rework Subcontract"]
        )
    )
    rework_mrb = inventory_raw[rework_mrb_mask].copy()
    inventory_alloc = inventory_raw[~rework_mrb_mask].copy()
    log.info(
        "Set aside %d Rework/MRB containers; %d remain for allocation",
        len(rework_mrb),
        len(inventory_alloc),
    )

    # Enrich inventory with prev/next op for the output CSV (parity).
    inventory = add_prev_next_operation(inventory_alloc, process_routing)

    log.info("Building graph...")
    graph = build_graph(process_routing, exploded_bom, inventory, painted_set)
    log.info(
        "Graph: nodes=%d painted_parts=%d parts_with_routing=%d unattached_containers=%d",
        len(graph.nodes),
        len(graph.painted_parts),
        len(graph.final_op),
        len(graph.unattached),
    )

    # Keep only releases whose graph contains an EC/PC op (all plants).
    before_paint = len(releases_raw)
    releases_raw = filter_releases_by_paint(releases_raw, graph)
    log.info(
        "Paint filter: %d releases -> %d kept", before_paint, len(releases_raw)
    )

    # Filter releases to parts we can anchor in the graph
    release_parts_in_graph = set(releases_raw["Part Number"]) & set(graph.final_op)
    releases = releases_raw[
        releases_raw["Part Number"].isin(release_parts_in_graph)
    ].reset_index(drop=True)

    # Reachability — informational; used to confirm which inventory will participate
    reach = reachable_parts(graph, set(releases["Part Number"]))
    log.info("Reachable parts from anchored releases: %d", len(reach))

    log.info("Anchoring releases and allocating...")
    anchors, releases_with_id = anchor_releases(graph, releases)
    log.info("Anchored release count: %d", len(anchors))

    alloc_df, internal_df, combined_rel = allocate_via_graph(
        graph, anchors, releases_with_id
    )
    log.info(
        "Allocation rows: %d (incl. unallocated). Internal releases generated: %d",
        len(alloc_df),
        len(internal_df),
    )

    # Attach Ecoat / Powdercoat / Powder Colour describing the RELEASE part
    # (the top-level part the allocation serves), keyed on Release Part Number.
    # Unallocated / orphan rows have no Release Part Number, so for those we fall
    # back to the container's own part flags (keeps painted containers in scope).
    flag_lookup = paint_flags.set_index("Part Number")
    key = alloc_df["Release Part Number"].where(
        alloc_df["Release Part Number"].notna(), alloc_df["Container Part Number"]
    )
    alloc_df["Ecoat"] = key.map(flag_lookup["Ecoat"]).fillna(False).astype(bool)
    alloc_df["Powdercoat"] = key.map(flag_lookup["Powdercoat"]).fillna(False).astype(bool)
    alloc_df["Powder Colour"] = key.map(flag_lookup["Powder Colour"]).where(
        key.map(flag_lookup["Powder Colour"]).notna(), "None"
    )

    # Keep only painted-container rows (Ecoat or Powdercoat). Anything that is
    # neither e-coated nor powder-coated is dropped from the final output.
    before = len(alloc_df)
    alloc_df = alloc_df[alloc_df["Ecoat"] | alloc_df["Powdercoat"]].reset_index(drop=True)
    log.info("Dropped %d non-painted allocation rows (%d remain)", before - len(alloc_df), len(alloc_df))

    # Run the imported sanity check too — its semantics differ slightly from our
    # internal assertion but it's the canonical check.
    try:
        output_allocation_check(alloc_df, check_num=1)
    except Exception as e:
        log.exception("output_allocation_check failed: %s", e)
        raise

    # Attach the dashboard's per-release filter values as "Filter: xyz" columns
    # so the CSV captures every filter the interactive dashboard exposes.
    alloc_df = attach_filter_columns(alloc_df, graph, releases_with_id, internal_df)

    log.info("Writing _V2 outputs...")
    out_dir = BASE / "Allocations"
    write_v2_outputs(out_dir, inventory, combined_rel, alloc_df)

    # Rework / MRB containers sit separately, never allocated.
    rework_mrb.to_csv(out_dir / "Rework_MRB_V2.csv", index=False)
    log.info("Rework/MRB containers written: %d", len(rework_mrb))

    # Completeness report: how many painted containers made it into the output?
    painted_inv = inventory_alloc[inventory_alloc["Part Number"].isin(painted_set)]
    painted_serials = set(painted_inv["Serial No"].dropna().astype(str))
    out_serials = set(alloc_df["Serial No"].dropna().astype(str))
    missing = painted_serials - out_serials
    log.info(
        "Painted containers: %d total, %d in output, %d missing",
        len(painted_serials),
        len(painted_serials & out_serials),
        len(missing),
    )
    if missing:
        log.warning("Sample missing painted serials: %s", list(missing)[:10])

    log.info("Done. Outputs in %s", out_dir)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("V2 pipeline failed: %s", e)
    input("Press Enter to close...")
