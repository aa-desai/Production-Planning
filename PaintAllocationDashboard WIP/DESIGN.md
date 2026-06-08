# Paint Allocation Dashboard — Design

**Status:** Part 1 (read-only allocation dashboard) **built & shipping**. Part 2
(PC/EC floor runlists) **built & verified (P1–P7 + packaging + shared views, 2026-06-05)**.
All V2.0.0 code complete; to ship: run the build (3 exes), flip `__version__` to `2.0.0`, and
do an in-browser click-through smoke. See [PROGRESS.md](PROGRESS.md).
**Current version:** **V1.1.0** (read-only dashboard + self-contained refactor).
**Target:** **V2.0.0** — the full build this doc describes (Part 1 + Part 2 runlists).

This is the single, consolidated design doc for everything under
`PaintAllocationDashboard\`. It folds in the former `Python Script\paint_dashboard_V2_design.md`
(Draft v10) and updates it to current reality, then specifies the new runlist feature.
Build history / resumable log lives in [PROGRESS.md](PROGRESS.md). Engine internals
(inputs/outputs/columns) are documented separately in `Python Script\graph_allocator_V2_README.md`.

---

## 0. Two parts, two trust models

| | Part 1 — Allocation dashboard | Part 2 — Floor runlists (new) |
|---|---|---|
| Audience | Planner | Shop floor |
| ERP raw data | **read-only** | not read (viewers are pipeline-free) |
| Writable state | derived only — shared snapshot pool + shared saved-views bank (never ERP data) | **runlist** (authored by planner, published to a shared file) |
| Writers | derived files only (snapshots, shared views) | **exactly one** planner (lock owner) |

> **Scoped reversal of the v10 "no writable shared state" rule.** v10 deliberately
> removed per-release overrides + the shared `overrides\` folder because multi-writer
> OneDrive edits conflicted. Part 2 reintroduces shared state **without** reintroducing
> that problem: the **planner is the sole writer** (enforced by a lock owner/heartbeat),
> the floor only **reads** a published file, and there is no per-release editing. The
> allocation *view* stays strictly read-only over ERP data.

---

## V. Versioning
**Scheme:** SemVer `MAJOR.MINOR.PATCH`.
- **MAJOR = capability epoch.** `1` = read-only allocation dashboard; `2` = + PC/EC floor
  runlists (the full build this doc describes).
- **MINOR** = user-facing feature additions within an epoch. **PATCH** = fixes / internal.

**Timeline:** `V1.0.0` first read-only build → `V1.1.0` self-contained package refactor
(current) → `V2.0.0` full runlist build (target).

**Single source of truth:** `paint_dashboard.__version__`. Surfaced in the queue payload as
`appVersion`, rendered in the dashboard header, and embedded in the snapshot filename (§7).
A MAJOR/MINOR bump doesn't break the cache — older snapshots simply age out of the
5-most-recent window; the snapshot reader is tolerant of a differing version field.

---

## PART 1 — READ-ONLY ALLOCATION DASHBOARD (built)

### 1. Goal
Replace `Allocation_V2.csv` + Excel with a two-pane dashboard:
- **Release Queue** (left): all paint releases, ship-date ASC, each with a 4-segment
  **coverage bar** and a 4-tier **concern badge**.
- **Selected Release** (right): the release's full routing (final op on top), container
  cards at every op, and collapsible **sub-routings** for painted subcomponents (rendered
  from the internal releases the allocator emits).

### 2. Architecture (current — post-refactor)
The dashboard is a **self-contained Python package** `paint_dashboard\` under
`PaintAllocationDashboard\`; `paint_allocation_dashboard.py` is a thin launcher shim.
It depends on **nothing** outside this folder — the allocation engine is **vendored** in
`paint_dashboard\engine\` (`allocation_common.py`, byte-identical copy of the trusted
module; `graph_allocator_v2.py`, identical except its import is package-relative).

```
paint_allocation_dashboard.py        ← launcher shim → paint_dashboard.app.run()
paint_dashboard/
  config.py        ini + run-dir resolution
  bootstrap.py     resolve project root (raw-data folders) + patch engine paths
  pipeline.py      run_pipeline() → PipelineResult (in-memory, writes no CSV)
  parity.py        optional --parity self-check vs Allocation_V2.csv
  datasource.py    raw-data mtime ("Data Pulled At")
  coverage.py · serialization.py · swatches.py    leaf helpers
  indexes.py       build_indexes() (release lineage, alloc-by-release, etc.)
  payload.py       build_queue_payload() + build_detail_tree() (holds CURRENT_GRAPH)
  snapshot.py      local snapshot cache (the only file written)
  state.py         AppState/STATE (refresh under lock, retain-on-failure)
  watcher.py       ERP auto-update watcher
  server.py        ThreadingHTTPServer read-only endpoints
  ui.py            embedded single-page UI (HTML string)
  app.py           main()/run()
  engine/          VENDORED: allocation_common.py + graph_allocator_v2.py
