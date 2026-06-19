# Paint Allocation Dashboard — Design

**Status:** Parts 1 + 2 **built, shipping from `PaintAllocationDashboard\`** (promoted from
WIP 2026-06-10). See [PROGRESS.md](PROGRESS.md).
**Current version:** **V2.2.0** — adds overdue release detection (faint red wash in the queue),
the P6 internal-lead-time −1-day shift, and the daily Volvo-Trucks churn-snapshot pool (see §6b),
on top of V2.1.0 (multi-release selection/push, the 5-min reconcile heartbeat + last-EC/PC-op
gate, the reworked editor, toast notifications, publish-when-empty, and the EC-eligibility fix).

This is the single, consolidated design doc for everything under
`PaintAllocationDashboard\`. It folds in the former `Python Script\paint_dashboard_V2_design.md`
(Draft v10) and updates it to current reality, then specifies the new runlist feature.
Build history / resumable log lives in [PROGRESS.md](PROGRESS.md). The project-level
overview / IT handoff (system, modules, UI reference, input data) is the root
[README.md](../README.md), which absorbed the former `graph_allocator_V2_README.md`.

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

**Timeline:** `V1.0.0` first read-only build → `V1.1.0` self-contained package refactor →
`V2.0.x` full runlist build (user testing) → `V2.1.0` selection/reconcile/editor wave →
`V2.2.0` overdue detection + P6 lead-time shift + Volvo churn snapshots (current).

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
`allocatedElsewhere` (bool — consumed by another release; drives greying, R20),
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
- Queue: ship-date ASC under **day dividers** (oldest add date first within each block, §6c); row =
  concern pip · customer · plant · part(+paint badge + **"Oldest Added" date, §6c**) · 4-seg coverage
  bar · ship date · rel bal · copy-part button. Overdue rows carry a faint red wash (§6b).
- Filters: customer multi-select, tri-state EC/PC, **colour multiselect (shown by default —
  hidden only when the PC tri-state is set to *exclude* PC; R18)**, "Inventory at P10", the
  **tri-state "Any" (partial) + "All" (whole-bar) condition filters (§6a)**, part search, ship-date range slider,
  saveable **filter presets** — **personal** (local `localStorage`) **and a shared "common
  bank"** any planner can publish to (§7a).
- Header shows the app **version** (`appVersion`) by the title, plus the "Data Pulled At" chip.
- Detail: **Stack** (vertical, final op top) / **Flow** (horizontal) toggle, default Stack;
  paint ops tagged; collapsed upstream ops show a pie-style past-paint chip; container cards
  `alloc/total` with past-paint border; 7-field click popover; Rework/MRB condensed to one
  aggregated grey card → breakout modal; sub-routings render inline under the consuming op.
  **Containers allocated to a *different* release are greyed out (R20)** — visibly de-emphasised
  (dimmed, "allocated elsewhere" hint) so the planner sees the container exists but it isn't
  free for this release. **Container order within each op (R21): allocated-here containers
  first, then any unallocated containers** (so the relevant cards lead; greyed/elsewhere and
  free containers follow).
- Theme: **Bold Slate** (slate canvas, deep navy header/accent, vivid coverage colours).
- Draggable splitter between panes; animated Refresh button.
- **Removed at v10 (do not reintroduce in Part 1):** per-release overrides, `overrides\`
  folder, `concernManual`, concern-cycling, conflict banners, the "manual" pip.

### 6a. Queue condition filters — tri-state "Any" (partial) + "All" (whole-bar) sections
Two parallel chip rows, both keyed on the release's **coverage buckets** (§5: `pastPaint` /
`paintable` = **WIP** / `pipeline` / `short` = **Short**). Each chip is **tri-state** — single
click = **is** (`.on`); click again = **is not** (`.neg`, shown "not …"); click again = off. State
lives in `condAny` / `condAll` (`bucket -> 1 | -1`). Each section **AND-combines** its own set chips.

- **Any** (partial presence) — *is* = the release has **some** of that bucket (`coverage[k] > 0`);
  *is not* = it has **none** (`coverage[k] === 0`). Example: *Any: WIP, not Short* → some WIP and
  nothing in Short.
- **All** (whole bar) — *is* = the **entire** coverage bar is that bucket (`coverage[k] === total`,
  i.e. 100% of the bar); *is not* = the entire bar is **not** that bucket (`coverage[k] !== total`).
  Example: *All: Short* → only releases that are **entirely** short. (`total` = sum of the four
  buckets, matching the rendered bar.)

An empty section imposes no constraint; the two sections combine with each other **and** with every
other filter by **AND**. (Replaces the former "OR" / Hide-all / Show-any groups; old saved views
that stored those sets simply drop them on load.)

### 6b. Overdue release detection + Volvo churn snapshots (V2.2.0)
Lives **entirely in the dashboard layer** (`paint_dashboard/overdue.py`), post-processing a copy
of `result.releases_with_id`. **The vendored engine is never touched**, and the whole step is
*best-effort*: `state.refresh` wraps `annotate(...)` so any failure degrades to "no overdue
flags" and the snapshot/churn sub-step is independently guarded — it can never break a refresh.

- **P6 lead-time shift.** Releases with `Release Plant == "P6"` get `Ship Date − 1 calendar day`,
  reflecting internal lead time. This is **display / overdue only** — the engine's FIFO allocation
  still uses the original dates (so a P6 release can show a shifted date while its allocation order
  reflects the original; accepted). The queue sort + shown date use the shifted value.
- **`overdue` flag** (per release; **gated to ship date ≤ today — nothing due in the future is ever
  overdue**, then OR of):
  - **4.1 — past-due (global, all customers):** shifted `Ship Date` < today.
  - **4.3 — duplicate collision (global):** ≥2 releases share `(Customer, Part No, Ship To, Ship
    Date)` after the shift → **both/all flagged** (we can't tell which quantity came from which day).
    Only fires for releases due **today or earlier** (a future-dated same-date pair, e.g. a Volvo
    6/24 duplicate, is **not** washed).
  - **4.2 — Volvo churn (computed + logged, NOT yet washing):** `(Part No, Ship To) ∈ volvo_late`.
    Implemented and logged for validation; **not** wired into the flag this rev.
  Surfaced as `overdue: bool` on each queue row → faint red `.qrow.overdue` wash, deepening to a
  darker red when the row is selected (`.sel`) or its release is ticked (`.relsel`) — the selection
  border/box-shadow also turn red for overdue rows so the cue stays consistent. `shipTo` is also
  added to the row.
- **Volvo churn snapshot pool.** Volvo-Trucks `(Part No, Ship To, Ship Date)` keys for ship dates
  in **[today−1 .. today+4]** (4-day forward window so a Thursday pull reaches Monday) are saved
  as `<shared>\Snapshots\volvo_churn\<pull-date>.json` (atomic `tmp`+replace) on the **first run
  of each local day** only; the pool keeps the **2 most recent pull dates**.
- **Churn pipeline** (only when a previous-pull snapshot exists; the previous may be days back —
  Monday's is Thursday's, which the 4-day window covers): `missing_yday` = in `prev[due today−1]`
  but gone from `curr[due today−1]`; `appeared_today` = in `curr[due today]` but absent from
  `prev[due today]`; `volvo_late = missing_yday ∩ appeared_today` on `(Part No, Ship To)` (qty
  ignored). On day one (no previous snapshot) it just writes today's snapshot and skips. The
  backward/weekend handling of "yesterday" is a known limitation, deferred until there are ≥2 days
  of real snapshots to validate against; the `[today−1]` slice is captured now for that work.

### 6c. Queue add-date range + global loading bar (V2.2.0)
- **Oldest inventory add date.** Each queue row shows, next to the colour badge, **"Oldest Added: …"**
  — the *earliest* `Add Date` across the containers **allocated to that release** (`payload.addDateLo`;
  `addDateHi` is still carried but no longer displayed). A release with no allocated containers shows
  nothing. **Queue sort:** ship-date ASC (primary), then **oldest add date first** within each
  ship-date block (no-add-date rows last); customer/part break remaining ties.
- **Global loading bar.** A single fixed top bar (`#loadbar`, GPU `transform` slide, ref-counted
  `loadStart`/`loadStop`) replaces the former per-button spinner/`bdone`/`bfail` swaps and the
  Refresh button's width-morph transition, which felt sticky while a heavy render blocked the main
  thread. `btnRun` now just disables its button + shows the bar; Refresh swaps label/icon (no width
  morph) + shows the bar.

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
- **Logging & crash diagnostics.** Logs go to the console **and** a rotating file `<ProgramName>.log`
  (2 MB × 5) beside the exe — per-program name so the planner + 2 viewers don't share one file. A
  `faulthandler` dump file `<ProgramName>_fault.log` captures **native** crashes (a C-level fault in
  pandas/numpy/calamine) that bypass Python and would otherwise close the window with no trace.
  `sys.excepthook` + `threading.excepthook` persist uncaught main- and worker-thread tracebacks, and the
  HTTP server logs per-request handler errors (`DashboardServer.handle_error`). To investigate a crash,
  reproduce it then read the `.log` (Python errors) and `_fault.log` (native dump).

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
- **Two complementary selection scopes:**
  - **Whole releases** — a checkbox on every **Release Queue** row (`RELSEL`, ordered by tick
    order). Each ticked checkbox shows its **selection-order number**; the row body still loads
    the detail on click. A ticked release means its **full required allocation** (every container
    with `allocatedHere > 0`, at that qty — identical to "Select allocation").
  - **Individual containers** — the existing per-container checkboxes/qty popup in the detail
    pane (`RUNSEL`, current release only). Kept intact for fine-grained control.
