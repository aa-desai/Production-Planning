"""
Shared ERP-data layer for the paint-allocation tools
=====================================================
Common building blocks used by every tool in this project:

* ``inventory_to_release_allocation.py`` — the legacy allocator (InventoryAllocator.exe)
* ``graph_allocator_V2.py``              — the graph allocation engine (GraphAllocator.exe)
* ``PaintAllocationDashboard\\paint_allocation_dashboard.py`` — the read-only dashboard

It owns the project-root / folder-path resolution, the ``.xlsx`` loader
(``engine="calamine"``), the raw-export cleaners, and a handful of routing/allocation
helpers. Keeping them here means there is one definition of each — the tools import
from this module rather than copying logic.

Configuration
-------------
Folder names and plant codes default to the values below and may be overridden by an
optional ``allocation_config.ini`` (searched next to this file / one level up / the
project root). The defaults match the live folder layout, so the tools run with no
config file present; the file exists only to make those values explicit and editable.
"""

from __future__ import annotations

import configparser
import logging
import sys
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

CONFIG_FILENAME = "allocation_config.ini"

# Defaults — used as-is when no allocation_config.ini is found, and as the base that
# any config file overrides on a per-key basis.
_CONFIG_DEFAULTS: dict[str, dict[str, str]] = {
    "folders": {
        "inventory_p6": "Inventory P6",
        "inventory_p10": "Inventory",
        "releases": "Releases",
        "process_routings": "Process Routings",
        "part_attributes": "Part Attributes",
        "bom": "BOM",
        "exploded_bom": "Exploded BOM",
        "flat_bom": "Flat BOM",
        "allocations": "Allocations",
    },
    "plants": {
        "p6": "P6",
        "p10": "P10",
        "p10_location": "Modineer - P10",
    },
}


# ---------------------------------------------------------------------------
# Path / config resolution
# ---------------------------------------------------------------------------

def get_base_path() -> Path:
    """Return the project root directory regardless of how the tool is run.

    Resolution order:

    1. **PyInstaller bundle** – sibling of the frozen executable.
    2. **Jupyter / IPython** – parent of the current working directory.
    3. **Normal Python script** – two levels up from this file (i.e. the parent of
       ``Python Script\\``).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    if "__file__" not in globals():
        return Path.cwd().resolve().parent
    return Path(__file__).resolve().parent.parent


def _config_dir() -> Path:
    """Directory to look in first for ``allocation_config.ini``."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return Path.cwd()


def _load_config(base: Path) -> configparser.ConfigParser:
    """Load ``allocation_config.ini`` over the built-in defaults, if it exists.

    Searched, first match wins: the module/exe directory, one level up, then the
    project root. A missing file (or unreadable keys) silently leaves the defaults
    in place.
    """
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    cp.read_dict(_CONFIG_DEFAULTS)
    d = _config_dir()
    for cand in (d / CONFIG_FILENAME, d.parent / CONFIG_FILENAME, base / CONFIG_FILENAME):
        if cand.is_file():
            try:
                cp.read(cand, encoding="utf-8")
                log.info("Loaded allocation config: %s", cand)
            except Exception as e:  # noqa: BLE001
                log.warning("Could not read %s (using defaults): %s", cand, e)
            break
    return cp


def _build_paths(base: Path) -> dict[str, Path]:
    """Compute ``BASE`` + every ``path_*`` constant from *base* and the config."""
    f = _CONFIG["folders"]
    bom_base = base / f["bom"]
    return {
        "BASE": base,
        "path_inv_p6": base / f["inventory_p6"],
        "path_inv_p10": base / f["inventory_p10"],
        "path_releases": base / f["releases"],
        "path_process_routings": base / f["process_routings"],
        "path_attributes": base / f["part_attributes"],
        "path_bom_base": bom_base,
        "path_bom_exploded": bom_base / f["exploded_bom"],
        "path_bom_flat": bom_base / f["flat_bom"],
        "path_allocations": base / f["allocations"],
    }


def rebind_base(new_base: Path) -> None:
    """Repoint ``BASE`` and every ``path_*`` constant at *new_base*.

    The dashboard resolves the project root at runtime (for OneDrive portability)
    and calls this so the loaders read from the resolved root rather than wherever
    this module happened to import from.
    """
    globals().update(_build_paths(Path(new_base)))


BASE = get_base_path()
_CONFIG = _load_config(BASE)

# Plant codes / the P10 staging location, exposed for the tools that need them.
PLANT_P6 = _CONFIG.get("plants", "p6")
PLANT_P10 = _CONFIG.get("plants", "p10")
P10_LOCATION = _CONFIG.get("plants", "p10_location")

