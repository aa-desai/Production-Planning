r"""
Paint Allocation Dashboard  (READ-ONLY)
=======================================
Interactive replacement for the ``Allocation_V2.csv`` Excel workflow.

This script imports the graph allocation engine ``graph_allocator_V2`` and the
shared ERP-data layer ``allocation_common`` (which both that engine and the legacy
allocator build on) and re-runs that exact pipeline **in memory**, then serves a
two-pane dashboard from a local ``http.server``.

The dashboard is strictly READ-ONLY to the planner: no UI action mutates any
file. Nothing in the shared modules is modified. Original raw ERP data is read
only; the only file this tool writes is a local, per-machine snapshot cache
(``paint_allocation_dashboard_snapshot.json``) — a derived performance file,
never shared, never user-edited.

Design spec: ``..\Python Script\paint_dashboard_V2_design.md`` (Draft v10).

Run (dev):  ``..\venv\Scripts\python.exe paint_allocation_dashboard.py``
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger("paint_dashboard")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)


# ---------------------------------------------------------------------------
# Path bootstrap (design §6a.4) — make the trusted modules resolve the right
# project root regardless of whether we run as a script or a frozen .exe, and
# regardless of where the .exe was moved. MUST run before importing the
# trusted modules' path-dependent code triggers any load.
# ---------------------------------------------------------------------------
RAW_DATA_SUBFOLDERS = ("Inventory", "Releases", "Process Routings", "Part Attributes", "BOM")


def _exe_or_script_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()


def load_config() -> dict:
    """Read ``paint_allocation_dashboard.ini`` if present (design §6a.4).

    Search order: ``--config <path>`` → exe/script dir → one level up → cwd.
    Returns a plain dict with optional keys: ``project_root`` (absolute Path),
    ``host`` (str), ``port`` (int). Missing file / keys → empty/defaults; the
    auto-resolver fills the rest. This is the only configuration surface; the
    dashboard is otherwise zero-config.
    """
    import configparser as _cp

    cfg_path: Optional[Path] = None
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        if i + 1 < len(sys.argv):
            cfg_path = Path(sys.argv[i + 1]).expanduser().resolve()
    if cfg_path is None:
        d = _exe_or_script_dir()
        for cand in (d / "paint_allocation_dashboard.ini",
                     d.parent / "paint_allocation_dashboard.ini",
                     Path.cwd() / "paint_allocation_dashboard.ini"):
            if cand.is_file():
                cfg_path = cand
                break
    out: dict = {}
    if cfg_path is None or not cfg_path.is_file():
        return out
    try:
        cp = _cp.ConfigParser(inline_comment_prefixes=(";", "#"))
        cp.read(cfg_path, encoding="utf-8")
        base = cfg_path.parent
        if cp.has_option("paths", "project_root"):
            pr = cp.get("paths", "project_root").strip()
            if pr:
                out["project_root"] = (base / pr).resolve()
        if cp.has_option("server", "host"):
            out["host"] = cp.get("server", "host").strip() or "127.0.0.1"
        if cp.has_option("server", "port"):
            try:
                out["port"] = int(cp.get("server", "port").strip())
            except ValueError:
                pass
        if cp.has_option("refresh", "auto_update"):
            out["auto_update"] = cp.getboolean("refresh", "auto_update", fallback=True)
        log.info("Loaded config: %s", cfg_path)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not parse config %s: %s", cfg_path, e)
    return out


CONFIG = load_config()


def _looks_like_project_root(p: Path) -> bool:
    """True if *p* contains the expected raw-data subfolders."""
    try:
        return all((p / sub).is_dir() for sub in ("Inventory", "Releases", "Process Routings"))
    except OSError:
        return False


def _find_project_root(start: Path) -> Optional[Path]:
    """Walk up from *start* looking for a dir that holds the raw-data folders."""
    for cand in [start, *start.parents]:
        if _looks_like_project_root(cand):
            return cand
    return None


def resolve_project_root() -> Path:
    """Resolve the project root (``Production Planning\\``).

    Order: explicit env/CLI override (future) → walk up from this file →
    walk up from cwd → walk up from the frozen exe dir. Fails loudly.
    """
    # 1. Explicit config override wins, if it points at a valid root.
    cfg_root = CONFIG.get("project_root")
    if cfg_root is not None and _looks_like_project_root(cfg_root):
        return cfg_root
    here = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    candidates = [here, Path.cwd().resolve()]
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.executable).resolve().parent)
    for c in candidates:
        root = _find_project_root(c)
        if root is not None:
            return root
    raise SystemExit(
        "Could not locate the project root (a folder containing "
        f"{RAW_DATA_SUBFOLDERS}). Looked up from: {[str(c) for c in candidates]}"
    )


def patch_trusted_paths(project_root: Path) -> None:
    """Repoint the shared data layer (and graph_allocator_V2's copies) at *project_root*.

    ``allocation_common`` owns ``BASE`` + the ``path_*`` constants; ``rebind_base``
    updates them in place. ``graph_allocator_V2`` imported a subset of those names by
    value at import time, so we refresh its copies too. No module source is edited.
    """
    import allocation_common as common

    common.rebind_base(project_root)

    import graph_allocator_V2 as ga

    ga.BASE = project_root
    for name in ("path_releases", "path_process_routings", "path_attributes", "path_bom_exploded"):
        if hasattr(ga, name):
            setattr(ga, name, getattr(common, name))

    # Sanity: the resolved root must actually hold the raw-data folders.
    for sub in ("Inventory", "Releases", "Process Routings"):
        assert (project_root / sub).is_dir(), f"Expected raw-data folder missing: {project_root / sub}"
    log.info("Project root resolved + paths patched: %s", project_root)


# Resolve + patch, then make the shared modules importable.
PROJECT_ROOT = resolve_project_root()
# IMPORTANT: only import the modules from the on-disk source tree when running as a
# *script* (dev). The frozen .exe carries them bundled inside it; pointing it at the
# OneDrive ``Python Script\`` folder is wrong — on a coworker's machine those .py
# files are often OneDrive "online-only" placeholders that fail to read
# (``OSError [Errno 22] Invalid argument``).
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(PROJECT_ROOT / "Python Script"))
patch_trusted_paths(PROJECT_ROOT)

import graph_allocator_V2 as ga  # noqa: E402
import allocation_common as common  # noqa: E402


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


def run_pipeline() -> PipelineResult:
    """Re-run the V2 allocation pipeline in memory, mirroring ``ga.main()``.

    Returns every object the dashboard needs. Does NOT write any CSV.
    """
    log.info("Loading data...")
    inventory_raw = common.load_inventory()
    releases_raw = ga.load_releases_no_p6_elim()
    process_routing = ga.load_full_process_routing()
    exploded_bom = common.clean_folder(common.path_bom_exploded, common.do_nothing)
    part_attributes = ga.load_part_attributes()
    log.info(
        "Loaded: inventory=%d releases=%d routing_rows=%d bom_rows=%d",
        len(inventory_raw), len(releases_raw), len(process_routing), len(exploded_bom),
    )

    # Paint flags + painted-part universe.
    paint_flags = ga.build_part_paint_flags(process_routing, exploded_bom, part_attributes)
    painted_set: set[str] = set(
        paint_flags.loc[paint_flags["Ecoat"] | paint_flags["Powdercoat"], "Part Number"]
    )

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


# ---------------------------------------------------------------------------
# Parity check vs the existing Allocation_V2.csv
# ---------------------------------------------------------------------------
def parity_check(result: PipelineResult) -> bool:
    """Compare the in-memory allocation against the on-disk Allocation_V2.csv.

    The allocator is non-deterministic in row order only; we compare the
    aggregate that matters: total allocated qty per (Serial No, Release ID)
    and overall row count. Returns True on match.
    """
    ref_path = PROJECT_ROOT / "Allocations" / "Allocation_V2.csv"
    if not ref_path.exists():
        log.warning("No reference Allocation_V2.csv at %s — skipping parity check", ref_path)
        return True

    ref = pd.read_csv(ref_path)
    got = result.alloc_df
    log.info("Parity: reference rows=%d, in-memory rows=%d", len(ref), len(got))

    def agg(df: pd.DataFrame) -> pd.Series:
        d = df.copy()
        # Normalise the join keys so CSV-round-trip dtypes line up with the
        # in-memory frame: the CSV loads Release ID as float (NaN on unallocated
        # rows forces float64), so 0 -> "0.0"; coerce both via Int64 first.
        d["Release ID"] = (
            pd.to_numeric(d["Release ID"], errors="coerce")
            .astype("Int64").astype("string").fillna("<none>")
        )
        d["Serial No"] = d["Serial No"].astype("string").fillna("<none>")
        d["Allocated Qty"] = pd.to_numeric(d["Allocated Qty"], errors="coerce").fillna(0).astype("int64")
        return d.groupby(["Serial No", "Release ID"])["Allocated Qty"].sum().sort_index()

    a_ref, a_got = agg(ref), agg(got)
    same = a_ref.equals(a_got)
    if same:
        log.info("PARITY OK: per-(serial,release) allocated quantities match exactly.")
    else:
        # Report the first few discrepancies.
        joined = pd.concat([a_ref.rename("ref"), a_got.rename("got")], axis=1).fillna(0)
        diff = joined[joined["ref"] != joined["got"]]
        log.warning("PARITY MISMATCH: %d differing (serial,release) groups", len(diff))
        log.warning("Sample diffs:\n%s", diff.head(15).to_string())
    return same


# ===========================================================================
# Payload + detail builders (steps 2, 7, 8)
# ===========================================================================
# Read-only dashboard (design v10): concern is auto-only, no overrides, no
# writable shared state. Everything below is derived from the in-memory
# PipelineResult and served to the browser.

import configparser  # noqa: E402
import json  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import webbrowser  # noqa: E402
from datetime import datetime, date  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from urllib.parse import urlparse, parse_qs  # noqa: E402

# Resolve next to the EXE when frozen (NOT PyInstaller's temp _MEIPASS that
# __file__ points at), so the swatch CSV / snapshot / config the planner edits
# beside the exe are the ones actually used.
HERE = _exe_or_script_dir()
SNAPSHOT_FILE = HERE / "paint_allocation_dashboard_snapshot.json"
SWATCH_CSV = HERE / "powder_colour_swatches.csv"
CONFIG_FILE = HERE / "paint_allocation_dashboard.ini"


def _jsonsafe(v):
    """Coerce pandas/NumPy/Timestamp scalars to JSON-serialisable values."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    if hasattr(v, "item"):
        try:
            return v.item()
        except (ValueError, AttributeError):
            pass
    return v


def _ship_iso(v) -> str:
    s = _jsonsafe(v)
    return s if isinstance(s, str) else ""


def load_swatch_map() -> dict[str, dict]:
    """colour_name -> {"hex", "alias"} from the planner-curated CSV (server-side, B6).

    Schema: ``colour_name, hex, alias``. ``hex`` blank → neutral grey. ``alias``
    is the (optionally longer) label painted inside the swatch; blank → the UI
    falls back to auto-generated initials.
    """
    if not SWATCH_CSV.exists():
        return {}
    try:
        df = pd.read_csv(SWATCH_CSV, dtype=str).fillna("")
        out = {}
        for _, r in df.iterrows():
            name = str(r.get("colour_name", "")).strip()
            hexv = str(r.get("hex", "")).strip()
            alias = str(r.get("alias", "")).strip()
            if name:
                out[name.lower()] = {"hex": hexv or "#9aa0a8", "alias": alias}
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read swatch CSV: %s", e)
        return {}


def _glyph_for(hexv: str) -> str:
    """Contrast-aware glyph colour for initials painted inside a swatch."""
    try:
        h = hexv.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#222" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#fff"
    except Exception:  # noqa: BLE001
        return "#fff"


def _initials(name: str) -> str:
    parts = [p for p in str(name).replace("-", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def paint_badge(ecoat: bool, powdercoat: bool, colour: str, swatch_map: dict) -> Optional[dict]:
    if not (ecoat or powdercoat):
        return None
    if powdercoat:
        cname = colour if colour not in (None, "", "None", "Not Found") else None
        entry = swatch_map.get(str(colour).lower()) if cname else None
        hexv = (entry or {}).get("hex") or "#9aa0a8"
        alias = (entry or {}).get("alias") or ""
        # Swatch label: planner-set alias wins; else auto initials; else "?".
        label = alias if alias else (_initials(cname) if cname else "?")
        badge = {
            "type": "EC+PC" if ecoat else "PC",
            "colourName": cname or "Unknown",
            "colourInitials": label,
            "swatchHex": hexv,
            "glyphHex": _glyph_for(hexv),
        }
        return badge
    return {"type": "EC"}


# ---- derived indexes attached to PipelineResult (built once) --------------
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


from collections import defaultdict  # noqa: E402  (used above)


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


def _raw_data_mtime_epoch() -> float:
    """Most recent file mtime (epoch seconds) across the raw ERP source folders.

    Reads the patched `path_*` on allocation_common (already pointed at the
    resolved project root). Used both for the "Data Pulled At" label and the
    auto-update watcher.
    """
    import os
    dirs = [
        common.path_inv_p6, common.path_inv_p10, common.path_releases,
        common.path_process_routings, common.path_attributes,
        common.path_bom_exploded, common.path_bom_flat,
    ]
    latest = 0.0
    for d in dirs:
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_file():
                        m = e.stat().st_mtime
                        if m > latest:
                            latest = m
        except OSError:
            continue
    return latest


def latest_raw_data_mtime() -> Optional[str]:
    """"MM-DD-YY HH:MM:SS" of the most recent raw-data file, or None."""
    ep = _raw_data_mtime_epoch()
    return datetime.fromtimestamp(ep).strftime("%m-%d-%y %H:%M:%S") if ep > 0 else None


# "Inventory at P10" filter: a container is "at P10" if it is P10-owned, or it is
# a P6 container that has physically transferred to the P10 location (the same
# "Modineer - P10" location test the trusted elim_p6_releases used).
P10_PLANT = "P10"
P10_LOCATION = "Modineer - P10"


def _container_at_p10(c: "ga.Container") -> bool:
    return str(c.container_plant) == P10_PLANT or str(c.location) == P10_LOCATION


def build_queue_payload(result: PipelineResult, idx: Indexes) -> dict:
    """releases[] for the Release Queue, ship-date ASC (design §3.1)."""
    flag_lookup = result.paint_flags.set_index("Part Number")
    rel = result.releases_with_id.copy()
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
            "shipDate": ship,
            "relBal": rel_bal,
            "p10Inventory": _subtree_has_p10(part),
            "coverage": cov,
            "concernAuto": concern,
            "paintBadge": badge,
            "hasPaintedSubcomponents": rid in parents_with_children,
        })

    customers = sorted({r["customer"] for r in releases if r["customer"]})
    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataPulledAt": latest_raw_data_mtime(),
        "releaseCount": len(releases),
        "releases": releases,
        "customers": customers,
        "readOnly": True,
    }


