# Paint Allocation Dashboard

In-memory paint allocation + floor runlist system for the Modineer P6/P10 paint operation.
Replaces the `Allocation_V2.csv` Excel workflow with a live, read-only planner dashboard and
two read-only shop-floor runlist views.

> **Status / handoff note (for IT):** working internal tool, built as a structured proof of
> concept. It reads manually-exported Plex `.xlsx` reports from a OneDrive folder tree, has no
> automated test suite, and runs as PyInstaller exes launched from `.bat` files. This README is
> the technical handoff: what it does, the modules, what it reads/writes, and the rough edges.
> Deep detail: [DESIGN.md](PaintAllocationDashboard/DESIGN.md) (behaviour spec) and
> [PROGRESS.md](PaintAllocationDashboard/PROGRESS.md) (build log); in-code docstrings are
> authoritative for individual algorithm steps.

---

## 1. System overview

```
Plex ERP ──(planner exports .xlsx into folder tree)──► allocation engine (in memory)
                                                            │
                              ┌─────────────────────────────┴────────────┐
                              ▼                                          ▼
               PaintAllocationDashboard.exe                    GraphAllocator.exe
               planner UI: queue + detail + runlist            batch run → Allocations\*.csv
               authoring (localhost web app)                   (same engine, CSV output)
                              │ publishes runlist_live.json
                  ┌───────────┴───────────┐
                  ▼                       ▼
        PaintRunlistPC.exe        PaintRunlistEC.exe
        PC floor view             EC floor view (read-only, poll & re-render)
```

- Everything runs **locally** (`127.0.0.1`, free port, opens browser). No services, no DB.
- The planner dashboard re-runs the allocation pipeline in memory; it writes **no ERP data** —
  only its own runtime files (§6).
- One planner instance is the runlist **writer** (lock-owner); floor viewers and extra planner
  instances are read-only consumers.

## 2. Allocation logic (engine)

`graph_allocator_V2` models routing + BOM as one directed graph and allocates by walking it:

- **Nodes** = `(part, operation)` from Process Routings; **routing edges** join consecutive ops
  of a part (upstream-only); **component edges** join a parent op to the components consumed
  there (exploded BOM, qty-scaled). On-hand **containers** attach to their `(part, op)` node.
- Releases are processed in **ship-date FIFO**. Each walks **upstream** from its part's final
  op: consume on-hand stock at each op, explode unmet demand into painted sub-components as
  *internal releases*, stop when met or the routing top is reached.
- Only **painted** (Ecoat/Powdercoat) material is allocated. Paint-op detection is
  **case-sensitive** `"EC"`/`"PC"` substring (real ops are `EC-Load`, `PC-Hang`, …; ops like
  `Inspection`/`Receive` do not match). Rework/MRB containers are set aside, never allocated.
- Per release, allocations bucket into **coverage**: past-paint / paintable (at the paint op) /
  pipeline (upstream) / short — shown as the queue's coverage bar and concern tier.
- The BOM is asserted to be a DAG; no container is over-allocated.

## 3. Runlist logic (planner → floor)

- **Select & push:** the planner selects whole releases (queue checkboxes, ordered) and/or
  individual containers (detail pane), then pushes to the **PC** or **EC** draft runlist.
  - *Eligibility:* a push only takes containers still **upstream of** the target paint op
    (never repaint); ineligible ones are reported as skipped.
  - *Quantity:* partially-allocated containers prompt Required / Entire / manual qty.
  - *Over-allocation cascade:* qty beyond the release balance spills to later same-part
    releases (FIFO); nothing is dropped.
  - *PC→EC deficit:* a PC push that exceeds e-coated feedstock auto-adds EC items (amber,
    flagged for review; checkmark to acknowledge).
- **Draft → publish:** edits land in a per-machine draft; **Publish** copies it to the shared
  `Runlists\runlist_live.json`, which the floor views poll (~15 s). First-ever publish never
  blocks on a stale lock.
- **Single-writer lock:** `runlist_owner.lock` + 10-min heartbeat; same machine+user reclaims
  instantly; a stale foreign lock is seized only after a missed-heartbeat confirmation window.
- **Reconciliation:** on every refresh **and a 5-minute heartbeat**, containers that have
  advanced to/past their list's **last EC / last PC op** (or left inventory) are removed, and
  partially-run quantities reduced; the reconciled list is republished automatically. A
  release stays listed until its balance is met.

## 4. Modules & responsibilities