# Initialise BASE + path_* (path_inv_p6, path_inv_p10, path_releases,
# path_process_routings, path_attributes, path_bom_base, path_bom_exploded,
# path_bom_flat, path_allocations) into the module namespace.
globals().update(_build_paths(BASE))


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def do_nothing(df: pd.DataFrame) -> pd.DataFrame:
    """Pass-through cleaner used where no transformation is needed.

    Satisfies the ``clean_func`` contract required by :func:`clean_folder`.
    """
    return df


def clean_folder(folder_path: Path, clean_func) -> pd.DataFrame:
    """Load every ``.xlsx`` file in *folder_path*, clean it, and combine.

    Parameters
    ----------
    folder_path:
        Directory containing one or more ``.xlsx`` exports.
    clean_func:
        Callable ``(DataFrame) -> DataFrame`` applied to each file after
        loading.  Use :func:`do_nothing` when no transformation is required.

    Returns
    -------
    pandas.DataFrame
        Row-wise concatenation of all cleaned files.  A ``Source File``
        column records the originating filename for traceability.

    Raises
    ------
    ValueError
        If no ``.xlsx`` files exist in *folder_path*, or if every file fails
        to process.
    """
    folder = Path(folder_path)
    files = list(folder.glob("*.xlsx"))

    if not files:
        raise ValueError(f"No .xlsx files found in {folder}")

    dfs = []
    for file in files:
        try:
            df = pd.read_excel(file, engine="calamine")
            cleaned = clean_func(df)
            cleaned["Source File"] = file.name
            dfs.append(cleaned)
            log.debug("Loaded %s (%d rows)", file.name, len(cleaned))
        except Exception as e:
            log.warning("Skipping %s: %s", file.name, e)

    if not dfs:
        raise ValueError(f"All files in {folder} failed to process.")

    combined = pd.concat(dfs, ignore_index=True)
    log.info("Loaded %d rows from %s (%d files)", len(combined), folder.name, len(dfs))
    return combined


def apply_revision_suffix(
    df: pd.DataFrame,
    part_col: str,
    revision_col: str,
    mask: pd.Series,
) -> pd.DataFrame:
    """Apply revision suffix to part numbers where mask is True.

    Creates or updates the ``Part Number`` column by appending
    ``-Rev-<Revision>`` for rows matching the mask.
    """
    df["Part Number"] = df[part_col]
    df.loc[mask, "Part Number"] = (
        df.loc[mask, part_col] + "-Rev-" + df.loc[mask, revision_col]
    )
    return df


# ---------------------------------------------------------------------------
# Raw-export cleaners
# ---------------------------------------------------------------------------