# ---- on-demand detail tree (design §3.2, §4.2, §4.4) ----------------------
def _container_card(c: "ga.Container", node: "ga.Node", alloc_rows_by_serial: dict) -> dict:
    serial = str(c.serial)
    allocated_here = alloc_rows_by_serial.get(serial, 0)
    past = ga_is_past_last_paint(node.part, node.seq)
    return {
        "serial": serial,
        "part": c.part,
        "location": str(c.location),
        "qty": int(c.quantity),
        "allocatedHere": int(allocated_here),
        "pastPaint": bool(past),
        "addDate": _jsonsafe(c.add_date),
        "containerPlant": str(c.container_plant),
        "nextOp": str(c.next_operation),
        "isReworkMrb": False,
    }


def ga_is_past_last_paint(part: str, seq: int) -> bool:
    lp = CURRENT_GRAPH.last_paint_seq.get(part) if CURRENT_GRAPH else None
    return bool(lp is not None and seq >= lp)


CURRENT_GRAPH: Optional["ga.Graph"] = None  # set on each pipeline run


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
        cards = [_container_card(c, n, serial_alloc) for c in n.containers]
        # rework/mrb display-only
        rwk = idx.rework_by_partop.get((part, op), [])
        rework_cards = [{
            "serial": str(x.get("Serial No", "")),
            "part": x.get("Part Number"),
            "location": str(x.get("Location", "")),
            "qty": int(x.get("Quantity") or 0),
            "allocatedHere": 0,
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


# ===========================================================================
# Snapshot cache (step 3) — local, per-machine, derived. Never shared.
# ===========================================================================
def write_snapshot(payload: dict) -> None:
    try:
        tmp = SNAPSHOT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(SNAPSHOT_FILE)
        log.info("Snapshot cached: %s", SNAPSHOT_FILE.name)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not write snapshot: %s", e)


def read_snapshot() -> Optional[dict]:
    if not SNAPSHOT_FILE.exists():
        return None
    try:
        return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read snapshot: %s", e)
        return None


# ===========================================================================
# In-memory app state (read-only; refreshed by POST /refresh)
# ===========================================================================
class AppState:
    def __init__(self):
        self.result: Optional[PipelineResult] = None
        self.idx: Optional[Indexes] = None
        self.queue_payload: Optional[dict] = None
        self.lock = threading.Lock()              # guards the payload swap
        self.refresh_lock = threading.Lock()      # serialises refreshes (manual + watcher)
        self.source_mtime = 0.0                   # raw-data mtime the current payload was built from

    def refresh(self, retries: int = 1) -> dict:
        """Re-run the pipeline + rebuild payloads atomically. Retain-on-failure.

        Serialised by ``refresh_lock`` so a manual Refresh and the auto-update
        watcher never run the pipeline concurrently.
        """
        global CURRENT_GRAPH
        with self.refresh_lock:
            last_err = None
            for attempt in range(retries + 1):
                # Capture the source mtime BEFORE the read so a pull that lands
                # mid-build is caught by the next watcher tick rather than lost.
                src = _raw_data_mtime_epoch()
                try:
                    result = run_pipeline()
                    idx = build_indexes(result)
                    payload = build_queue_payload(result, idx)
                    with self.lock:
                        self.result, self.idx, self.queue_payload = result, idx, payload
                        CURRENT_GRAPH = result.graph
                        self.source_mtime = src
                    write_snapshot(payload)
                    return payload
                except (PermissionError, OSError) as e:
                    last_err = e
                    log.warning("Refresh attempt %d failed (locked file?): %s", attempt + 1, e)
                    time.sleep(2)
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    log.exception("Refresh failed: %s", e)
                    break
            raise RuntimeError(f"Pipeline refresh failed: {last_err}")


STATE = AppState()


# ===========================================================================
# Auto-update watcher — re-runs the pipeline when the ERP files change.
# ===========================================================================
WATCH_POLL_SEC = 15       # how often to check the raw-data folders
WATCH_DEBOUNCE_SEC = 12   # require the mtime to be stable this long before rebuilding


def start_watcher() -> None:
    """Background daemon: rebuild when new raw files are pulled from the ERP.

    Polls the max raw-data mtime. A new pull bumps the mtime; we wait until it
    stops moving (DEBOUNCE) so we don't read a half-written export, then trigger
    ``STATE.refresh()`` (which has its own retry + retain-on-failure). The
    browser's poll picks up the new payload automatically.
    """
    def loop():
        pending = None
        pending_since = 0.0
        while True:
            time.sleep(WATCH_POLL_SEC)
            try:
                cur = _raw_data_mtime_epoch()
            except Exception:  # noqa: BLE001
                continue
            if cur <= STATE.source_mtime:
                pending = None          # nothing newer than the current build
                continue
            if cur != pending:
                pending = cur            # files still arriving — keep waiting
                pending_since = time.monotonic()
                continue
            if time.monotonic() - pending_since >= WATCH_DEBOUNCE_SEC:
                log.info("Raw data changed — auto-refreshing…")
                try:
                    STATE.refresh()
                    log.info("Auto-refresh complete (Data Pulled At %s).", latest_raw_data_mtime())
                except Exception as e:  # noqa: BLE001
                    log.warning("Auto-refresh failed (will retry next tick): %s", e)
                pending = None
    threading.Thread(target=loop, name="erp-watcher", daemon=True).start()
    log.info("ERP auto-update watcher started (poll %ss, debounce %ss).",
             WATCH_POLL_SEC, WATCH_DEBOUNCE_SEC)


# ===========================================================================
# HTTP handler (step 4/5) — read-only endpoints
# ===========================================================================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter console
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            html = HTML_PAGE.replace("__PAYLOAD__", json.dumps(STATE.queue_payload or {}))
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif u.path == "/snapshot":
            self._json(STATE.queue_payload or {})
        elif u.path == "/detail":
            q = parse_qs(u.query)
            key = q.get("key", [""])[0]
            rid = q.get("rid", [""])[0]
            with STATE.lock:
                result, idx = STATE.result, STATE.idx
            try:
                release_id = int(rid)
            except (TypeError, ValueError):
                # resolve from natural key
                release_id = None
                for r in (STATE.queue_payload or {}).get("releases", []):
                    if r["naturalKey"] == key:
                        release_id = r["releaseId"]
                        break
            if release_id is None or result is None:
                self._json({"error": "release not found"}, 404)
                return
            rel_bal = idx.ext_by_id.get(release_id, {}).get("Rel Bal", 0)
            tree = build_detail_tree(result, idx, release_id, int(rel_bal or 0))
            self._json(tree or {"error": "no routing"})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/refresh":
            try:
                payload = STATE.refresh()
                self._json(payload)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 503)
        else:
            self._send(404, b"not found", "text/plain")


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ===========================================================================
# Embedded UI (read-only) — Classic queue (ship-date ASC, day dividers) +
# Stack/Flow detail toggle, heather-gray theme. Mirrors
# paint_dashboard_ui_refined.html, wired to the live payload + /detail.
# ===========================================================================
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paint Allocation Dashboard</title>
<style>
/* Theme: Bold Slate — slate canvas, deep navy header + accent, vivid coverage. */
:root{--bg:#e6e8ee;--panel:#ffffff;--panel-2:#eef1f6;--panel-3:#e2e6ee;--ink:#0b141f;
--muted:#33404f;--faint:#4a576b;--line:#d3d9e2;--line-soft:#e3e7ee;--accent:#27457e;--accent-soft:#e7edf7;
--navy:#27457e;--navy-2:#2f5191;
--c-past:#1f9d4d;--c-paint:#f2bf0b;--c-pipe:#f47b1f;--c-short:#df3b3b;
--t-good:#1f9d4d;--t-low:#f2bf0b;--t-med:#f47b1f;--t-high:#df3b3b;
--mono:'Consolas','SFMono-Regular',ui-monospace,monospace;--sans:'Segoe UI',system-ui,sans-serif}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{font-family:var(--sans);color:var(--ink);background:var(--bg);font-size:14px}
header.app{display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--navy);color:#fff;border-bottom:3px solid #1b3361;box-shadow:0 2px 8px rgba(20,30,55,.25)}
header.app .logo{font-weight:800;letter-spacing:.01em}header.app .logo small{font-weight:400;color:#aebfdc;margin-left:8px}
.spacer{flex:1}.btn{border:1px solid var(--line);background:#fff;border-radius:7px;padding:5px 11px;cursor:pointer;font-size:12px;font-weight:600}
.btn:hover{background:var(--panel-2)}
/* Refresh: bold/poppy white pill on the navy header; animates width on click. */
.btn.refresh{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;background:#fff;color:var(--accent);
 border:none;border-radius:9px;padding:7px 15px;font-size:13.5px;font-weight:800;letter-spacing:.02em;
 cursor:pointer;box-shadow:0 2px 8px rgba(11,20,31,.28);white-space:nowrap;overflow:hidden;
 transition:width .34s cubic-bezier(.34,.01,.2,1),background-color .3s ease,color .3s ease,transform .12s ease}
.btn.refresh:hover{background:#eaf0fa;transform:translateY(-1px);box-shadow:0 4px 12px rgba(11,20,31,.32)}
.btn.refresh:active{transform:translateY(0)}
.btn.refresh.done{background:var(--c-past);color:#fff}
.btn.refresh.fail{background:var(--c-short);color:#fff}
.btn.refresh .rlabel{display:inline-block}
.ricon{width:0;height:16px;overflow:hidden;display:inline-flex;align-items:center;justify-content:center;
 margin-right:0;flex:0 0 auto;transition:width .3s cubic-bezier(.34,.01,.2,1),margin-right .3s cubic-bezier(.34,.01,.2,1)}
.ricon.show{width:16px;margin-right:8px}
.ricon .spin{width:14px;height:14px;border-radius:50%;border:2px solid rgba(39,69,126,.28);border-top-color:var(--accent);animation:rspin .62s linear infinite}
@keyframes rspin{to{transform:rotate(360deg)}}
.twopane{display:grid;grid-template-columns:var(--leftw,46%) 10px minmax(0,1fr);gap:0;padding:12px;height:calc(100vh - 50px)}
/* Draggable splitter between the two panes (left pane resizes; right takes the rest). */
.gutter{align-self:stretch;display:flex;align-items:center;justify-content:center;cursor:col-resize;touch-action:none}
.gutter::before{content:"";width:4px;height:46px;max-height:60%;border-radius:3px;background:var(--line);transition:background .15s ease,width .15s ease}
.gutter:hover::before,.gutter.drag::before{background:var(--accent);width:5px}
body.resizing{cursor:col-resize!important;user-select:none}
.pane{background:var(--panel);border:1px solid var(--line);border-radius:10px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.pane-head{padding:9px 12px;background:var(--panel-2);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
/* Title bars in both panes share a fixed height so "Release Queue" and "Selected
   Release" line up even though the right one carries the taller Stack/Flow toggle. */
.pane-head.headbar{min-height:48px}
.pane-head h3{margin:0;font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:var(--accent);font-weight:700;line-height:1}
.pane-body{overflow:auto;padding:8px;flex:1}
.cov{display:flex;height:9px;width:100%;border-radius:5px;overflow:hidden;background:#dfe2e9;border:1px solid #cdd1da}
.cov.lg{height:12px}.cov span{display:block;height:100%}
.seg-past{background:var(--c-past)}
.seg-paint{background:var(--c-paint)}
.seg-pipe{background:var(--c-pipe)}
.seg-short{background:var(--c-short)}
.cov-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--muted)}
.cov-legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px;border:1px solid #bcc1cb}
.concern{width:17px;height:17px;border-radius:50%;flex:0 0 auto;display:inline-block;border:2px solid currentColor;position:relative}
.concern.good{color:var(--t-good);background:currentColor}
.concern.low{color:var(--t-low);background:linear-gradient(90deg,currentColor 50%,#fff 50%)}
.concern.medium{color:var(--t-med);background:conic-gradient(currentColor 0 75%,#fff 0)}
.concern.high{color:var(--t-high);background:#fff}
.concern.high::after{content:"";position:absolute;inset:3px;border-radius:50%;background:currentColor}
.hidegrp{display:inline-flex;align-items:center;gap:4px}
.hidegrp .hlbl{font-size:11px;color:var(--muted)}
.hchip{display:inline-flex;align-items:center;gap:4px;font-size:11px;padding:3px 7px;border:1px solid var(--line);border-radius:6px;cursor:pointer;background:#fff;user-select:none}
.hchip i{width:9px;height:9px;border-radius:50%;display:inline-block;flex:0 0 auto}
.hchip.on{background:#f0f1f5;color:var(--muted);text-decoration:line-through;border-color:#cdd2db}
.hchip.on i{opacity:.4}
.pbadge{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600}
.pbadge .ec{background:#e7f0ff;color:#1554c0;border:1px solid #bcd2f7;border-radius:4px;padding:1px 5px}
.swatch{min-width:21px;width:auto;height:16px;padding:0 4px;border-radius:3px;border:1px solid rgba(0,0,0,.28);display:inline-flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;line-height:1;white-space:nowrap}
.pie{width:14px;height:14px;border-radius:50%;border:1.5px solid var(--c-past);display:inline-block;flex:0 0 auto}
.filters{display:flex;gap:6px;flex-wrap:wrap;align-items:center;width:100%}
.chip{border:1px solid var(--line);background:#fff;border-radius:16px;padding:3px 9px;font-size:11.5px;cursor:pointer;display:inline-flex;gap:5px;align-items:center}
.chip.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.chip.neg{background:var(--c-short);color:#fff;border-color:var(--c-short)}
/* Filter area: Presets (left) | divider | quick filters (right). */
.filterbar{display:flex;align-items:flex-start;gap:10px;width:100%}
.presets{display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex:0 0 auto;max-width:46%}
.presetchips{display:inline-flex;gap:6px;flex-wrap:wrap}
.fdivider{flex:0 0 auto;align-self:stretch;width:1px;background:var(--line);margin:0 2px}
.quickfilters{display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex:1 1 auto;min-width:0}
.seclbl{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);font-weight:700;white-space:nowrap}
.chip.preset{padding-right:5px}
.chip.preset .px{cursor:pointer;color:var(--faint);font-weight:800;margin-left:1px;padding:0 3px;border-radius:4px;line-height:1}
.chip.preset .px:hover{color:#fff;background:var(--c-short)}
.chip.psave{border-style:dashed;color:var(--accent);border-color:var(--accent);font-weight:700}
.pnone{font-size:11px;color:var(--faint);font-style:italic}
.drange{flex:1;min-width:70px;accent-color:var(--accent);height:14px}
input.search{border:1px solid var(--line);border-radius:7px;padding:5px 9px;font-size:12px;min-width:110px}
/* Shrinkable tracks (minmax(0,…)) so the row always fits the pane — otherwise,
   once the vertical scrollbar narrows the body, the fixed columns overflow and the
   selection highlight (which only paints to the row's box) stops short of the date/qty. */
.qrow{display:grid;grid-template-columns:18px minmax(0,84px) 30px minmax(56px,1fr) minmax(38px,64px) 60px minmax(40px,auto);align-items:center;gap:7px;padding:8px 10px;border-radius:9px;cursor:pointer;border:1px solid transparent;min-width:0;overflow:hidden}
.qrow .plant{font-family:var(--mono);font-size:13px;color:var(--muted);text-align:center}
.qrow:hover{background:var(--accent-soft)}.qrow.sel{background:var(--accent-soft);border-color:var(--accent);border-left:4px solid var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.qrow .cust{color:var(--muted);font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qrow .pnwrap{display:flex;align-items:center;gap:6px;min-width:0}
.qrow .pn{font-family:var(--mono);font-weight:700;font-size:15px;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qrow .date{font-family:var(--mono);color:var(--muted);font-size:13px;white-space:nowrap;text-align:right}.qrow .bal{font-weight:800;font-size:15px;text-align:right}
.copybtn{flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;width:24px;height:22px;padding:0;border:1px solid var(--line);background:#fff;color:var(--faint);border-radius:5px;cursor:pointer}
.copybtn:hover{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.copybtn.ok{background:var(--c-past);border-color:var(--c-past);color:#fff}
.daygroup{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint);margin:8px 8px 2px;display:flex;align-items:center;gap:8px}
.daygroup::after{content:"";flex:1;height:1px;background:var(--line-soft)}
/* Segmented Stack/Flow toggle with a sliding thumb (200ms). */
.seg{position:relative;display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff}
.seg .thumb{position:absolute;top:0;left:0;width:50%;height:100%;background:var(--accent);border-radius:7px;z-index:0;
 transition:transform .2s cubic-bezier(.4,0,.2,1)}
.seg.flow .thumb{transform:translateX(100%)}
.seg button{position:relative;z-index:1;width:74px;text-align:center;border:none;background:transparent;padding:6px 0;
 cursor:pointer;font-size:12px;font-weight:600;color:var(--muted);transition:color .2s ease}
.seg button.on{color:#fff}
@keyframes vfade{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}
.vfade{animation:vfade .2s cubic-bezier(.4,0,.2,1)}
.detailhead{display:flex;align-items:center;gap:10px;padding:8px 4px;flex-wrap:wrap}
.detailhead .pn{font-family:var(--mono);font-weight:700;font-size:14px}.detailhead .meta{color:var(--muted)}
.oprow{border:1px solid var(--line);border-radius:9px;margin:6px 0;background:#fff;overflow:hidden}
.oprow.up{background:var(--panel-3)}.oprow.collapsed .cardstrip,.oprow.collapsed .subroute{display:none}
.ophead{display:flex;align-items:center;gap:10px;padding:8px 10px;cursor:pointer}
.ophead .opname{font-weight:600;min-width:120px}.ophead .opnet{font-family:var(--mono);color:var(--accent);font-weight:700}
.ophead .opnet small{color:var(--muted);font-weight:400}.ophead .caret{color:var(--muted);width:12px;display:inline-block}
.oprow.collapsed .caret{transform:rotate(-90deg)}.ophead.paint{background:linear-gradient(0deg,#fff,#fff7e8)}
.tag-paint{font-size:9.5px;font-weight:700;color:#9a6b00;background:#ffedcc;border:1px solid #f0d18a;border-radius:4px;padding:1px 5px}
.cardstrip{display:flex;gap:6px;overflow-x:auto;padding:4px 8px 9px}
.ccard{flex:0 0 auto;min-width:120px;border:1px solid var(--line);border-radius:8px;padding:6px 8px;background:#fff;cursor:pointer;border-left:4px solid #c3c8d2;position:relative}
.ccard:hover{border-color:#aeb6c4}.ccard.past{border-left-color:var(--c-past)}
.ccard .sn{font-family:var(--mono);font-size:11px}.ccard .loc{font-size:10.5px;color:var(--muted)}
.ccard .qty{font-weight:700;font-size:13px;margin-top:2px}
.ccard .corner{position:absolute;top:6px;right:7px;width:7px;height:7px;border-radius:50%;background:var(--c-past)}
.ccard:not(.past) .corner{display:none}
.ccard.mrb{background:#e9eaee;color:#7b8090;border-left-color:#b7bcc7;font-style:italic;display:flex;align-items:center}
.subroute{margin:0 10px 9px 30px;border:1px dashed #b9c0cc;border-left:3px solid var(--accent);border-radius:9px;background:#f5f8ff}
.subhead{display:flex;align-items:center;gap:8px;padding:7px 10px;cursor:pointer;font-size:12px}
.subhead .lbl{font-weight:700;font-family:var(--mono)}.subhead .xq{font-family:var(--mono);color:var(--muted)}
.subroute .innerops{display:none;padding:0 8px 8px}.subroute.open .innerops{display:block}
.flowwrap{overflow:auto;padding:8px 4px;flex:1}.flowline{display:flex;align-items:flex-start;min-width:max-content;padding-bottom:8px}
.fstage{min-width:152px;max-width:152px;border:1px solid var(--line);border-radius:10px;background:#fff;padding:8px;position:relative;margin-right:32px}
.fstage.up{background:var(--panel-3)}
.fstage::after{content:"";position:absolute;right:-26px;top:34px;width:20px;height:2px;background:#b7bcc7}
.fstage:last-child::after{display:none}.fstage.paint{border-color:#ecc569;background:#fff7e8}
.fstage .fname{font-weight:700;font-size:12px}.fstage .fnet{font-family:var(--mono);color:var(--accent);font-size:11px;margin:1px 0 6px}
.fmini{border:1px solid var(--line);border-radius:6px;margin:3px 0;padding:3px 6px;font-size:10.5px;font-family:var(--mono);background:#fff;cursor:pointer}
.fmini.past{border-left:4px solid var(--c-past)}.fmini.mrb{background:#e9eaee;color:#7b8090;font-style:italic;cursor:default}
.fbranch{margin-top:8px;border-top:1px dashed #b9c0cc;padding-top:6px}.fbranch .bl{font-size:10px;color:var(--accent);font-weight:700;margin-bottom:4px;font-family:var(--mono)}
#pop{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:rgba(20,24,32,.4);z-index:100}
#pop.show{display:flex}#pop .box{background:#fff;border-radius:12px;padding:16px 18px;min-width:310px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
#pop h4{margin:0 0 10px}#pop .frow{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px}
#pop .frow b{font-family:var(--mono)}.note{font-size:11px;color:var(--muted);margin-top:8px}
.empty{color:var(--muted);padding:20px;text-align:center}.readonly{font-size:11px;color:#cdd8ee}
.pulled{font-size:11.5px;color:#dfe6f4;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.28);border-radius:6px;padding:2px 8px;font-family:var(--mono);transition:box-shadow .3s,background .3s}
.pulled.flash{background:rgba(31,157,77,.45);box-shadow:0 0 0 2px var(--c-past)}
</style></head><body>
<header class="app">
  <span class="logo">Paint Allocation Dashboard</span>
  <span id="datapulled" class="pulled"></span>
  <span class="spacer"></span>
  <span class="readonly">read-only view</span>
  <button class="btn refresh" id="refresh"><span class="ricon" aria-hidden="true"></span><span class="rlabel">Refresh</span></button>
</header>
<div class="twopane">
  <div class="pane">
    <div class="pane-head headbar"><h3>Release Queue</h3><span class="spacer"></span>
      <span style="font-size:11px;color:var(--muted)">sort: ship date &uarr;</span></div>
    <div class="pane-head" style="background:#fff">
      <div class="filterbar">
        <div class="presets">
          <span class="seclbl">Views</span>
          <span id="presetChips" class="presetchips"></span>
          <button class="chip psave" id="savePreset" title="Save the current filters as a preset view">+ Save view</button>
          <span class="chip" id="clearFilters" title="Reset all quick filters">Clear</span>
        </div>
        <div class="fdivider"></div>
        <div class="quickfilters">
          <span class="seclbl">Quick&nbsp;filters</span>
          <span class="chip" id="custBtn">+ Customer</span>
          <span class="chip" id="ecChip" data-p="EC">EC</span>
          <span class="chip" id="pcChip" data-p="PC">PC</span>
          <span class="chip" id="colourBtn" style="display:none">Colour &#9662;</span>
          <span class="chip" id="invP10Chip" title="Hide P6 releases that have no inventory anywhere in their routing at P10">Inventory at P10</span>
          <span class="hidegrp" title="Click a condition to hide those releases">
            <span class="hchip" data-k="good"   title="green &middot; fully covered (past paint)"><i style="background:var(--t-good)"></i>Hide Past Paint</span>
            <span class="hchip" data-k="low"    title="yellow &middot; paintable / WIP only"><i style="background:var(--t-low)"></i>Hide WIP only</span>
            <span class="hchip" data-k="medium" title="orange &middot; pipeline only"><i style="background:var(--t-med)"></i>Hide Pipeline only</span>
            <span class="hchip" data-k="high"   title="red &middot; empty pipeline / short"><i style="background:var(--t-high)"></i>Hide Empty Pipeline</span>
          </span>
          <input class="search" id="search" placeholder="part #&hellip;">
          <span class="spacer"></span><span id="count" style="font-size:11px;color:var(--muted)"></span>
        </div>
      </div>
    </div>
    <div id="custPanel" class="pane-head" style="display:none;background:#fff"></div>
    <div id="colourPanel" class="pane-head" style="display:none;background:#fff"></div>
    <div class="pane-head" style="background:#fff">
      <div class="filters" style="align-items:center;flex-wrap:nowrap">
        <span style="font-size:11px;color:var(--muted)">Ship</span>
        <b id="dFrom" style="font-family:var(--mono);font-size:11px;min-width:74px"></b>
        <input type="range" id="dLo" class="drange">
        <input type="range" id="dHi" class="drange">
        <b id="dTo" style="font-family:var(--mono);font-size:11px;min-width:74px;text-align:right"></b>
        <span class="chip" id="dReset">all dates</span>
      </div>
    </div>
    <div class="pane-body" id="queue"></div>
    <div class="pane-head" style="border-top:1px solid var(--line);border-bottom:none">
      <div class="cov-legend">
        <span><i style="background:var(--c-past)"></i>past paint</span>
        <span><i class="seg-paint"></i>paintable</span>
        <span><i class="seg-pipe"></i>pipeline</span>
        <span><i class="seg-short"></i>short</span></div></div>
  </div>
  <div class="gutter" id="gutter" role="separator" aria-orientation="vertical" title="Drag to resize"></div>
  <div class="pane">
    <div class="pane-head headbar"><h3>Selected Release</h3><span class="spacer"></span>
      <div class="seg" id="viewtoggle"><span class="thumb"></span><button data-v="stack" class="on">&#9636; Stack</button><button data-v="flow">&#9655; Flow</button></div></div>
    <div class="detailhead" id="detailhead"><span class="meta">Select a release&hellip;</span></div>
    <div class="pane-body" id="detailStack"></div>
    <div class="flowwrap" id="detailFlow" style="display:none"><div class="flowline" id="flowline"></div></div>
  </div>
</div>
<div id="pop"><div class="box"><h4>&#128230; Container detail</h4><div id="popbody"></div>
  <div class="note">Read-only &middot; Esc or click outside to close</div></div></div>
<script>
let PAYLOAD = __PAYLOAD__;
let SEL = null, VIEW = 'stack', custFilter = new Set(), colourFilter = new Set();
let hideConcern = new Set();             // concern levels to hide: good/low/medium/high
let ecState = 0, pcState = 0;            // 0=off, 1=require, -1=exclude
let invP10 = false;                      // hide P6 releases with no P10 inventory in their routing
let DATES = [], dLo = 0, dHi = 0;        // ship-date range slider (indices into DATES)
const $ = s => document.querySelector(s);

function covBar(c,lg){const t=(c.pastPaint+c.paintable+c.pipeline+c.short)||1;
 return `<div class="cov ${lg?'lg':''}"><span class="seg-past" style="width:${c.pastPaint/t*100}%"></span>
 <span class="seg-paint" style="width:${c.paintable/t*100}%"></span>
 <span class="seg-pipe" style="width:${c.pipeline/t*100}%"></span>
 <span class="seg-short" style="width:${c.short/t*100}%"></span></div>`;}
function concernEl(t){return `<span class="concern ${t}" title="concern: ${t}"></span>`;}
function paintBadge(p){if(!p)return '';if(p.type==='EC')return `<span class="pbadge"><span class="ec">EC</span></span>`;
 const sw=`<span class="swatch" style="background:${p.swatchHex};color:${p.glyphHex}" title="${p.colourName}">${p.colourInitials}</span>`;
 return p.type==='PC'?`<span class="pbadge">${sw}</span>`:`<span class="pbadge"><span class="ec">EC</span>${sw}</span>`;}
function pieStyle(s){if(s>=1)return 'background:var(--c-past)';if(s<=0)return 'background:#fff';
 return `background:conic-gradient(var(--c-past) 0 ${Math.round(s*100)}%,#fff 0)`;}

// Universal "content_copy" icon (two overlapping pages).
const COPY_ICON='<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path fill="currentColor" d="M15.5 1h-11A1.5 1.5 0 0 0 3 2.5V16h2V3h10.5V1zm3 4h-9A1.5 1.5 0 0 0 8 6.5v15A1.5 1.5 0 0 0 9.5 23h9A1.5 1.5 0 0 0 20 21.5v-15A1.5 1.5 0 0 0 18.5 5zM18 21H10V7h8v14z"/></svg>';
const CHECK_ICON='<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M3 8.4l3.2 3.2L13 4.4" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>';
// Refresh-button icons: spinner ring, and a check-in-a-circle for "Refreshed".
const SPINNER='<span class="spin"></span>';
const CHK_CIRCLE='<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="none" stroke="#fff" stroke-width="2"/><path d="M7 12.4l3.3 3.3L17 8.4" fill="none" stroke="#fff" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function fmtDate(iso){if(!iso)return '';const m=/^(\d{4})-(\d{2})-(\d{2})/.exec(iso);return m?m[2]+'-'+m[3]+'-'+m[1].slice(2):iso;}
function fallbackCopy(text,done){const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);done&&done();}
function copyPart(btn,part){
 const orig=btn.innerHTML, ttl=btn.title;
 const done=()=>{btn.classList.add('ok');btn.innerHTML=CHECK_ICON;btn.title='Copied '+part;
   setTimeout(()=>{btn.classList.remove('ok');btn.innerHTML=orig;btn.title=ttl;},900);};
 if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(part).then(done).catch(()=>fallbackCopy(part,done));
 else fallbackCopy(part,done);
}

function renderQueue(){
 const h=$('#queue');h.innerHTML='';
 const term=$('#search').value.trim().toLowerCase();
 let lastDay=null, shown=0;
 PAYLOAD.releases.forEach(r=>{
   if(custFilter.size && !custFilter.has(r.customer))return;
   if(invP10 && r.releasePlant==='P6' && !r.p10Inventory)return;
   if(DATES.length && r.shipDate && (r.shipDate < DATES[dLo] || r.shipDate > DATES[dHi]))return;
   const pt = r.paintBadge ? r.paintBadge.type : '';
   const isEC = pt==='EC'||pt==='EC+PC', isPC = pt==='PC'||pt==='EC+PC';
   if(ecState===1 && !isEC)return;
   if(ecState===-1 && isEC)return;
   if(pcState===1 && !isPC)return;
   if(pcState===-1 && isPC)return;
   if(colourFilter.size){
     const cn = r.paintBadge && r.paintBadge.colourName;
     if(!cn || !colourFilter.has(cn))return;
   }
   if(hideConcern.has(r.concernAuto))return;
   if(term && !(r.part.toLowerCase().includes(term)||r.customer.toLowerCase().includes(term)))return;
   if(r.shipDate!==lastDay){const g=document.createElement('div');g.className='daygroup';g.textContent='Ship '+(fmtDate(r.shipDate)||'—');h.appendChild(g);lastDay=r.shipDate;}
   const d=document.createElement('div');d.className='qrow'+(SEL===r.naturalKey?' sel':'');
   d.innerHTML=`${concernEl(r.concernAuto)}<span class="cust" title="${r.customer}">${r.customer}</span>
     <span class="plant" title="Release Plant">${r.releasePlant||''}</span>
     <span class="pnwrap"><button class="copybtn" title="Copy part number" aria-label="Copy part number">${COPY_ICON}</button><span class="pn">${r.part}</span>${paintBadge(r.paintBadge)}</span>
     ${covBar(r.coverage)}<span class="date">${fmtDate(r.shipDate)}</span><span class="bal">${r.relBal}</span>`;
   d.onclick=()=>{SEL=r.naturalKey;document.querySelectorAll('.qrow').forEach(x=>x.classList.remove('sel'));d.classList.add('sel');loadDetail(r);};
   const cb=d.querySelector('.copybtn');if(cb)cb.addEventListener('click',e=>{e.stopPropagation();copyPart(cb,r.part);});
   h.appendChild(d);shown++;
 });
 $('#count').textContent=shown+' / '+PAYLOAD.releaseCount;
 $('#datapulled').textContent='Data Pulled At: '+(PAYLOAD.dataPulledAt||'unknown');
 // Auto-select the first visible release so the detail pane is never empty.
 if(!SEL){const first=h.querySelector('.qrow');if(first)first.click();}
}

function renderCustPanel(){
 const p=$('#custPanel');
 p.innerHTML='<div class="filters">'+PAYLOAD.customers.map(c=>
   `<span class="chip ${custFilter.has(c)?'on':''}" data-c="${c}">${c}</span>`).join('')+'</div>';
 p.querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{
   const c=ch.dataset.c;custFilter.has(c)?custFilter.delete(c):custFilter.add(c);renderQueue();renderCustPanel();});
}
$('#custBtn').onclick=()=>{const p=$('#custPanel');p.style.display=p.style.display==='none'?'flex':'none';renderCustPanel();};
$('#search').oninput=renderQueue;
// Hide-by-condition chips (good/low/medium/high → green/yellow/orange/red).
document.querySelectorAll('.hchip').forEach(ch=>ch.onclick=()=>{
  const k=ch.dataset.k; hideConcern.has(k)?hideConcern.delete(k):hideConcern.add(k);
  ch.classList.toggle('on',hideConcern.has(k)); renderQueue();});

// Paint-type (EC/PC) + colour filters.
function updateColourBtn(){
 const showCol = pcState===1;
 $('#colourBtn').style.display = showCol ? 'inline-flex' : 'none';
 if(!showCol){colourFilter.clear();$('#colourPanel').style.display='none';}
}
// EC / PC are tri-state: click cycles off → require → exclude ("not …").
function paintChip(id,state,base){const el=$('#'+id);
 el.classList.toggle('on',state!==0);el.classList.toggle('neg',state===-1);
 el.textContent=state===-1?('not '+base):base;}
$('#ecChip').onclick=()=>{ecState=(ecState===0?1:ecState===1?-1:0);paintChip('ecChip',ecState,'EC');renderQueue();};
$('#pcChip').onclick=()=>{pcState=(pcState===0?1:pcState===1?-1:0);paintChip('pcChip',pcState,'PC');updateColourBtn();renderQueue();};
// "Inventory at P10": when on, hides P6 releases whose entire routing has no P10 inventory.
$('#invP10Chip').onclick=()=>{invP10=!invP10;$('#invP10Chip').classList.toggle('on',invP10);renderQueue();};

// Ship-date range slider (defaults to the full range = all releases visible).
function initDateSlider(){
 DATES=[...new Set(PAYLOAD.releases.map(r=>r.shipDate).filter(Boolean))].sort();
 const lo=$('#dLo'),hi=$('#dHi');
 if(DATES.length<2){lo.disabled=hi.disabled=true;dLo=0;dHi=Math.max(DATES.length-1,0);updateDateLabels();return;}
 lo.disabled=hi.disabled=false;
 lo.min=hi.min=0;lo.max=hi.max=DATES.length-1;lo.step=hi.step=1;
 dLo=0;dHi=DATES.length-1;lo.value=dLo;hi.value=dHi;updateDateLabels();
}
function updateDateLabels(){$('#dFrom').textContent=DATES[dLo]||'—';$('#dTo').textContent=DATES[dHi]||'—';}
$('#dLo').oninput=()=>{dLo=Math.min(+$('#dLo').value,dHi);$('#dLo').value=dLo;updateDateLabels();renderQueue();};
$('#dHi').oninput=()=>{dHi=Math.max(+$('#dHi').value,dLo);$('#dHi').value=dHi;updateDateLabels();renderQueue();};
$('#dReset').onclick=()=>{if(!DATES.length)return;dLo=0;dHi=DATES.length-1;$('#dLo').value=dLo;$('#dHi').value=dHi;updateDateLabels();renderQueue();};
function colourHexMap(){const m={};PAYLOAD.releases.forEach(r=>{const b=r.paintBadge;if(b&&b.colourName&&b.swatchHex)m[b.colourName]=b.swatchHex;});return m;}
function colourList(){return [...new Set(PAYLOAD.releases.filter(r=>r.paintBadge&&['PC','EC+PC'].includes(r.paintBadge.type)&&r.paintBadge.colourName&&r.paintBadge.colourName!=='Unknown').map(r=>r.paintBadge.colourName))].sort();}
function renderColourPanel(){
 const cols=colourList(), hex=colourHexMap();
 $('#colourPanel').innerHTML='<div class="filters">'+(cols.length?cols.map(c=>
   `<span class="chip ${colourFilter.has(c)?'on':''}" data-col="${c}"><span style="display:inline-block;width:12px;height:12px;border-radius:3px;border:1px solid rgba(0,0,0,.25);background:${hex[c]||'#9aa0a8'}"></span>${c}</span>`).join('')
   :'<span style="font-size:11px;color:var(--muted)">no powder colours in current data</span>')+'</div>';
 $('#colourPanel').querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{
   const c=ch.dataset.col;colourFilter.has(c)?colourFilter.delete(c):colourFilter.add(c);renderQueue();renderColourPanel();});
}
$('#colourBtn').onclick=()=>{const p=$('#colourPanel');p.style.display=p.style.display==='none'?'flex':'none';renderColourPanel();};

function cardHTML(c){
 if(c.isReworkMrb)return '';
 return `<div class="ccard ${c.pastPaint?'past':''}" onclick='showPop(${JSON.stringify(c).replace(/'/g,"&#39;")})'>
   <span class="corner"></span><div class="sn">${c.serial}</div><div class="loc">${c.location}</div>
   <div class="qty">${c.allocatedHere}/${c.qty}</div></div>`;
}
function mrbCardHTML(op){
 if(!op.reworkCards.length)return '';
 return `<div class="ccard mrb" onclick='showMrb(${JSON.stringify(op.reworkCards).replace(/'/g,"&#39;")})'>MRB Qty: ${op.reworkQty}</div>`;
}
function subHTML(sub){
 const inner=sub.ops.map(o=>`<div class="oprow"><div class="ophead"><span class="caret">&#9662;</span>
   <span class="opname">${o.op}</span><span class="opnet">${o.netQty}<small> net</small></span>
   <span class="pie" style="margin-left:8px;${pieStyle(o.pastPaintShare)}"></span></div></div>`).join('');
 return `<div class="subroute"><div class="subhead" onclick="this.parentNode.classList.toggle('open')">
   <span class="caret">&#9662;</span><span class="lbl">${sub.partNo}</span><span class="xq">net ${sub.bomScaledNet}</span>
   <span style="flex:1;max-width:150px">${covBar(sub.coverage)}</span>${concernEl(sub.concernAuto)}</div>
   <div class="innerops">${inner}</div></div>`;
}
function renderStack(detail){
 const h=$('#detailStack');
 h.innerHTML=detail.ops.map(o=>{
   const cards=o.containers.map(cardHTML).join('')+mrbCardHTML(o);
   const subs=o.subRoutings.map(subHTML).join('');
   return `<div class="oprow ${o.collapsed?'collapsed up':''}">
     <div class="ophead ${o.isPaintOp?'paint':''}" onclick="this.parentNode.classList.toggle('collapsed')">
       <span class="caret">&#9662;</span><span class="opname">${o.op}</span>
       <span class="opnet">${o.netQty}<small> net</small></span>
       <span class="pie" style="${pieStyle(o.pastPaintShare)}" title="past-paint share"></span>
       <span class="spacer"></span>${o.isPaintOp?'<span class="tag-paint">PAINT</span>':''}</div>
     <div class="cardstrip">${cards||'<span class="note">no containers</span>'}</div>${subs}</div>`;
 }).join('');
}
function renderFlow(detail){
 const stages=[...detail.ops].reverse();
 $('#flowline').innerHTML=stages.map(o=>{
   const minis=o.containers.map(c=>`<div class="fmini ${c.pastPaint?'past':''}" onclick='showPop(${JSON.stringify(c).replace(/'/g,"&#39;")})'>${c.serial} &middot; ${c.allocatedHere}/${c.qty}</div>`).join('')
     +(o.reworkCards.length?`<div class="fmini mrb">MRB ${o.reworkQty}</div>`:'');
   const branch=o.subRoutings.map(s=>`<div class="fbranch"><div class="bl">&#8627; ${s.partNo}</div><div style="font-size:9.5px;color:var(--muted)">net ${s.bomScaledNet}</div>${covBar(s.coverage)}</div>`).join('');
   return `<div class="fstage ${o.collapsed?'up':''} ${o.isPaintOp?'paint':''}">
     <div class="fname">${o.op}${o.isPaintOp?' <span class="tag-paint">P</span>':''}</div>
     <div class="fnet">net ${o.netQty}</div>${minis||'<div class="note" style="font-size:10px">—</div>'}${branch}</div>`;
 }).join('');
}
function loadDetail(r){
 $('#detailhead').innerHTML=`${concernEl(r.concernAuto)}<span class="pn">${r.part}</span>${paintBadge(r.paintBadge)}
   <span class="meta">${r.customer} &middot; ship ${r.shipDate} &middot; <b>Bal ${r.relBal}</b></span>
   <span class="spacer"></span><span style="min-width:140px">${covBar(r.coverage)}</span>`;
 $('#detailStack').innerHTML='<div class="empty">loading&hellip;</div>';
 fetch('/detail?rid='+encodeURIComponent(r.releaseId)).then(x=>x.json()).then(d=>{
   if(d.error){$('#detailStack').innerHTML='<div class="empty">'+d.error+'</div>';return;}
   window._detail=d;renderStack(d);renderFlow(d);
 });
}
document.querySelectorAll('#viewtoggle button').forEach(b=>b.onclick=()=>{
 if(b.classList.contains('on'))return;
 document.querySelectorAll('#viewtoggle button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
 VIEW=b.dataset.v;const flow=VIEW==='flow';
 $('#viewtoggle').classList.toggle('flow',flow);          // slide the thumb (200ms)
 const show=flow?$('#detailFlow'):$('#detailStack'), hide=flow?$('#detailStack'):$('#detailFlow');
 hide.style.display='none';show.style.display=flow?'flex':'block';
 show.classList.remove('vfade');void show.offsetWidth;show.classList.add('vfade');  // quick fade-in (200ms)
});

// --- Draggable splitter: resize the release (left) pane; right takes the rest. ---
(function(){
 const tp=document.querySelector('.twopane'), gut=$('#gutter');
 const MIN_LEFT=440, MIN_RIGHT=340, GUT=10;
 const clamp=w=>{const max=tp.clientWidth-24-GUT-MIN_RIGHT;return Math.max(MIN_LEFT,Math.min(Math.max(max,MIN_LEFT),w));};
 const setW=w=>tp.style.setProperty('--leftw',clamp(w)+'px');
 // init from saved width, else the current rendered left-pane width
 let init;try{init=parseFloat(localStorage.getItem('paintLeftW'));}catch(e){}
 if(!init)init=document.querySelector('.pane').getBoundingClientRect().width;
 setW(init);
 let dragging=false,startX=0,startW=0;
 gut.addEventListener('pointerdown',e=>{dragging=true;startX=e.clientX;
   startW=document.querySelector('.pane').getBoundingClientRect().width;
   gut.classList.add('drag');document.body.classList.add('resizing');
   gut.setPointerCapture(e.pointerId);e.preventDefault();});
 gut.addEventListener('pointermove',e=>{if(dragging)setW(startW+(e.clientX-startX));});
 const end=()=>{if(!dragging)return;dragging=false;gut.classList.remove('drag');document.body.classList.remove('resizing');
   try{localStorage.setItem('paintLeftW',parseFloat(tp.style.getPropertyValue('--leftw')));}catch(e){}};
 gut.addEventListener('pointerup',end);gut.addEventListener('pointercancel',end);
 window.addEventListener('resize',()=>{const cur=parseFloat(tp.style.getPropertyValue('--leftw'));if(cur)setW(cur);});
})();
function showPop(c){
 $('#popbody').innerHTML=[['Serial',c.serial],['Part',c.part],['Location',c.location],
  ['Alloc Qty',c.allocatedHere],['Container Qty',c.qty],['Add Date',c.addDate||'—'],
  ['Inventory Plant',c.containerPlant||'—'],['Next Op',c.nextOp||'—']]
  .map(([k,v])=>`<div class="frow"><span>${k}</span><b>${v}</b></div>`).join('');
 $('#pop').classList.add('show');
}
function showMrb(cards){
 $('#popbody').innerHTML='<div style="font-weight:600;margin-bottom:6px">Rework / MRB ('+cards.length+')</div>'+
  cards.map(c=>`<div class="frow"><span>${c.serial} &middot; ${c.location} <small>(${c.status||'MRB'})</small></span><b>0/${c.qty}</b></div>`).join('');
 $('#pop').classList.add('show');
}
$('#pop').onclick=e=>{if(e.target.id==='pop')e.currentTarget.classList.remove('show');};
document.addEventListener('keydown',e=>{if(e.key==='Escape')$('#pop').classList.remove('show');});
const RB=$('#refresh'), RIC=RB.querySelector('.ricon'), RLB=RB.querySelector('.rlabel');
// Smoothly animate the button from its current width to the natural width of the
// new content, while the icon slot slides in/out. `mutate` applies the new label
// + icon + colour and returns whether the icon should be shown afterwards.
function refreshTransition(mutate){
 const startW=RB.getBoundingClientRect().width, startIcon=RIC.classList.contains('show');
 RB.style.transition='none';RIC.style.transition='none';
 const endIcon=!!mutate();
 RIC.classList.toggle('show',endIcon);          // final icon state → measure target width
 RB.style.width='auto';const endW=RB.getBoundingClientRect().width;
 RB.style.width=startW+'px';RIC.classList.toggle('show',startIcon);  // back to start
 RB.offsetWidth;                                // reflow while transitions are off
 RB.style.transition='';RIC.style.transition='';
 requestAnimationFrame(()=>{RB.style.width=endW+'px';RIC.classList.toggle('show',endIcon);});
}
let refreshing=false;
function refreshIdle(){refreshTransition(()=>{RB.classList.remove('done','fail');RLB.textContent='Refresh';return false;});
 setTimeout(()=>{RIC.innerHTML='';RB.style.width='';},380);refreshing=false;}
RB.onclick=()=>{
 if(refreshing)return;refreshing=true;RB.classList.remove('done','fail');
 refreshTransition(()=>{RIC.innerHTML=SPINNER;RLB.textContent='Refreshing';return true;});
 fetch('/refresh',{method:'POST'}).then(x=>x.json()).then(d=>{
   if(d.error)throw new Error(d.error);
   PAYLOAD=d;SEL=null;initDateSlider();renderQueue();
   $('#detailhead').innerHTML='<span class="meta">Select a release&hellip;</span>';
   $('#detailStack').innerHTML='';$('#flowline').innerHTML='';
   refreshTransition(()=>{RB.classList.add('done');RIC.innerHTML=CHK_CIRCLE;RLB.textContent='Refreshed';return true;});
   setTimeout(refreshIdle,1200);
 }).catch(()=>{
   refreshTransition(()=>{RB.classList.add('fail');RIC.innerHTML=CHECK_ICON;RLB.textContent='Failed';return true;});
   setTimeout(refreshIdle,2200);
 });
};

// Auto-update: poll the snapshot; when the server has rebuilt from a new ERP
// pull (dataPulledAt changed), swap in the new payload and re-render in place.
function applyPayload(d){
 PAYLOAD=d;initDateSlider();
 const still=SEL&&PAYLOAD.releases.some(x=>x.naturalKey===SEL);
 if(!still)SEL=null;
 renderQueue();
 if(still){const r=PAYLOAD.releases.find(x=>x.naturalKey===SEL);if(r)loadDetail(r);}
 const chip=$('#datapulled');if(chip){chip.classList.add('flash');setTimeout(()=>chip.classList.remove('flash'),2000);}
}
setInterval(()=>{fetch('/snapshot').then(x=>x.json()).then(d=>{
 if(d&&d.dataPulledAt&&d.dataPulledAt!==PAYLOAD.dataPulledAt)applyPayload(d);
}).catch(()=>{});},15000);

// --- Filter presets: save / apply / delete named filter sets (local only). ---
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function captureFilters(){return {cust:[...custFilter],ec:ecState,pc:pcState,colour:[...colourFilter],
 invP10:invP10,hide:[...hideConcern],search:$('#search').value,
 dateLo:DATES[dLo]||null,dateHi:DATES[dHi]||null};}
function applyFilters(f){
 f=f||{};
 custFilter=new Set(f.cust||[]);ecState=f.ec||0;pcState=f.pc||0;
 colourFilter=new Set(f.colour||[]);invP10=!!f.invP10;hideConcern=new Set(f.hide||[]);
 $('#search').value=f.search||'';
 paintChip('ecChip',ecState,'EC');paintChip('pcChip',pcState,'PC');updateColourBtn();
 $('#invP10Chip').classList.toggle('on',invP10);
 document.querySelectorAll('.hchip').forEach(ch=>ch.classList.toggle('on',hideConcern.has(ch.dataset.k)));
 if(DATES.length){
   let lo=0,hi=DATES.length-1;
   if(f.dateLo){const i=DATES.findIndex(d=>d>=f.dateLo);if(i>=0)lo=i;}
   if(f.dateHi){for(let k=0;k<DATES.length;k++){if(DATES[k]<=f.dateHi)hi=k;}}
   if(lo>hi){lo=0;hi=DATES.length-1;}
   dLo=lo;dHi=hi;const el=$('#dLo'),eh=$('#dHi');if(el){el.value=dLo;eh.value=dHi;}updateDateLabels();
 }
 if($('#custPanel').style.display!=='none')renderCustPanel();
 if($('#colourPanel').style.display!=='none')renderColourPanel();
 renderQueue();
}
let PRESETS={};
function loadPresets(){try{PRESETS=JSON.parse(localStorage.getItem('paintPresets')||'{}')||{};}catch(e){PRESETS={};}}
function persistPresets(){try{localStorage.setItem('paintPresets',JSON.stringify(PRESETS));}catch(e){}}
function renderPresets(){
 const c=$('#presetChips');const names=Object.keys(PRESETS);
 if(!names.length){c.innerHTML='<span class="pnone">no saved views</span>';return;}
 c.innerHTML=names.map(n=>`<span class="chip preset" data-n="${esc(n)}" title="Apply view “${esc(n)}”">${esc(n)}<b class="px" title="Delete view">&times;</b></span>`).join('');
 c.querySelectorAll('.preset').forEach(ch=>ch.onclick=e=>{
   const n=ch.dataset.n;
   if(e.target.classList.contains('px')){e.stopPropagation();delete PRESETS[n];persistPresets();renderPresets();return;}
   applyFilters(PRESETS[n]);
 });
}
$('#savePreset').onclick=()=>{
 const name=(prompt('Save current filters as a view — name:')||'').trim();
 if(!name)return;
 if(PRESETS[name]&&!confirm('A view named “'+name+'” exists. Overwrite it?'))return;
 PRESETS[name]=captureFilters();persistPresets();renderPresets();
};
$('#clearFilters').onclick=()=>applyFilters({dateLo:DATES[0]||null,dateHi:DATES[DATES.length-1]||null});

initDateSlider();renderQueue();loadPresets();renderPresets();
</script></body></html>"""



# ===========================================================================
# Entry point
# ===========================================================================
def main() -> None:
    log.info("Paint Allocation Dashboard starting (read-only, design v10)")

    # Fast open from snapshot if present, then build fresh in memory.
    cached = read_snapshot()
    if cached:
        STATE.queue_payload = cached
        log.info("Loaded cached snapshot (%s releases) for instant open.",
                 cached.get("releaseCount"))

    STATE.refresh()  # build live; overwrites cache
    if "--parity" in sys.argv:
        parity_check(STATE.result)

    # Auto-update when new ERP files are pulled (config: [refresh] auto_update).
    if CONFIG.get("auto_update", True) and "--no-watch" not in sys.argv:
        start_watcher()

    host = CONFIG.get("host", "127.0.0.1")
    port = CONFIG.get("port") or _free_port()
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    log.info("Serving dashboard at %s  (Ctrl+C / close window to stop)", url)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        httpd.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log.exception("Dashboard failed: %s", e)
        input("Press Enter to close...")
        sys.exit(1)
