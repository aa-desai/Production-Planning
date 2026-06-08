# `graph_allocator_V2.py` — Technical Reference & Handoff Notes

Graph-based inventory→release paint allocation engine for the Modineer P6/P10
paint operation.

> **Status: proof of concept.** This engine works against live ERP exports and
> produces the allocation the planning team uses today, but it was built to prove
> the approach — not as a hardened production service. It reads manually-placed
> Excel exports from a OneDrive folder tree, has no automated test suite, and is
> tightly coupled to a sibling helper module. This document is written for the IT
> team taking it toward a structured implementation: it covers **what it does, what
> it reads, what it writes, what it depends on, and where the rough edges are.**
> For the *why* of any individual algorithm step, the in-code docstrings and
> comments are authoritative.

---

## 1. What it does

It models the full multi-plant routing **and** multi-level BOM as a single
directed graph, then allocates on-hand inventory to open customer releases by
walking the graph.

- **Nodes** are `(part, operation)` pairs from the process routings.
- **Routing edges** join consecutive operations of one part (upstream-only).
- **Component edges** join a parent operation to the components consumed at that
  operation (from the exploded BOM), scaled by BOM quantity.
- On-hand **inventory containers** are attached to the node matching their
  `(part, operation)`.

For each customer release (processed in ship-date FIFO order), the engine walks
**upstream** from the release part's final operation: it consumes on-hand stock at
each operation first, then explodes the unmet demand down into painted
sub-components as *internal releases*, and continues until demand is met or the top
of the routing is reached. Only **painted** (Ecoat / Powdercoat) material reaches
the final allocation output.

All output files carry a `_V2` suffix so the legacy production CSVs from
`inventory_to_release_allocation.py` are never overwritten.

---

## 2. System context

- **ERP source of truth:** Plex. Today the engine does **not** talk to Plex
  directly — it reads `.xlsx` reports a planner exports and drops into the folder
  tree below. *(The exception is `Part Attributes`, which has no Plex report and is
  maintained by hand — see §10.)*
- **Plants:** P6 and P10. Containers and releases each carry a plant; the engine is
  multi-plant throughout.
- **Consumers of the output:** the CSVs feed downstream planning tools, and the
  **Paint Allocation Dashboard** imports this module and re-runs the pipeline in
  memory for its read-only UI (see §7).

---

## 3. How to run

### From source (development)