- The selection + push controls (**Select allocation**, count, **Push → PC/EC**, draft count,
  **Publish**) live in the **Selected Release** header, directly under the title.
- **Push acts on everything selected at once, in selection order:** each ticked release is pushed
  (in tick order) as its own per-release push, then the viewed release's ticked containers (only if
  that release isn't itself ticked — releases take precedence to avoid double-counting). Pushing
  per release preserves the engine's per-release cascade (§12) + PC→EC deficit (§13). Skipped/added
  totals are summed and surfaced via a toast.
- Two buttons: **Push to PC runlist**, **Push to EC runlist** (separate).
- **Eligibility by paint op (R17).** A push only takes containers that still **need** the op
  in question — i.e. whose current position is **upstream of** the target paint op.
  Paint-op detection is **case-sensitive** (`"EC"`/`"PC"` substring, matching the engine):
  real paint ops are `EC-Load`/`EC-Unload`/`PC-Hang`/`PC-Unload` (uppercase prefix), so
  lookalike ops with a lowercase "ec"/"pc" — `Inspection`, `Receive`, `Inspection & Ship` —
  are **not** treated as paint ops. (Upper-casing first was a bug: it wrongly gated the op right
  before e-coat, blocking those containers from the EC push.) **Push to
  PC** silently drops any selected container that is **in or past a PC op** (it has already
  been — or is currently being — powdercoated); **Push to EC** drops any container **in or
  past an EC op**. Position is judged by the container's node `seq` vs. the branch's EC/PC op
  `seq` (the same `last_paint_seq`/op-seq predicate §5 uses), so an already-painted container
  can never be queued to repaint. Dropped containers are reported back ("N skipped — already
  at/past that op") rather than silently vanishing.
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
- `runlist_owner.lock` holds `{machine, user, pid, instance, acquiredAt, heartbeatAt}`.
- The owner rewrites `heartbeatAt` every **10 minutes**.
- **Ownership is per *planner identity* (machine + user), not per process (R22).** The `instance`
  token distinguishes processes for heartbeat bookkeeping, but the *blocking* decision keys on
  machine+user: **another of your own processes on your own machine (a relaunch, a second window)
  reclaims the lock immediately** — no missed-heartbeat wait. Only a *different* machine/user can
  block you. This removes the "can't publish — owned by yourself" deadlock that the per-process
  UUID caused when a planner reopened the dashboard while an old window was still heartbeating.
- **Takeover is event-driven, not polled:** when a non-owner instance attempts an authoring /
  publish action, it checks the lock. If the owner's `heartbeatAt` is older than one interval
  plus grace (a **missed heartbeat**), the contender runs a short **missed-heartbeat
  confirmation** (re-reads the lock after a brief confirm window to be sure the owner is
  really gone), then **auto-takes ownership** (atomic write) and notifies. A live owner means
  the second instance stays **read-only** (can author a draft, cannot publish) until takeover.
- Only the lock owner may write `runlist_live.json`.

### 15. Reconciliation on refresh + 5-min heartbeat (auto-remove what was run)
Runs inside `AppState.refresh()` (`_reconcile_runlist`), **after** the payload swap; if we
hold the lock the reconciled draft is republished to `runlist_live.json`. It runs on **every**
data read: the manual **Refresh** button, the ERP auto-update watcher, **and** a dedicated
**5-minute reconcile heartbeat** (`watcher.start_reconcile_heartbeat`, started in `app.main`)
that re-reads inventory/releases and reconciles even with nobody clicking Refresh and no new
ERP pull. Per `RunItem` (keyed by `serial`):
- **Run (removed)** — the container has reached **the last paint op of this list's target on
  its own routing**: for an **EC** item, `node.seq ≥ last EC-op seq`; for a **PC** item,
  `node.seq ≥ last PC-op seq` (per-part maps from `reconcile.build_last_paint_seqs`, mirroring
  the app-wide "past last paint" `≥` test). Also removed if the serial is gone from inventory
  or its on-hand qty is 0. Removed serials are reported (`report[t]["removedSerials"]`).
- **Partially run** — container still present but its on-hand qty dropped below the run qty →
  **reduce the item's run qty** to what's left; keep it on the list.
- A **release stays on the list until its balance is met** — never drop a whole release just
  because one of its containers ran.
- **Reflected everywhere with a leave animation:** the floor PC/EC pages and the planner's open
  reorder editor fade/slide removed rows out before re-rendering (§16/§17); the planner runbar
  draft counts poll so removals show even with the editor closed.

### 16. Reorder editor (planner) + publish
- The editor renders the **draft** runlists with **drag-and-drop** reordering. The flat item
  order per target is the source of truth (persisted via `/runlist/reorder`); **group headers
  are derived from that order on every render** — **PC groups by colour → part, EC groups by
  part**.
- **Grouped drag (free placement):** dragging a container moves it anywhere; on drop the order
  is re-read and **headers are recomputed by consecutive run** (a container dropped among a
  different group gets its own header there — no header/colour mismatch). Dragging a **group
  header moves its whole chunk** (a colour header carries its part sub-chunks; a part header
  carries its containers).
- **Make-space animation:** during a drag the other rows FLIP-animate to open/close the gap
  (`flip()` records rects, moves, then transitions transform→0).
- **Reset to live:** each pane (PC, EC) has a **Reset** button that reverts that target's draft
  to the live published list (`/runlist/reset` → `push.reset_to_live`), discarding unpublished
  edits. Each pane also keeps its **Clear** button (empty the draft; floor unaffected until publish).
- **Item rows show Serial · Location · Qty only** — the part number is shown once, in the group
  header (PC part sub-header / EC part header), not repeated on every container row.
- **Collapsible groups:** click any group header (colour or part) to collapse/expand its chunk
  (a large caret pip with a 26 px hit target + hover halo rotates; the caret and drag-handle
  glyphs are forced to legible colours on the dark navy colour header). Collapsed rows stay in the
  DOM as `ehide` (display:none) so a header drag
  still carries them and order is never lost; state lives in `COLL` (per-list key sets) and
  survives re-renders. A post-drag click is suppressed so dragging never also toggles.
- **Acknowledging auto-added EC:** each auto-added EC container (amber) carries a **checkmark**;
  clicking it `POST /runlist/ack {runItemId, acknowledged:true}` sets the item's `acknowledged` flag
  on the draft, clearing the amber and decrementing the “⚠ N auto-added EC — review” banner. Once
  acknowledged the checkmark is **removed entirely** — no residual indicator (the row becomes a
  plain container). Only unacknowledged auto-added items show the checkmark.
- **Confirm** publishes the draft → `runlist_live.json` (atomic; requires lock ownership —
  **except** the very first publish: when no `runlist_live.json` exists yet there is no floor
  view to protect, so `push.publish` `lock.seize()`s outright rather than letting a stale/foreign
  lock block getting started). **Auto-publish every 10 minutes** while open (safety net). While
  open the editor also polls the draft (20 s) so §15 reconcile removals animate out in place.
- Published order is what the floor views render.

### 17. Floor views
- **PC view:** `Current colour → Releases → containers` (Part No · Serial · Location · Run
  Qty), in published order.
- **EC view:** flat ordered container list (same four fields).
- Each polls `runlist_live.json` (~10–15 s) and re-renders; completed containers disappear
  because the planner (or the 5-min heartbeat, §15) republishes the reconciled list. Rows that
  vanished since the last render **fade/slide out** (`animateThenRender` diffs `data-serial`
  before swapping the table). Read-only.

### 18a. Toast notifications
- Transient overlay messages (`#toasts` top-right, `toast(msg,type)`; types `ok`/`warn`/`err`) that
  **auto-dismiss** (~4.5 s) with no click. Used for the **skipped-on-push** notice (containers already
  at/past the target paint op) — previously a blocking `alert()`. Hard-failure paths (push/publish
  errors) still use `alert()` so they can't be missed.

### 18b. Universal button UX
- **Click feedback (all buttons/chips):** a quick press dip (`transform`/inset shadow) on
  `.btn`, `.chip`, `.hchip`, `.copybtn`, the Stack/Flow toggle, and editor rows.
- **Loading buttons:** every async-action button (Rebuild graph, Push→PC/EC, Publish, editor
  Save/Confirm/Clear/Reset) routes through `btnRun()` — a spinner + verb label while the
  promise runs, then a brief green ✓ "done" / red ✕ "fail" state before reverting — matching
  the Refresh button's feel.

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

### Refinements (2026-06-08; design only — not yet built)
| # | Decision |
|---|---|
| R17 | **Push eligibility by op (§11):** never push a container that is **in or past** the target paint op — PC push drops containers in/past any PC op, EC push drops containers in/past any EC op (judged by node `seq` vs. the EC/PC op `seq`). Skipped count is reported. |
| R18 | **Colour filter shown by default (§6);** hidden only when the PC tri-state is set to **exclude** PC. |
| R19 | **Queue condition filters → two groups (§6a):** **Hide all `<cond>`** (hide releases whose *entire* balance is in that coverage bucket) and **Show any `<cond>`** (show releases where that bucket is `> 0`); conditions = Past Paint / WIP (paintable) / Pipeline / Short. |
| R20 | **Selected-release detail greys out containers allocated to other releases** (`allocatedElsewhere` flag, §4). |
| R21 | **Container order within each op:** allocated-here first, then unallocated. |
| R22 | **Runlist lock is per planner identity (machine+user), not per process (§14):** your own other processes reclaim it immediately; only a different machine/user blocks. Fixes the "owned by yourself" publish deadlock. |

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