def clean_inventory_file(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise a raw inventory export.

    Key transformations
    -------------------
    * Appends ``-Rev-<Revision>`` to the part number when a revision is
      present and the container is not in a blocked status (MRB / Rework /
      Hold).
    * Drops non-unit-of-measure ``Ea`` rows (no piece-count tracking for
      other UoMs).
    * Removes containers held in locations that are not relevant to the
      painted-parts workflow (Sheet stock, HSG, JLTV, Weld Station,
      Retirement, MRB).
    * Drops columns that carry no value downstream.
    """
    mask = (
        df["Revision"].notna()
        & (df["Revision"] != "")
        & (df["Container Status"] != "MRB")
        & (df["Container Status"] != "Rework")
        & (df["Container Status"] != "Hold")
    )

    df = apply_revision_suffix(df, "Part No", "Revision", mask)

    df = df[df["Unit"] == "Ea"]

    df = df.drop(
        columns=[
            "Part No", "Revision", "Name", "Part Count", "Supplier Code",
            "Job Template Status", "Job Template No", "Job Template",
            "Inventory Type", "Accounting Job Status Color",
            "Accounting Job Status", "Accounting Job No", "Expiration Date",
            "Linear Weight", "Part Name", "Tracking No", "Customer Part No",
            "Unit", "Job No", "Defect Type", "Operation Type",
            "Master Unit No", "Lot No", "Shipper Container Exists",
            "Container Type", "Net Weight", "Heat No", "Heat Code",
            "Material Code", "Card No", "Containers",
        ]
    )

    df = df[
        ~df["Location"].str.contains(
            r"Sheet|HSG|JLTV|Weld Station|Retirement|MRB",
            case=False,
            na=False,
        )
    ]

    return df


def clean_release_file(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise a raw customer-release export.

    Key transformations
    -------------------
    * Removes internal transfer rows (Modineer P6 / P10 customers).
    * Splits compound ``Part No/Cust Part`` and ``Ship Date/Shipper No``
      columns that the ERP exports as newline-delimited pairs.
    * Parses ``Ship Date`` to a Python ``date``.
    * Drops columns not needed downstream.
    """
    df = df[
        (df["Customer"] != "Modineer - P10")
        & (df["Customer"] != "Modineer - P6")
    ]

    df = df.drop(
        columns=["Schedule Quantity", "Dock Code", "Rel Type", "Time",
                 "PO Rel", "Total Rel Due"]
    )

    df[["Part Number", "Cust Part"]] = df["Part No/Cust Part"].str.split(
        "\n", n=1, expand=True
    )
    df[["Ship Date", "Shipper No"]] = df["Ship Date/Shipper No"].str.split(
        "\n", n=1, expand=True
    )

    df["Ship Date"] = pd.to_datetime(df["Ship Date"], errors="coerce").dt.date

    df = df.drop(
        columns=["Part No/Cust Part", "Cust Part", "Ship Date/Shipper No",
                 "Shipper No"]
    )

    return df


def clean_process_routing_file(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise a raw process-routing export.

    Key transformations
    -------------------
    * Removes rework operations, which are not part of the standard flow.
    * Applies the same revision-suffix logic used in
      :func:`clean_inventory_file` so part numbers match across datasets.
    * Drops columns not needed downstream.
    """
    df = df[
        (df["Operation"] != "Rework")
        & (df["Operation"] != "Rework - Subcontract")
    ]

    mask = df["Revision"].notna() & (df["Revision"] != "")
    df = apply_revision_suffix(df, "Part No", "Revision", mask)

    df = df.drop(
        columns=[
            "Part No", "Revision", "Part Op Type", "Suboperation",
            "Net Weight", "Standard Value", "Minimum Inventory", "Multiple",
            "Standard Container Type", "Standard Quantity",
            "Operation Description", "Label Format Key", "Location",
            "Bulletin", "Minimum Quantity", "Scrap", "Shippable",
            "Other Note", "Flowchart Symbol",
        ]
    )

    return df


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

def reorder_both(group: pd.DataFrame) -> pd.DataFrame:
    """Reorder routing rows for parts that run through both P6 and P10.

    Parts processed at both plants follow one of two patterns:

    * **No subcontract** – all P6 operations come before all P10 operations.
    * **Subcontract present** – P6 operations up to (and including) the
      subcontract handoff come first, then all P10 operations, then any
      remaining P6 operations (e.g. final inspection after return from P10).
    """
    group = group.sort_values("Operation No").copy()

    subcontract_mask = group["Operation"].str.contains("Subcontract", na=False)

    if subcontract_mask.any():
        max_sub_op = group.loc[subcontract_mask, "Operation No"].max()

        p6_rows   = group[group["Routing Plant"] == "P6"].sort_values("Operation No")
        p6_before = p6_rows[p6_rows["Operation No"] <  max_sub_op]
        p6_after  = p6_rows[p6_rows["Operation No"] >= max_sub_op]
        p10_rows  = group[group["Routing Plant"] == "P10"].sort_values("Operation No")

        return pd.concat([p6_before, p10_rows, p6_after], ignore_index=True)

    p6_rows   = group[group["Routing Plant"] == "P6"].sort_values("Operation No")
    p10_rows  = group[group["Routing Plant"] == "P10"].sort_values("Operation No")
    other_rows = group[~group["Routing Plant"].isin(["P6", "P10"])]

    return pd.concat([p6_rows, other_rows, p10_rows], ignore_index=True)


def internal_op_nos(df: pd.DataFrame) -> pd.DataFrame:
    """Assign a continuous ``Internal Op No`` across all plants for each part.

    Standard ERP operation numbers reset per plant.  This function produces
    a single cross-plant sequence so that inventory containers can be sorted
    by production progress regardless of which plant they are at.

    For parts that go through a paint operation (EC/PC), all operations
    *before* the paint step are zeroed out so that pre-paint inventory sorts
    below in-process and finished inventory.
    """
    df = df.drop_duplicates(subset=["Part Number", "Operation", "Routing Plant"])

    p6_pns   = set(df[df["Routing Plant"] == "P6"]["Part Number"].unique())
    p10_pns  = set(df[df["Routing Plant"] == "P10"]["Part Number"].unique())

    df_p10   = df[df["Part Number"].isin(p10_pns - p6_pns)].copy()
    df_p6    = df[df["Part Number"].isin(p6_pns - p10_pns)].copy()
    df_both  = df[df["Part Number"].isin(p6_pns & p10_pns)].copy()

    df_both = pd.concat(
        [reorder_both(g) for _, g in df_both.groupby("Part Number")],
        ignore_index=True,
    )

    df_final = pd.concat([df_both, df_p10, df_p6], ignore_index=True)
    df_final["Internal Op No"] = df_final.groupby("Part Number").cumcount() + 1

    def apply_ec_pc_rule(group: pd.DataFrame) -> pd.DataFrame:
        """Zero out Internal Op No for all operations before the first paint step."""
        group = group.sort_values("Internal Op No").copy()
        mask_ec_pc = group["Operation"].str.contains("EC|PC", case=False, na=False)

        if mask_ec_pc.any():
            first_paint_pos = mask_ec_pc.to_numpy().argmax() - 1
            group.iloc[
                :first_paint_pos,
                group.columns.get_loc("Internal Op No"),
            ] = 0

        return group

    df_final = pd.concat(
        [apply_ec_pc_rule(g) for _, g in df_final.groupby("Part Number")],
        ignore_index=True,
    )

    return df_final


def add_prev_next_operation(
    inventory: pd.DataFrame,
    process_routing: pd.DataFrame,
) -> pd.DataFrame:
    """Annotate each inventory row with the operations immediately before and after it.

    Uses the process routing to look up the predecessor and successor
    operations for the operation code recorded on each inventory container.
    Containers whose operation code does not appear in the routing receive
    ``"None"`` for both fields.

    Parameters
    ----------
    inventory:
        Cleaned inventory DataFrame.  Must contain ``Part Number`` and
        ``Operation Code``.
    process_routing:
        Cleaned routing DataFrame with ``Internal Op No`` already assigned
        (see :func:`internal_op_nos`).

    Returns
    -------
    pandas.DataFrame
        *inventory* with ``Prev Operation`` and ``Next Operation`` columns
        added.
    """
    inv     = inventory.copy()
    routing = process_routing.copy()

    routing = routing.dropna(subset=["Part Number", "Operation No", "Operation"])
    inv     = inv.dropna(subset=["Part Number", "Operation No"])

    routing["Operation No"] = pd.to_numeric(routing["Operation No"], errors="coerce")
    routing = routing.dropna(subset=["Operation No"])

    routing = routing.drop_duplicates(
        subset=["Part Number", "Operation", "Routing Plant"],
        keep="first",
    )

    routing = routing.sort_values(["Part Number", "Internal Op No"])

    # Shift within each part's sequence to get adjacent operations
    routing["Prev Operation"] = routing.groupby("Part Number")["Operation"].shift(1)
    routing["Next Operation"] = routing.groupby("Part Number")["Operation"].shift(-1)
    routing[["Prev Operation", "Next Operation"]] = routing[
        ["Prev Operation", "Next Operation"]
    ].fillna("None")

    lookup = routing[
        ["Part Number", "Operation", "Prev Operation", "Next Operation",
         "Internal Op No", "Routing Plant"]
    ]

    result = inv.merge(
        lookup,
        left_on=["Part Number", "Operation Code", "Container Plant"],
        right_on=["Part Number", "Operation", "Routing Plant"],
        how="left",
        validate="many_to_one",  # surfaces accidental duplicates in the routing
    )

    result["Prev Operation"] = result["Prev Operation"].fillna("None")
    result["Next Operation"] = result["Next Operation"].fillna("None")

    return result


def extract_plant_from_source_file(df: pd.DataFrame, target_col: str) -> pd.DataFrame:
    """Extract plant code from Source File column.

    Parses filename patterns like "P6 - xxx" or "P10 - yyy" to extract the
    plant code and populate the target column.

    Parameters
    ----------
    df:
        DataFrame with ``Source File`` column.
    target_col:
        Name of column to populate with extracted plant code.

    Returns
    -------
    pandas.DataFrame
        DataFrame with ``target_col`` populated from ``Source File``.
    """
    df[target_col] = (
        df["Source File"]
        .str.split(" - ", n=1).str[1]
        .str.split(" ", n=1).str[0]
    )
    return df


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_inventory() -> pd.DataFrame:
    """Load and combine inventory from both plants."""
    inventory = pd.concat(
        [
            clean_folder(path_inv_p6,  clean_inventory_file).assign(Plant="P6"),
            clean_folder(path_inv_p10, clean_inventory_file).assign(Plant="P10"),
        ],
        ignore_index=True,
    ).rename(columns={"Plant": "Container Plant"})
    return inventory


# ---------------------------------------------------------------------------
# Allocation sanity check
# ---------------------------------------------------------------------------

def output_allocation_check(output: pd.DataFrame, check_num: int) -> None:
    """Verify that no container has been allocated more than its on-hand quantity.

    Parameters
    ----------
    output:
        Allocation DataFrame containing ``Serial No``, ``Allocated Qty``,
        and ``Total Container Quantity``.
    check_num:
        Identifier used in the error message to pinpoint which check failed.

    Raises
    ------
    ValueError
        If any container's total allocated quantity exceeds its on-hand
        quantity.
    """
    over_allocated = (
        output.groupby("Serial No")["Allocated Qty"].sum()
        > output.groupby("Serial No")["Total Container Quantity"].first()
    )

    if over_allocated.any():
        bad = over_allocated[over_allocated].index.tolist()
        raise ValueError(
            f"Over-allocation detected at check {check_num} "
            f"for serial numbers: {bad}"
        )