```

**Per-planner local server.** Each planner runs their own `http.server` on `127.0.0.1`
(no firewall change). The browser polls `GET /snapshot` (~15 s) so a background refresh
(e.g. after an ERP pull) updates the view in place.

**Endpoints:** `GET /` (UI + inlined queue payload), `GET /snapshot` (queue JSON for
polling), `GET /detail?rid=` (on-demand routing tree), `POST /refresh` (re-run pipeline).

### 3. Pipeline flow (what `run_pipeline` does, in order)
1. **Bootstrap** — resolve project root (config override → walk up for the raw-data
   folders) and patch the engine's `path_*` at that root.
2. **Load & clean** — inventory (P6+P10), releases (no P6 elimination), full process
   routing (all parts, with cross-plant `Internal Op No`), exploded BOM, part attributes.
3. **Paint classification** — per-part Ecoat/Powdercoat/Powder Colour; a part is painted
   if it has its own EC/PC op **or** is the sole component consumed by a parent's EC/PC op.
   Rework/MRB containers are sidelined (never allocated; re-attached display-only).
4. **Build graph** — each `(part, op)` is a Node; routing edges link to the upstream op;
   inventory attaches via exact-then-base-name match; BOM component edges link a parent op
   to the final op of each consumed component (carrying the BOM multiplier). Records
   `last_paint_seq` per part; asserts the BOM is a DAG.
5. **Filter & anchor releases** — keep a release (any plant) only if its subtree contains
   an EC/PC op; stamp ship-date FIFO `Release ID`; anchor to the part's final op.
6. **Allocate** — one upstream traversal per anchor: consume containers (smallest first),
   fan out to component edges scaled by BOM multiplier (painted child → visible internal
   release; non-painted intermediate → passthrough), propagate residual upstream. Shared
   container pools mutate, so FIFO order matters. Leftover/orphan painted containers are
   emitted as unallocated rows.
7. **Finalize** — attach release-part paint flags, keep painted rows → `PipelineResult`.

**Output:** `PipelineResult{graph, anchors, alloc_df, internal_df, releases_with_id,
paint_flags, rework_mrb, inventory_raw, process_routing, painted_set}`.

### 3.1 Daily graph build vs. per-refresh allocation (V2 change)
The structural graph changes rarely (it derives from process routing + BOM), but inventory
and releases change with every ERP pull. V2 therefore **splits the pipeline**:

- **Built once per local day (cached), or on demand via a "Rebuild graph" button:** load
  routing + BOM + part attributes; build the *structural* graph (routing nodes + edges, BOM
  component edges, `last_paint_seq`); compute paint flags + `painted_set`. Cache this bundle
  **local, per machine** — it is cheap to rebuild and not worth sharing.
- **Every refresh / rerun:** (re)load inventory + releases, **attach inventory containers**
  to the cached structural graph, filter + anchor releases, **allocate**, finalize. This is
  the only work a routine refresh does.

Rebuild trigger = **first run of the local day**, **plus a manual "Rebuild graph" button**
(`POST /rebuild-graph`) for when routing/BOM changed mid-day. Mid-day routing/BOM changes are
*not* auto-detected (decision R14).

> **Implementation note.** Today `build_graph()` both creates the structural graph *and*
> attaches inventory in one call, and the allocator mutates `container.remaining`. The split
> needs a `build_structural_graph()` (cacheable) + a per-run `attach_inventory(graph, inv)`
> that starts each allocation from a clean container state. This separation lives in the
> dashboard's orchestration (or a documented engine extension); the allocation *logic*
> (consume order, traversal, FIFO) stays unchanged.

### 4. Payload schema
Top-level payload also carries `appVersion`, `generatedAt`, `dataPulledAt`, `releaseCount`,
`customers[]`, `readOnly`.

**`releases[]` (queue rows):** `naturalKey` = `customer__part__shipISO__relBal__dedupeIdx`
(stable across regens), `customer`, `part`, `releasePlant`, `shipDate`, `relBal`,
`coverage{pastPaint, paintable, pipeline, short}` (sums to `relBal`), `concernAuto`
(`good`/`low`/`medium`/`high`), `paintBadge` (`EC`/`PC`/`EC+PC`; PC carries
`{colourName, colourInitials, swatchHex, glyphHex}` resolved **server-side** from
`powder_colour_swatches.csv`), `p10Inventory` (bool), `hasPaintedSubcomponents`.

**Detail tree (`GET /detail?rid=`, built on demand):** `partNo`, `relBal`, `coverage`,
`concernAuto`, `ops[]` each with `op`, `seq`, `isPaintOp`, `netQty`, `collapsed`,
`pastPaintShare`, `containers[]` (`serial`, `location`, `qty`, `allocatedHere`,
`pastPaint`, `addDate`, `containerPlant`, `nextOp`), `reworkCards[]` (display-only),
and recursive `subRoutings[]` (internal releases, same shape + `consumedAtOp`,
`bomScaledNet`).

### 5. Computed logic (settled — must not silently disagree with the engine)
- **Past last paint:** container is past paint iff `node.seq >= graph.last_paint_seq[part]`
  — the allocator's own predicate (`coverage._bucket_rows` reads the `Past Last Paint Op`
  flag the engine stamps).
- **Coverage buckets:** `pastPaint` (past last paint), else `paintable` (Next Op is EC/PC),
  else `pipeline`; `short = max(relBal − sum, 0)`.
- **`concernAuto`** (quantity-only, 4 tiers, first match): `good` `past≥bal` → `low`
  `past+paintable≥bal` → `medium` `past+paintable+pipeline≥bal` → `high`. Time is
  intentionally NOT a factor (ship-date drives the queue sort instead).

### 6. UI (settled decisions still in force)
- Queue: ship-date ASC under **day dividers**; row = concern pip · customer · plant ·
  part(+paint badge) · 4-seg coverage bar · ship date · rel bal · copy-part button.
- Filters: customer multi-select, tri-state EC/PC, colour multiselect (when PC), "Inventory
  at P10", four hide-by-condition chips, part search, ship-date range slider, saveable
  **filter presets** — **personal** (local `localStorage`) **and a shared "common bank"**
  any planner can publish to (§7a).
- Header shows the app **version** (`appVersion`) by the title, plus the "Data Pulled At" chip.
- Detail: **Stack** (vertical, final op top) / **Flow** (horizontal) toggle, default Stack;
  paint ops tagged; collapsed upstream ops show a pie-style past-paint chip; container cards
  `alloc/total` with past-paint border; 7-field click popover; Rework/MRB condensed to one
  aggregated grey card → breakout modal; sub-routings render inline under the consuming op.
- Theme: **Bold Slate** (slate canvas, deep navy header/accent, vivid coverage colours).
- Draggable splitter between panes; animated Refresh button.
- **Removed at v10 (do not reintroduce in Part 1):** per-release overrides, `overrides\`
  folder, `concernManual`, concern-cycling, conflict banners, the "manual" pip.

### 7. Config, snapshot, watcher, distribution
- **Config** `paint_allocation_dashboard.ini` (optional; zero-config otherwise). Keys:
  `[paths] project_root`, `[server] host`/`port` (port 0 = auto), `[refresh] auto_update`.
  Search: `--config` → run dir → one-up → cwd. All paths relative (OneDrive-portable).
- **Snapshot cache (V2: shared pool).** On each successful build, write
  `Dashboard Snapshot - <appVersion> - <ComputerID> - <YYYY-MM-DD_HHMMSS>.json` (time = the
  pipeline-run init time; `ComputerID` = `platform.node()`) to a **shared snapshot folder**,
  atomically (`.tmp`→replace). Then **prune the folder to the 5 most-recent files overall**
  (across all machines — a busy machine may evict another's older snapshot; accepted, R11).
  On startup, read the newest shared snapshot for an instant open, then rebuild live. This
  supersedes the v10 "local, per-machine, never-shared" snapshot. **Ordering (newest / prune)
  uses the embedded filename timestamp, not mtime** — robust to OneDrive rewriting mtimes on
  sync. Location = `<shared dir>/Snapshots/` (`[shared] dir`; defaults to the local run dir).
  *(Built 2026-06-05.)*
- **Watcher** — polls raw-data mtime; on a settled change (debounced) re-runs the pipeline;
  browser picks it up via the `/snapshot` poll. Gated by `[refresh] auto_update` / `--no-watch`.
- **Distribution** — PyInstaller `--onefile` `PaintAllocationDashboard.exe`, built by
  `build-PaintAllocationDashboard.ps1` (scratch dirs outside OneDrive; `--collect-all
  python_calamine`). Launched via `Launch Paint Allocation Dashboard.bat` (`%~dp0`
  self-relative). Frozen exe resolves files beside itself, not PyInstaller's `_MEIPASS`.

### 7a. Saved views — personal + shared bank (V2)
Saved filter views come in two scopes:
- **Personal** — stay in the browser's `localStorage` (as today); private, instant.
- **Shared "common bank"** — published to a **shared views folder**, **one JSON file per
  named view** (`<view name>.json` carrying the captured filter state + `creator`,
  `updatedAt`). Any planner can **add** a view and **pull** anyone's; **only the creator may
  overwrite/delete** their own (conflict-free, mirroring the old per-file overrides pattern).
  The UI lists Personal and Shared views separately, with a "Publish to shared" action.
- Shared views are derived/non-ERP; OneDrive sync latency applies (a new shared view appears
  for others after sync — seconds to a minute).

---

## PART 2 — PC / EC FLOOR RUNLISTS (designed, not built)

### 8. Goal
Two floor-facing **runlist** views, fed by the planner from the dashboard:
- **PC runlist:** grouped `Current colour → Releases assigned to this run → containers`.
- **EC runlist:** a flat ordered list of containers.

Each container shows the pushed fields: **Part No · Serial Number · Location · Allocation
Qty**. Floor views are read-only and auto-drop containers that have been run.

### 9. Topology & trust
- **Planner instance** (the existing dashboard exe): runs the pipeline, authors the runlist
  (a *draft*), and **publishes** to a shared file.
- **Floor instances** (separate viewer exes, one per view): **pipeline-free**; read the
  published file, render, and poll. They never write.
- **Shared file** lives on a OneDrive/network path (configured). The planner is the **sole
  writer**, enforced by a lock owner (§14).
- **Eventual consistency:** floor sees changes after OneDrive syncs the published file
  (seconds–minutes). Accepted trade-off (mirrors the Part-1 OneDrive latency choice).

### 10. Data model
**`RunItem`** — published fields: `partNo, serial, location, allocQty`. Internal fields:
`runItemId` (stable), `target` (`pc`/`ec`), `releaseId`, `customer`, `shipDate`,
`powderColour` (PC grouping), `part`, `queuedPaintSeq` (the EC- or PC-op seq this item is
queued for — drives reconciliation), `source` (`manual` / `auto-ec-deficit`), `pushedAt`.

**Runlist structure** (explicit nested order so drag-and-drop can reorder everything):
- **PC:** ordered `colours[] → releases[] → items[]`.
- **EC:** ordered `items[]`.

**Files:**
- `runlist_draft.json` — planner-local autosave (survives restart). Where edits land.
- `runlist_live.json` — shared, published; what the floor reads. The contract.
- `run_history.json` — local audit of reconciled/removed items (nothing vanishes silently).
- `runlist_owner.lock` — shared lock/heartbeat (§14).

### 11. Selection & push (planner)
- Selection affordances (checkboxes) on **releases** and on **container cards** in the
  detail pane. Selecting a release auto-selects its current allocation (containers with
  `allocatedHere > 0`).
- Two buttons: **Push to PC runlist**, **Push to EC runlist** (separate).
- Push appends `RunItem`s to the **draft** (not live).

**Quantity popup — Required / Entire / Manual.** **Trigger: any engine-partial container**
(a selected container whose `allocatedHere < qty`). The popup offers:
- **Required** — the allocated qty only.
- **Entire** — the full container qty (the surplus cascades per §12).
- **Manual** — planner types a qty (e.g. run 40 of 50 for time reasons); the typed qty is
  what goes to the runlist (and cascades if it exceeds the release's remaining balance).

### 12. Over/under-allocation cascade (always vs. release balance)
- **Under** the release balance: allowed, no action.
- **Over** the release balance: the run qty placed on a release on the runlist is capped at
  its `relBal`; the **excess cascades to the next unfilled release for the same part**, in
  ship-date FIFO order (the same order the allocator uses). If none remains, surface a
  warning — never drop qty.
- *Example:* Release A `relBal=100`, containers 40/45/50 all selected **Entire** →
  A gets 40+45+15 (=100); the remaining 35 of container 3 cascades to Release B (next
  release for that part). "Unfilled" = `relBal − qty already placed on that release`.

### 13. PC → EC deficit auto-fill
Only for branches that have **both** an EC and a PC op (EC then PC). When PC is pushed:
- Required PC feedstock = the PC run qty for the branch.
- Available = allocated containers already **past EC** (between EC and PC).
- If available < required, walk the still-**needs-EC** containers (before the EC op) **in
  allocation order** and add them to the EC runlist (`source = auto-ec-deficit`) until the
  deficit is covered.
- Auto-added EC items are **colour-coded** in the reorder tab, and a notification
  (“N auto-added EC items — review”) prompts the planner. They publish with the normal
  Confirm/auto-publish (the colour-coding is the review gate).

### 14. Lock owner / heartbeat (single-writer guarantee)
- `runlist_owner.lock` holds `{machine, user, pid, acquiredAt, heartbeatAt}`.
- The owner rewrites `heartbeatAt` every **10 minutes**.
- **Takeover is event-driven, not polled:** when a non-owner instance attempts an authoring /
  publish action, it checks the lock. If the owner's `heartbeatAt` is older than one interval
  plus grace (a **missed heartbeat**), the contender runs a short **missed-heartbeat
  confirmation** (re-reads the lock after a brief confirm window to be sure the owner is
  really gone), then **auto-takes ownership** (atomic write) and notifies. A live owner means
  the second instance stays **read-only** (can author a draft, cannot publish) until takeover.
- Only the lock owner may write `runlist_live.json`.

### 15. Reconciliation on planner refresh (auto-remove what was run)
Run inside `AppState.refresh()`, **before** the payload swap; reconciled draft is then
republished (Confirm / auto-publish). Per `RunItem` (keyed by `serial`):
- **Fully run** — container is now **past the queued paint op** (`node.seq ≥ queuedPaintSeq`)
  or its serial is gone at/before that op → remove from the runlist, append to history.
- **Partially run** — container still present but its on-hand qty at the queued op dropped →
  **reduce the item's run qty** to the new remaining; keep it on the list.
- A **release stays on the list until its balance is met** — never drop a whole release just
  because one of its containers ran.

### 16. Reorder tab (planner) + publish
- A new planner tab renders the **draft** runlists (PC nested colour→release→container,
  EC list) with **full drag-and-drop** reordering at every level — the planner has total
  control of run order.
- Auto-added EC items are colour-coded with the review notification (§13).
- **Confirm** publishes the draft → `runlist_live.json` (atomic; requires lock ownership).
- **Auto-publish every 10 minutes** while the reorder tab is open (safety net).
- Each pane (PC, EC) has its own **Clear** button to empty that target's draft (with confirm);
  clears the draft only — the floor view is unaffected until the next publish.
- Published order is what the floor views render.

### 17. Floor views
- **PC view:** `Current colour → Releases → containers` (Part No · Serial · Location · Run
  Qty), in published order.
- **EC view:** flat ordered container list (same four fields).
- Each polls `runlist_live.json` (~10–15 s) and re-renders; completed containers disappear
  because the planner republishes the reconciled list. Read-only.

### 18. Packaging / build
- **Three entry scripts → three exes, one bat each** (independent launch per view):
  - `paint_allocation_dashboard.py` → `PaintAllocationDashboard.exe` (planner; existing).
  - `runlist_pc.py` → `PaintRunlistPC.exe` (PC floor viewer; runs the package in viewer mode,
    no pipeline).
  - `runlist_ec.py` → `PaintRunlistEC.exe` (EC floor viewer; viewer mode).
- The build script **builds all three** (extend `build-PaintAllocationDashboard.ps1` or add a
  combined target). **Viewers are pipeline-free and stdlib-only — no pandas / calamine /
  engine** (R15): the viewer entry scripts import only the runlist reader + floor UI + a
  minimal `http.server`, so PyInstaller bundles none of the heavy deps and the viewer exes
  stay tiny. The package must be structured so the viewer import path never transitively
  imports `pipeline`/`engine`. The planner exe still carries pandas (it runs the pipeline)
  but is kept as lean as practical.
- New config block `[runlists] shared_dir = <relative-or-absolute path>` (read by both the
  planner and the viewers) locates the shared runlist/lock files.

### 19. Endpoints (Part 2)
- **Planner:** `POST /runlist/push {target, items, qtyChoices}`, `POST /runlist/reorder
  {target, order}`, `POST /runlist/clear {target}` (omit/invalid target = both), `POST /runlist/publish`,
  `GET /runlist/draft.json`, `GET /runlist/lock`.
- **Viewer:** `GET /runlist/pc`, `GET /runlist/ec` (pages), `GET /runlist/live.json` (reads
  the shared file).

### 20. Suggested build order
1. Model + store + **viewer mode** reading a hand-made `runlist_live.json` (prove the floor
   pages + shared-file round-trip + OneDrive latency — riskiest infra bet).
2. **Lock owner / heartbeat** (§14).
3. Planner **selection + push** + the **qty popup** (§11) → draft → Confirm/publish.
4. **Overallocation cascade** (§12).
5. **PC→EC deficit** + colour-coding/review (§13).
6. **Reconciliation** on refresh (§15).
7. **Reorder tab** (full DnD) + 10-min auto-publish (§16).

**Also part of the V2.0.0 build (independent of the runlist sequence above):** version in
header + `__version__` (§V); shared snapshot pool with the new naming + 5-most-recent pruning
(§7); personal + shared saved-views bank (§7a); the structural-graph/allocation split + daily
build + Rebuild-graph button (§3.1). These can land in any order; **the graph split is the
highest-value (it cuts every refresh's cost) and lowest-risk — do it first.**

---

## 21. Decisions log

### Part 1 (settled; see also the former v10 §8 table, condensed here)
Ship-date-ASC queue with day dividers · Stack default + Flow toggle · Bold Slate theme ·
**concern is auto-only, quantity-based, 4 tiers** · coverage bar never overridden · server-side
swatch hex · pie past-paint chip · natural-key stable IDs · per-planner local 127.0.0.1 server ·
snapshot cache is the only writable artifact · ERP auto-update watcher on by default ·
Rework/MRB displayed but never allocated · **no overrides / no writable shared state**.
Refactor (2026-06-05): self-contained `paint_dashboard\` package + vendored engine; no
dependency on `..\Python Script\`; `inventory_to_release_allocation` is no longer imported.

### Part 2 (settled this round)
| # | Decision |
|---|---|
| R1 | Floor access = **shared file on OneDrive/network**; planner writes, floor reads. |
| R2 | "Successfully run" = **container advanced past its queued paint op** (qty-level: partial run → reduce qty; full → remove; release persists until met). |
| R3 | Reorder tab = **full drag-and-drop** over colours/releases/containers (PC) and EC list. |
| R4 | PC→EC deficit ECs are **auto-added, colour-coded, with a review notification**. |
| R5 | Reorder tab has a **Confirm (publish-to-live)** button **and auto-publishes every 10 min** while open. |
| R6 | **Lock owner/marker** on the shared path; **auto-takeover after heartbeat timeout**. |
| R7 | Over/under is **always vs. release balance**; under is fine; over cascades to the next release for the part (FIFO). |
| R8 | Qty popup (**Required / Entire / Manual**) appears for **any engine-partial container**. |
| R9 | **One independent bat/exe per view** (planner + PC viewer + EC viewer); build script builds all. |
| R10 | **Version in header**; SemVer epochs (1 = read-only dashboard, 2 = + runlists); single source `paint_dashboard.__version__`; current **V1.1.0**, target **V2.0.0**. |
| R11 | **Snapshots → shared pool**, named `Dashboard Snapshot - <Version> - <ComputerID> - <time>`; keep the **5 most recent total** (a busy machine may evict others — accepted). |
| R12 | **Saved views = personal (local) + shared "common bank"** (one file per view; creator-owned overwrite/delete). |
| R13 | **Split structural-graph build from allocation:** build the graph once per local day (cached); every refresh re-attaches inventory + reallocates. |
| R14 | Graph rebuild = **daily + a manual "Rebuild graph" button**; mid-day routing/BOM changes are not auto-detected. |
| R15 | **Viewer exes are stdlib-only** (no pandas/engine); all exes kept as light as possible. |
| R16 | **Heartbeat = 10 min**; takeover **event-driven** with a **missed-heartbeat confirmation** before seizing the lock. |

## 22. Open items
**Resolved this round:** OneDrive sync latency accepted (documented). Manual-qty distribution
confirmed (run 40 of 50 → 15→A, 25→B, 10 unrun). Heartbeat = 10 min, event-driven takeover
(R16). Viewer exes stdlib-only (R15). Snapshots shared/5-total (R11); views personal+shared
(R12); graph split daily + button (R13/R14).

**Still to pin during build:**
- The **shared paths** (snapshot pool, shared-views folder, runlist `shared_dir`, lock) and
  their config keys + write permissions on every machine. Proposed: one `[shared]` section
  with sub-keys, all relative to the config for OneDrive portability.
- The grace window for the missed-heartbeat confirmation (R16).
- Concurrency on **snapshot pruning** (two machines pruning the shared pool at once) — use
  atomic rename + tolerate races.