`PaintAllocationDashboard\paint_dashboard\` (the app package):

| Module | Responsibility |
|---|---|
| `app.py` / `__main__.py` | entry point: bootstrap, snapshot fast-open, watcher + reconcile heartbeat, serve |
| `config.py` / `bootstrap.py` | `paint_allocation_dashboard.ini`, project-root/shared-dir resolution |
| `pipeline.py` | runs the vendored engine in memory → `PipelineResult` (daily graph cache + per-refresh allocation) |
| `engine/` | **vendored byte-identical copy** of `graph_allocator_V2` + `allocation_common` |
| `state.py` | `AppState`: refresh under lock, retain-on-failure, runlist reconcile hook |
| `watcher.py` | ERP folder watcher (auto-refresh on new pull) + 5-min reconcile heartbeat |
| `indexes.py` / `coverage.py` / `payload.py` / `serialization.py` / `swatches.py` | derived lookups, coverage/concern classification, queue payload + detail tree, JSON safety, colour swatches |
| `snapshot.py` | local + shared snapshot pool (instant open) |
| `server.py` | HTTP endpoints (read-only data + runlist authoring POSTs) |
| `ui.py` | the entire planner single-page UI (embedded HTML/JS) |
| `views.py` | shared saved-views bank (creator-owned) |
| `parity.py` | optional check vs the on-disk `Allocation_V2.csv` |
| `runlists/` | `model` (RunItem/doc) · `store` (draft/live JSON, atomic) · `lock` (single-writer) · `push` (eligibility, cascade, EC-deficit, publish, reset, ack) · `reconcile` (remove/reduce run containers) · `grouping` (PC colour→release) · `viewer` + `ui` (stdlib-only floor pages) |

`Python Script\` (engine source of truth — dashboard vendors a copy):

| File | Responsibility |
|---|---|
| `graph_allocator_V2.py` | the allocation engine (graph build + upstream allocator + CSV outputs) |
| `allocation_common.py` | shared ERP-data layer: paths, `.xlsx` readers/cleaners, `allocation_config.ini` |
| `graph_visualize_V2.py` | graph visualisation utility (imports the engine + legacy allocator) |
| `inventory_to_release_allocation.py` | legacy allocator — **kept only as a `graph_visualize_V2` dependency** |

## 5. UI reference (what every button does)

**Header:** `Runlist editor` opens the reorder/publish editor · `Rebuild graph` reloads
routing/BOM mid-day (else cached per day) and re-allocates · `Refresh` re-reads inventory/
releases and re-allocates (animated status).

**Release queue (left):** per-row **checkbox** selects the whole release for pushing (badge =
selection order) · the leftmost cell shows a **yellow caution sign** when the release's oldest
allocated inventory is **≥ 4 days old** (blank otherwise) · row click opens detail · copy icon
copies the part number · rows with a
**faint red wash are "overdue"** (only releases due today or earlier — never future) — past
their (P6-shifted) ship date, or one of ≥2 releases sharing the same customer/part/ship-to/ship-date ·
each row also shows **"Oldest Added"** (the earliest add date of the containers allocated to it)
next to the colour badge, and rows are sorted **oldest-first within each ship-date block** · **Views** save/apply/delete personal filter presets;
**Shared** publishes them to all planners · quick filters: `+ Customer`, `EC`/`PC` (tri-state:
off → require → exclude), `Colour ▾`, `Inventory at P10`, coverage condition chips in two sections
— **Any** (partial: the bar has *some* / *none* of a bucket) and **All** (whole bar: the *entire*
bar *is* / *is not* a bucket), each chip tri-state (click = is, click again = is not, again = off)
over Past Paint / WIP / Pipeline / Short — part/customer search, ship-date range sliders + `all dates` ·
draggable splitter between panes. A slim **loading bar** at the top of the page shows while any
action (refresh, push, publish, …) is running.

**Selected release (right):** `Stack`/`Flow` toggle switches detail layout · runbar (under the
title): `Select allocation` ticks the viewed release's allocated containers · `Push → PC` /
`Push → EC` push everything selected (releases in tick order, then loose containers) to that
draft · draft counts · `Publish` copies draft → live floor list · lock owner shown · container
**checkboxes** select individual containers (partial containers prompt Required/Entire/manual
qty) · clicking a card shows container details.

**Runlist editor:** drag rows to reorder; drag a **group header** (PC: colour → part; EC: part)
to move its whole block; headers recompute on drop · header click **collapses/expands** a group ·
**✓** on amber auto-added EC acknowledges it (clears the review banner) · `Save order` persists ·
`Confirm & Publish` saves + publishes (also auto-publishes every 10 min while open) ·
`Reset to live` reverts a pane's draft to the published list · `Clear` empties a pane's draft ·
`Close`.

**Floor pages (PC/EC):** read-only; poll and re-render; rows animate out when reconciliation
removes a run container.

## 6. Data: inputs, outputs, runtime files

**Inputs** — `.xlsx` exports dropped under the project root (`…\Production Planning\`); all
files in each folder are concatenated; **never modified**. Read with pandas + `calamine`.

| Folder | Plex report | Key columns used |
|---|---|---|
| `Inventory\` (P10), `Inventory P6\` | Inventory | `Serial No`, `Part Number`, `Operation Code`, `Quantity`, `Location`, `Container Plant`, `Add Date`, `Next Operation`, `Container Status` |
| `Releases\` | Customer Releases & Scheduling | `Part Number`, `Customer`, `Rel Bal`, `Ship Date`, `Release Plant` |
| `Process Routings\` | Process Routings | `Part Number`, `Operation`, `Internal Op No`, `Routing Plant` |
| `BOM\Exploded BOM\` | Exploded BOM | `BOM Part-Rev`, `Component Part-Rev`, `Op No - Code`, `BOM Quantity` |
| `Part Attributes\` | **database query + manual overrides** (two files, see below) | `Part No` + `Revision`, `Powder Colour` |

*Part Attributes detail:* `Part Attributes SQL.xlsx` is pulled by a **database query** (paint
colour as a part attribute); `Part Attributes - Manual.xlsx` **overrides missing colours** with
manual inputs. Both files are concatenated and, per part, the first **non-null** colour wins —
so the manual file fills gaps in the SQL pull. A powder-coated part with no colour in either
shows as `Not Found`.

**Outputs (engine CLI only)** — `GraphAllocator.exe` writes `Allocations\Allocation_V2.csv`,
`Releases_V2.csv`, `Inventory_V2.csv`, `Rework_MRB_V2.csv` (column names are load-bearing for
downstream tools). The dashboard itself writes **no CSVs**.

**Runtime files (dashboard, all derived/regenerable except the runlists):**
`Snapshots\` (fast-open snapshot pool) · `Snapshots\volvo_churn\<date>.json` (daily Volvo-Trucks
release snapshot for overdue/churn detection — first run of each day, two kept) ·
`Runlists\runlist_live.json` + `runlist_owner.lock` (the published floor list — shared state) ·
`Views\` (shared saved views) · `runlist_draft.json` (per-machine draft) · rotating
`*.log` / `*_fault.log` beside each exe.

## 7. Run, build, develop

| Action | How |
|---|---|
| Run (users) | root `.bat` files: `Launch Paint Allocation Dashboard.bat`, `Launch PC Runlist.bat`, `Launch EC Runlist.bat` (start the exes in `PaintAllocationDashboard\`) |
| Run from source (dev) | `Launch Paint Allocation Dashboard V2.bat`, or `venv\Scripts\python.exe -m paint_dashboard` from inside `PaintAllocationDashboard\` (flags: `--no-browser --no-watch --parity`) |
| Build exes | `build-PaintAllocationDashboard.ps1` (3 dashboard exes), `build-GraphAllocator.ps1`, or `build.ps1` for all — PyInstaller via the project `venv\`, scratch dirs in `%TEMP%` (OneDrive breaks in-tree builds) |
| Environment | Python 3.12.10 in `venv\` · pandas 3.0.2 · python-calamine 0.6.2 · pyinstaller 6.20.0 · floor viewers are stdlib-only |

## 8. Rough edges / IT take-aways

- **Manual data drops:** no direct Plex integration; staleness = whenever the last export was
  pulled (shown as "Data Pulled At" in the header). Part Attributes comes from a database query
  (`Part Attributes SQL.xlsx`) plus a hand-maintained override file for missing colours.
- **No automated tests;** parity vs the trusted CSV is a manual `--parity` run.
- **OneDrive quirks:** file locks can break in-tree PyInstaller builds (hence `%TEMP%`) and
  occasionally delay shared-file writes; all shared writes are atomic (`tmp` + replace).
- **Trusted engine:** never edit `paint_dashboard\engine\` directly — it is a byte-identical
  vendored copy of `Python Script\graph_allocator_V2.py` / `allocation_common.py`; change the
  source and re-vendor.