From the **project root** (`…\Production Planning\`):

```powershell
venv\Scripts\python.exe "Python Script\graph_allocator_V2.py"
```

### Packaged executable

`build-GraphAllocator.ps1` (project root) builds a standalone `GraphAllocator.exe`
via PyInstaller using the project venv. Each exe has its own `build-<Name>.ps1`
script; `build.ps1` runs all of them in turn.

### Runtime behaviour

- The project root is auto-detected by `allocation_common.get_base_path()`:
  frozen-exe sibling → Jupyter cwd parent → two levels up from this file.
- Run as `__main__`, it logs progress to stdout and waits on `Press Enter to close…`
  at the end (convenient for a double-clicked `.exe`).
- It can also be **imported** as a library — the dashboard calls its functions
  directly rather than `main()`.

---

## 4. Inputs (read-only)

Raw ERP exports live under the project root and are resolved through the
`path_*` constants in `allocation_common` (the folder names are configurable — see
§6). Every file is **`.xlsx`**, read with `pd.read_excel(engine="calamine")`.
**None of these are modified.** Each folder may contain one or more files; all are
concatenated.

| Folder (under project root) | `path_*` constant       | Plex report                          |
|-----------------------------|-------------------------|--------------------------------------|
| `Inventory P6\`             | `path_inv_p6`           | Inventory (P6)                       |
| `Inventory\`                | `path_inv_p10`          | Inventory (P10)                      |
| `Releases\`                 | `path_releases`         | Customer Releases and Scheduling     |
| `Process Routings\`         | `path_process_routings` | Process Routings                     |
| `Part Attributes\`          | `path_attributes`       | **None — locally maintained** (§10)  |
| `BOM\Exploded BOM\`         | `path_bom_exploded`     | Exploded BOM                         |

Key columns the engine relies on (after the `allocation_common` cleaners run):

- **Inventory** — `Serial No`, `Part Number`, `Operation Code`, `Quantity`,
  `Location`, `Container Plant` (P6/P10), `Add Date`, `Next Operation`,
  `Container Status` (Rework/MRB are set aside).
- **Releases** — `Part Number`, `Customer`, `Rel Bal`, `Ship Date`,
  `Release Plant` (P6/P10).
- **Process Routing** — `Part Number`, `Operation`, `Internal Op No`,
  `Routing Plant`.
- **Exploded BOM** — `BOM Part-Rev`, `Component Part-Rev`, `Op No - Code`,
  `BOM Quantity`.
- **Part Attributes** — `Part No` + `Revision` (→ `Part Number`), `Powder Colour`.

---

## 5. Outputs

Written to `…\Production Planning\Allocations\`. Column names are preserved exactly
(downstream tools depend on them).

### 5.1 `Allocation_V2.csv` — main output (one row per allocation)

Painted allocation rows (a release consuming a container), plus unallocated
painted-container rows (sentinel `Ship Date` 9999-12-31, blank release fields,
`Unmatched Reason` set so no painted container is ever silently dropped).

Base columns:
`Container Part Number`, `Release Part Number`, `Serial No`, `Allocated Qty`,
`Ship Date`, `Release ID`, `Rel Bal`, `Location`, `Total Container Quantity`,
`Add Date`, `Operation Code`, `Next Operation`, `Container Plant`, `Customer`,
`Release Plant`, `Past Last Paint Op`, `Unmatched Reason`, `Ecoat`, `Powdercoat`,
`Powder Colour`.

**`Filter:` columns** (added by `attach_filter_columns`, mirroring the interactive
dashboard's filters). Per-release values are computed for the **top-level external
release** a row serves — internal/sub-component rows roll up to their parent — then
denormalised onto every row:

| Column                     | Meaning                                                                                                     | Values                                                       |
|----------------------------|-------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------|
| `Filter: Customer`         | top-level release customer (never the synthetic `Internal-…` string)                                        | text                                                         |
| `Filter: EC`               | release part is e-coated                                                                                    | True / False                                                 |
| `Filter: PC`               | release part is powder-coated                                                                               | True / False                                                 |
| `Filter: Colour`           | powder colour of the release part                                                                           | text / `None` / `Not Found`                                  |
| `Filter: Inventory at P10` | any container in the release's **entire routing subtree** sits at P10 (P10-owned, or moved to `Modineer - P10`) | True / False                                                 |
| `Filter: Condition`        | coverage class of the release                                                                               | `Past Paint` / `WIP only` / `Pipeline only` / `Empty Pipeline` |
| `Filter: Ship Date`        | release ship date                                                                                           | `YYYY-MM-DD`                                                 |

`Filter: Condition` mapping (coverage vs. release balance `b`; `p` = past-paint,
`a` = paintable / next-op-is-EC-or-PC, `l` = pipeline):
`p ≥ b → Past Paint` · `p+a ≥ b → WIP only` · `p+a+l ≥ b → Pipeline only` ·
else `Empty Pipeline`.

> Unallocated rows (no `Release ID`) have **blank** `Filter:` values for the
> per-release fields. Releases with **zero** allocations (all "Empty Pipeline") have
> no row in this file at all — inherent to the per-row granularity.

### 5.2 `Releases_V2.csv` — external + internal releases

External customer release columns plus, for generated internal (sub-component)
releases: `Release ID`, `Parent Release ID`, `Consumed At Op`, `Parent Part`.
Internal rows carry a synthetic `Internal-<customer>-Release ID:N` customer.

### 5.3 `Inventory_V2.csv` — cleaned, allocation-eligible inventory

The inventory used for allocation, enriched with `Prev Operation` /
`Next Operation` / `Internal Op No` / `Routing Plant`. Excludes Rework/MRB.

### 5.4 `Rework_MRB_V2.csv` — sidelined containers

Containers with a Rework operation or `Container Status` ∈ {MRB, Rework,
Rework Subcontract}. Listed for visibility; **never allocated**.

---

## 6. Dependencies & packages

Built and verified against the project `venv\`:

| Package          | Version | Why                                                            |
|------------------|---------|----------------------------------------------------------------|
| Python           | 3.12.10 | runtime (matches the bundled `_python_calamine.cp312` extension) |
| pandas           | 3.0.2   | all dataframe work                                             |
| python-calamine  | 0.6.2   | the `engine="calamine"` `.xlsx` reader (compiled Rust extension) |
| numpy            | 2.4.4   | pandas dependency                                              |
| pyinstaller      | 6.20.0  | only for building the standalone `.exe`                        |

**Standard library:** `logging`, `sys`, `collections`, `configparser`,
`dataclasses`, `datetime`, `pathlib`, `typing`.

**Local dependency (not on PyPI)** — `allocation_common.py` in the same
`Python Script\` folder: the **shared ERP-data layer** that every tool in the
project builds on. It owns `get_base_path()` / `BASE`, the `path_*` constants, the
`engine="calamine"` reader, the per-file cleaners, and the helpers reused here
(`clean_folder`, `clean_process_routing_file`, `clean_release_file`,
`extract_plant_from_source_file`, `internal_op_nos`, `load_inventory`,
`add_prev_next_operation`, `output_allocation_check`, …). `graph_allocator_V2.py`
adds the graph builder and allocator on top of it.

**Configuration** — `allocation_config.ini` (next to `allocation_common.py`) holds
the raw-data folder names, plant codes, and the `Modineer - P10` staging location.
Every value defaults to the live layout *in code*, so the tools run with no config
file present; the file makes those values explicit and editable. To override values
for a packaged `.exe`, place a copy of the file next to that `.exe`.

> The other tools share this layer too: `inventory_to_release_allocation.py` (the
> legacy `InventoryAllocator`) and the Paint Allocation Dashboard both import
> `allocation_common` rather than redefining the cleaners/paths.

---

## 7. Consumers / relationships

- **Standalone CSV run** — `graph_allocator_V2.py` writes the four CSVs in §5.
- **Paint Allocation Dashboard**
  (`PaintAllocationDashboard\paint_allocation_dashboard.py`) imports this module and
  re-runs the pipeline **in memory** for its read-only UI. The dashboard does **not**
  call `main()`, so it never writes CSVs. The `Filter:` columns in §5.1 are the CSV
  mirror of the dashboard's interactive filters and were verified to produce
  identical per-release Condition / Inventory-at-P10 / Customer values.

---

## 8. Invariants / guarantees

- Raw ERP inputs are never modified; all outputs use the `_V2` suffix.
- Only Ecoat / Powdercoat material appears in `Allocation_V2.csv`.
- No container is over-allocated; every painted container appears in the output
  (allocated and/or as an unallocated remainder row).
- The BOM graph is asserted to be a DAG (`_assert_dag`) — a self-consuming part
  fails loudly rather than looping.

---

## 9. Code map

The module reads top-to-bottom as a pipeline. Main building blocks:

| Section                    | Functions                                                                 |
|----------------------------|---------------------------------------------------------------------------|
| Data model                 | `Container`, `ComponentEdge`, `Node`, `Graph`, `ReleaseAnchor` (dataclasses) |
| Loaders                    | `load_full_process_routing`, `load_part_attributes`, `load_releases_no_p6_elim` |
| Op-string normalisation    | `normalize_bom_op`, `op_base_name`                                        |
| Paint classification       | `build_part_paint_flags`                                                  |
| Graph construction         | `build_graph`, `_assert_dag`                                              |
| Reachability               | `reachable_parts`, `filter_releases_by_paint`                            |
| Allocation                 | `anchor_releases`, `allocate_via_graph` (the core upstream traversal)    |
| Dashboard-parity filters   | `attach_filter_columns`, `_bucket_rows`, `concern_from_coverage`, `_container_at_p10` |
| Orchestration              | `write_v2_outputs`, `main`                                                |