"""
Painted Parts Inventory Allocation (legacy allocator)
=====================================================
Loads inventory, customer releases, process routings, and BOM data, then allocates
on-hand inventory containers to open customer releases in ship-date order, writing
the results to ``<project_root>/Allocations/``.

The shared ERP-data layer (project-root/path resolution, the ``.xlsx`` loader, the
raw-export cleaners, and the common routing helpers) lives in
:mod:`allocation_common`; this module imports those and adds the legacy
allocation-specific logic on top.

Outputs
-------
Three CSV files are written to ``<project_root>/Allocations/``:

* **Inventory.csv**   – Cleaned, enriched inventory with routing context.
* **Releases.csv**    – Cleaned releases including generated internal releases.
* **Allocation.csv**  – Row-per-allocation linking containers to releases.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Shared ERP-data layer. These names are also re-exported for tools that still
# import them from this module (e.g. graph_visualize_V2).
from allocation_common import (  # noqa: F401
    BASE,
    add_prev_next_operation,
    apply_revision_suffix,
    clean_folder,
    clean_process_routing_file,
    clean_release_file,
    do_nothing,
    extract_plant_from_source_file,
    internal_op_nos,
    load_inventory,
    path_attributes,
    path_bom_exploded,
    path_bom_flat,
    path_process_routings,
    path_releases,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing enrichment
# ---------------------------------------------------------------------------

def routing_painted_parts(df: pd.DataFrame) -> pd.DataFrame:
    """Retain only part numbers that pass through an EC or PC operation.

    Filters the routing table to parts that have at least one electrocoat
    (EC) or powdercoat (PC) operation, which are the parts this tool tracks.
    """
    pns = df[df["Operation"].str.contains("EC|PC", na=False)]["Part Number"].unique()
    return df[df["Part Number"].isin(pns)]


# ---------------------------------------------------------------------------
# BOM helpers
# ---------------------------------------------------------------------------

def build_bom_components(
    flat_bom: pd.DataFrame,
    process_routing: pd.DataFrame,
) -> pd.DataFrame:
    """Extract painted sub-components from the flat BOM.

    Returns rows where the *component* part number is itself a painted part
    (i.e. it has an EC or PC operation in the routing).  Sheet-metal
    components are excluded as they are tracked separately.

    Returns
    -------
    pandas.DataFrame
        Columns: ``Release Part Number``, ``Customer``, ``BOM Quantity``,
        ``Part Number``.
    """
    flat_bom = flat_bom.rename(
        columns={
            "Part-Rev":            "Release Part Number",
            "Total BOM Qty":       "BOM Quantity",
            "Component Part-Rev":  "Part Number",
            "Customer Code":       "Customer",
        }
    )

    flat_bom = flat_bom[
        ~flat_bom["Component Part Type"].str.contains("Sheet", na=True)
    ]

    paint_pns = process_routing[
        process_routing["Operation"].str.contains("EC|PC", na=False)
    ]["Part Number"].unique()

    bom_components = flat_bom[flat_bom["Part Number"].isin(paint_pns)]

    return bom_components[
        ["Release Part Number", "Customer", "BOM Quantity", "Part Number"]
    ]


def build_changing_pns(df: pd.DataFrame) -> pd.DataFrame:
    """Extract level-1 BOM components that are painted in-house.

    Targets components at BOM level 1 that are linked to a paint operation
    (EC/PC) via the ``Op No - Code`` field in the exploded BOM export.

    Returns
    -------
    pandas.DataFrame
        Columns: ``Release Part Number``, ``Customer``, ``BOM Quantity``,
        ``Part Number``.
    """
    df = df.rename(
        columns={
            "Part-Rev":           "Release Part Number",
            "Component Part-Rev": "Part Number",
            "Customer Code":      "Customer",
        }
    )

    df = df[df["BOM Level"] == 1]
    df = df[
        df["Part Number"].notna()
        & (df["Part Number"] != "")
        & (~df["Part Number"].str.startswith(".", na=False))
    ]
    df = df[df["Op No - Code"].str.contains("EC|PC", na=False)]

    return df[["Release Part Number", "Customer", "BOM Quantity", "Part Number"]]


# ---------------------------------------------------------------------------
# Release helpers
# ---------------------------------------------------------------------------

def elim_p6_releases(
    inventory: pd.DataFrame,
    releases: pd.DataFrame,
) -> pd.DataFrame:
    """Remove P6 releases for parts whose inventory has already moved to P10.

    A P6 container recorded at location ``Modineer - P10`` means the part
    has physically transferred and will ship from P10.  The corresponding P6
    release should therefore be suppressed to avoid double-counting.
    """
    p6_inv = inventory[
        (inventory["Container Plant"] == "P6")
        & (inventory["Location"] == "Modineer - P10")
    ]
    p6_pns = p6_inv["Part Number"].unique()

    return releases[
        (releases["Release Plant"] == "P10")
        | (
            (releases["Release Plant"] == "P6")
            & (releases["Part Number"].isin(p6_pns))
        )
    ]


def create_internal_releases(
    releases: pd.DataFrame,
    bom_parts: pd.DataFrame,
) -> pd.DataFrame:
    """Explode customer releases into internal releases for painted sub-components.

    For each customer release, if the released part number has painted
    sub-components in the BOM, a corresponding internal release is created
    for each component.  The quantity is scaled by the BOM quantity.

    The ``Customer`` field on internal releases is set to
    ``Internal-<original customer>-Release ID:<id>`` to distinguish them
    from external releases.

    New ``Release ID`` values are appended after the highest existing ID so
    that original IDs are never modified.
    """
    new_rows = []

    for pn in releases["Part Number"].unique():
        rel_grp    = releases[releases["Part Number"] == pn]
        components = bom_parts[bom_parts["Release Part Number"] == pn]

        if components.empty:
            continue

        for _, this_rel in rel_grp.iterrows():
            for _, comp in components.iterrows():
                new_row = this_rel.copy()
                new_row["Customer"] = (
                    f"Internal-{this_rel['Customer']}"
                    f"-Release ID:{this_rel['Release ID']}"
                )
                new_row["Part Number"] = comp["Part Number"]
                new_row["Rel Bal"]     = this_rel["Rel Bal"] * comp["BOM Quantity"]
                new_rows.append(new_row)

    if not new_rows:
        return releases

    new_df   = pd.DataFrame(new_rows)
    combined = pd.concat([releases, new_df], ignore_index=True)

    max_existing_id = releases["Release ID"].max()
    num_new  = len(new_df)
    new_ids  = range(max_existing_id + 1, max_existing_id + 1 + num_new)
    combined.loc[len(releases):, "Release ID"] = list(new_ids)

    return combined


# ---------------------------------------------------------------------------
# Part attributes
# ---------------------------------------------------------------------------

def create_part_data(process_routing: pd.DataFrame) -> pd.DataFrame:
    """Build a part-level attribute table with paint-process flags.

    Combines powder colour data from the Part Attributes export with boolean
    flags derived from the process routing indicating whether each part
    passes through electrocoat (EC) or powdercoat (PC) operations.

    When a part has multiple attribute rows, the row with a non-null powder
    colour is preferred.
    """
    pr = process_routing.copy()
    pr["Ecoat"]      = pr["Operation"].str.contains("EC", na=False)
    pr["Powdercoat"] = pr["Operation"].str.contains("PC", na=False)
    pr = pr.groupby("Part Number", as_index=False)[["Ecoat", "Powdercoat"]].any()

    df = clean_folder(path_attributes, do_nothing)
    df = df[["Part Number", "Powder Colour"]]
    df = df.merge(pr, on="Part Number", how="right")
    df = df.drop_duplicates().reset_index(drop=True)

    # Prefer rows that carry a powder colour value
    df = df.sort_values(
        by=["Part Number", "Powder Colour"],
        ascending=[True, False],
        na_position="last",
    )
    df = df.drop_duplicates(subset=["Part Number"], keep="first")

    return df


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def merge_allocation_context(
    output: pd.DataFrame,
    inventory: pd.DataFrame,
    part_data: pd.DataFrame,
    releases: pd.DataFrame,
) -> pd.DataFrame:
    """Merge inventory, part, and release context into allocation output.

    Combines location/routing data from inventory, paint-process flags
    from part_data, and customer info from releases into a single output row.
    """
    output = output.merge(
        inventory[
            ["Serial No", "Location", "Quantity", "Add Date",
             "Operation Code", "Next Operation"]
        ].rename(columns={"Quantity": "Total Container Quantity"}),
        on="Serial No",
        how="left",
    )

    output = output.merge(
        part_data,
        left_on="Part No",
        right_on="Part Number",
        how="left",
    )

    output = output.merge(
        releases[["Customer", "Release Plant"]],
        left_on="Release ID",
        right_index=True,
        how="left",
    )

    output["Ecoat"]      = output["Ecoat"].fillna(False).astype(bool)
    output["Powdercoat"] = output["Powdercoat"].fillna(False).astype(bool)

    return output


def allocate_inventory_to_releases(
    inventory: pd.DataFrame,
    releases: pd.DataFrame,
    part_data: pd.DataFrame,
) -> pd.DataFrame:
    """Allocate on-hand inventory containers to open customer releases.

    Algorithm
    ---------
    Inventory containers are sorted by ``Internal Op No`` descending (most
    finished first) and ``Quantity`` ascending (smallest containers first,
    to minimise partial splits).  For each container the earliest open
    release for the same part number is filled first, then the next, and so
    on until the container is exhausted or all releases are satisfied.

    Containers with no matching release are recorded with a sentinel ship
    date of ``9999-12-31`` so they sort to the bottom of the output.

    Parameters
    ----------
    inventory:
        Cleaned, routing-enriched inventory.
    releases:
        Cleaned releases including internal releases.
    part_data:
        Part-level attribute table from :func:`create_part_data`.

    Returns
    -------
    pandas.DataFrame
        One row per allocation event, merged with inventory location /
        routing context, part attributes, and release customer information.
        Sorted by ``Ship Date`` then ``Part No``.
    """
    inv = inventory.copy()
    rel = releases.copy()

    inv["Quantity"] = inv["Quantity"].astype(int)
    rel["Rel Bal"]  = rel["Rel Bal"].astype(int)

    rel      = rel.set_index("Release ID")
    rel_bal  = rel["Rel Bal"].to_dict()
    rel_index = (
        rel.groupby("Part Number").apply(lambda x: x.index.tolist()).to_dict()
    )

    output_rows = []

    inv = inv.sort_values(
        by=["Internal Op No", "Quantity"],
        ascending=[False, True],
    ).reset_index(drop=True)

    for _, inv_row in inv.iterrows():
        part_no  = inv_row["Part Number"]
        serial   = inv_row["Serial No"]
        inv_qty  = int(inv_row["Quantity"])

        if part_no not in rel_index:
            # No open release for this part — record as unallocated
            output_rows.append(
                {
                    "Part No":       part_no,
                    "Serial No":     serial,
                    "Allocated Qty": inv_qty,
                    "Ship Date":     datetime(9999, 12, 31),
                    "Release ID":    None,
                    "Rel Bal":       None,
                }
            )
            continue

        for rid in rel_index[part_no]:
            if inv_qty <= 0:
                break

            remaining = rel_bal.get(rid, 0)
            if remaining <= 0:
                continue

            alloc    = min(inv_qty, remaining)
            output_rows.append(
                {
                    "Part No":       part_no,
                    "Serial No":     serial,
                    "Allocated Qty": alloc,
                    "Ship Date":     rel.loc[rid, "Ship Date"],
                    "Release ID":    rid,
                    "Rel Bal":       rel.loc[rid, "Rel Bal"],
                }
            )
            inv_qty      -= alloc
            rel_bal[rid] -= alloc

    output = pd.DataFrame(output_rows)

    output = merge_allocation_context(output, inventory, part_data, rel)

    output["Ship Date"]  = pd.to_datetime(output["Ship Date"])

    return output.sort_values(
        by=["Ship Date", "Part No"],
        ascending=[True, True],
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_releases(inventory: pd.DataFrame) -> pd.DataFrame:
    """Load, enrich, and filter releases."""
    releases = clean_folder(path_releases, clean_release_file)
    releases = extract_plant_from_source_file(releases, "Release Plant")
    releases = elim_p6_releases(inventory, releases)
    releases = releases.sort_values("Ship Date").reset_index(drop=True)
    return releases


def load_process_routing() -> pd.DataFrame:
    """Load and prepare process routing."""
    process_routing = clean_folder(path_process_routings, clean_process_routing_file)
    process_routing = extract_plant_from_source_file(process_routing, "Routing Plant")
    process_routing = process_routing.drop_duplicates(
        subset=["Part Number", "Operation", "Routing Plant"],
        keep="first",
    )
    process_routing = routing_painted_parts(process_routing)
    process_routing = internal_op_nos(process_routing)
    return process_routing


def load_bom(process_routing: pd.DataFrame) -> pd.DataFrame:
    """Load and combine BOM components."""
    flat_bom = clean_folder(path_bom_flat, do_nothing)
    flat_bom = build_bom_components(flat_bom, process_routing)

    exploded_bom = clean_folder(path_bom_exploded, do_nothing)
    exploded_bom = build_changing_pns(exploded_bom)

    bom_parts = (
        pd.concat([flat_bom, exploded_bom], ignore_index=True)
        .drop_duplicates(subset=["Release Part Number", "Part Number"], keep="first")
    )
    return bom_parts


def filter_to_painted_parts(
    inventory: pd.DataFrame,
    releases: pd.DataFrame,
    process_routing: pd.DataFrame,
) -> tuple:
    """Filter datasets to only painted parts and assign release IDs."""
    painted_pns = process_routing["Part Number"].unique()
    inventory = inventory[inventory["Part Number"].isin(painted_pns)].reset_index(drop=True)
    releases = releases[releases["Part Number"].isin(painted_pns)].reset_index(drop=True)
    releases["Release ID"] = releases.index
    return inventory, releases


def enrich_inventory_with_routing(
    inventory: pd.DataFrame,
    process_routing: pd.DataFrame,
) -> pd.DataFrame:
    """Enrich inventory with operational context from process routing."""
    inventory = add_prev_next_operation(inventory, process_routing)

    duplicate_cols = ["Operation No", "Active", "Source File", "Routing Plant",
                      "Internal Op No"]

    inventory = (
        inventory
        .merge(
            process_routing.drop(columns=duplicate_cols),
            left_on=["Part Number", "Operation Code"],
            right_on=["Part Number", "Operation"],
            how="left",
        )
        .drop(columns=["Operation_y"])
        .rename(columns={"Operation_x": "Operation"})
    )
    return inventory


def write_output_csvs(
    base_path: Path,
    inventory: pd.DataFrame,
    releases: pd.DataFrame,
    output: pd.DataFrame,
) -> None:
    """Write allocation results to CSV files."""
    base_path.mkdir(exist_ok=True)
    inventory.to_csv(base_path / "Inventory.csv",   index=False)
    releases.to_csv( base_path / "Releases.csv",    index=False)
    output.to_csv(   base_path / "Allocation.csv",  index=False)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the full inventory-allocation pipeline and write output CSVs."""

    log.info("Loading and cleaning data...")

    inventory = load_inventory()
    releases = load_releases(inventory)
    process_routing = load_process_routing()
    bom_parts = load_bom(process_routing)

    inventory, releases = filter_to_painted_parts(inventory, releases, process_routing)
    releases = create_internal_releases(releases, bom_parts)
    part_data = create_part_data(process_routing)

    inventory = enrich_inventory_with_routing(inventory, process_routing)

    log.info("Allocating inventory to releases...")
    output = allocate_inventory_to_releases(inventory, releases, part_data)

    log.info("Writing output CSVs...")
    write_output_csvs(BASE / "Allocations", inventory, releases, output)

    log.info("Done. Output written to %s", BASE / "Allocations")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Pipeline failed: %s", e)

    input("Press Enter to close...")
