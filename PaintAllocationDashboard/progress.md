# Paint Allocation Dashboard — Build Progress

**Purpose of this file:** resumable build log. If the session ends, read this top-to-bottom
to pick up exactly where we left off. Design spec lives in
`..\Python Script\paint_dashboard_V2_design.md` (Draft v10 — READ-ONLY pivot). UI target mockup:
`..\Python Script\paint_dashboard_ui_refined.html` (Classic queue + Stack/Flow detail, heather-gray theme).

---

## ⚑ v10 READ-ONLY PIVOT (current directive)
The planner **cannot modify anything** from the dashboard. It is a pure *view*.
This removed, project-wide:
- per-release status overrides, the `overrides\` folder (deleted), `concernManual`, concern-cycling
- `PUT /overrides`, OneDrive conflict detection, Keep-mine/Keep-theirs, the "manual" pip
- **Concern is auto-only** (design §5.2). Only writable artifact = **local snapshot cache**
  (`paint_allocation_dashboard_snapshot.json`, per-machine, derived, never shared/edited).
- Concurrency is now a non-problem: each planner runs an independent read-only view.

Design doc updated: header v10 block + §8 rows 24/1/23/11 marked superseded conceptually
(see the v10 callout). Build reflects this fully.

## Ground rules (do not violate)
- **Never edit** `..\Python Script\inventory_to_release_allocation.py` (trusted, read-only).
- **Never edit** `..\Python Script\graph_allocator_V2.py` (trusted; imported as-is). *graph_allocator_v2 logic is sound — used as the allocation engine.*
- Raw ERP data folders are read-only.
- All new code lives under `PaintAllocationDashboard\`. Dashboard imports trusted modules
  and re-runs their pipeline **in memory** (no CSV dependency).
- Paths relative / config-driven for OneDrive portability.

## Environment (verified)
- Python `3.12.10` at `..\venv\Scripts\python.exe`. pandas 3.0.2, calamine 0.6.2, pyinstaller 6.20.0.
- Run dev: `..\venv\Scripts\python.exe paint_allocation_dashboard.py [--no-browser] [--parity]`
  (cwd = `PaintAllocationDashboard\`). Picks a free 127.0.0.1 port, opens browser.

---

## Build order & status
- [x] **1. Skeleton** — in-memory `run_pipeline()` mirrors `ga.main()`; returns `PipelineResult`.
      **PARITY OK** vs `..\Allocations\Allocation_V2.csv` (5574=5574 rows, per-(serial,release)
      allocated qty matches exactly). Parity check key-normalisation fixed (CSV loads Release ID
      as float → coerce via Int64 before compare).
- [x] **2. Payload builder** — `build_queue_payload()` → `releases[]` with
      `coverage{pastPaint,paintable,pipeline,short}` + `concernAuto` (4-tier, §5.2) + `paintBadge`
      (server-side swatch hex, initials-in-swatch) + `hasPaintedSubcomponents`. naturalKey =
      `customer__part__shipISO__relBal__dedupeIdx`. Verified: 1582 releases, 19 customers.
- [x] **3. Snapshot cache** — `write_snapshot`/`read_snapshot` (atomic .tmp→replace). Instant open
      from cache, then live rebuild.
- [x] **4. Local server + HTML shell** — `ThreadingHTTPServer` on 127.0.0.1, `GET /` (embeds queue
      payload into `HTML_PAGE`), `GET /snapshot`, `GET /detail?rid=`, `POST /refresh`. Full UI
      embedded (queue: coverage bar + concern badge + paint badge + day dividers + customer
      multiselect + hide-good + search). Verified root=621KB, endpoints return correct JSON.
- [x] **5. Refresh endpoint** — `POST /refresh` re-runs pipeline, retain-on-failure (retry once on
      PermissionError/OSError, 503 on hard fail), atomic state swap under lock, rewrites snapshot.
- [~] **6. ~~Override persistence~~** — **REMOVED (read-only pivot).** No-op. `overrides\` deleted.
- [x] **7. Detail pane v1** — `build_detail_tree()`: routing final-op-first, collapse default
      (`seq < firstPaintSeq-1`), container cards (serial/loc/`alloc/total`, past-paint border,
      qty-asc from graph), 7-field popover, aggregated `MRB Qty` card → breakout modal.
      Stack + Flow views both render. Verified rid=15 cross-part renders.
- [x] **8. Sub-routings** — recursive `build_detail_tree` for internal releases (Parent Release ID
      match, grouped by Consumed At Op). Shows child partNo + bomScaledNet + coverage bar + concern.
      Verified: AXE109785-Rev-A → child HXE209761-Rev-A (5 ops) renders inline under Assembly op.
- [x] **9. Polish** — DONE:
      - [x] `paint_allocation_dashboard.ini` created + wired (`load_config()`, search order §6a.4:
            `--config` → exe/script dir → one-up → cwd). Overrides project_root + server host/port.
            **port=0 (auto) is the distribution default.**
      - [x] `powder_colour_swatches.csv` seeded with **26 real powder-colour names** from the data
            (grey `#9aa0a8` placeholders to curate). `load_swatch_map()` reads it server-side.
      - [x] `..\Launch Paint Allocation Dashboard.bat` (`%~dp0` self-relative → exe).
      - [x] `build.ps1` target added (`--onefile --name PaintAllocationDashboard --paths "Python Script"`
            + hidden-imports calamine/openpyxl + collect-submodules of the two trusted modules).
      - [x] Fixed module-docstring SyntaxWarning (made docstring raw).
      - [x] Verified cross-part coverage rollup (14 cross-part releases credit painted child qty;
            e.g. 24772385 pastPaint=81 rolled up). `alloc_by_top` includes internal-child rows.
      - [x] Added auto-select-first-release so detail pane is never empty on load.
      - [x] `.claude/launch.json` for the in-app preview (fixed port 8765 when previewing).

## ✅ FROZEN .EXE BUILT & VERIFIED (2026-06-01 session 2)
- **Two build gotchas hit & fixed (both in `build.ps1`):**
  1. **calamine not bundled.** pandas reads .xlsx via `engine="calamine"` → lazily imports the
     COMPILED `python_calamine` extension. `--hidden-import` alone misses the `.pyd`. Fix:
     `--collect-all python_calamine` + `--hidden-import pandas.io.excel._calamine`. Symptom was
     "Missing optional dependency 'python-calamine'" → "All files in Inventory P6 failed".
  2. **OneDrive locks the build\ scratch dir** → `--clean` rmtree fails "Access is denied" on
     `build\...\localpycs`. Fix: build to `$env:TEMP\pai_work` / `pai_dist` (NOT OneDrive), copy
     only the .exe back. Also Stop-Process any running exe before the copy (file lock).
- **Frozen exe smoke test PASSED:** 0 calamine warnings, inventory=20497 (P6 loads), paint filter
  3137→1564, "Serving dashboard at http://127.0.0.1:PORT/". Path bootstrap resolved project root
  correctly from the exe inside `PaintAllocationDashboard\`.
- exe is at `PaintAllocationDashboard\PaintAllocationDashboard.exe` (41 MB). Launch via
  `..\Launch Paint Allocation Dashboard.bat`.

## ✅ BUILD COMPLETE — verified
- **PARITY OK** on current data: trusted `ga.main()` and the in-memory pipeline BOTH produce 5468
  painted rows; per-(serial,release) allocated qty matches exactly.
- Live UI screenshotted: heather-gray theme, ship-date queue w/ day dividers, pie concern badges,
  paint badges w/ colour-initial swatches, 4-seg coverage bars, Stack detail w/ PAINT tags +
  past-paint pie chips + real container cards, Stack/Flow toggle, filters, read-only banner.
- **Remaining (optional, user-facing):** (a) build the `.exe` via `build.ps1` and smoke-test the
  frozen path resolution; (b) planner curates real hex values into `powder_colour_swatches.csv`;
  (c) decide on a `Production\` launcher (§6a.3, deferred).

---

## Key implementation facts (for resuming)
- **File:** `paint_allocation_dashboard.py` (~single file, ~700 lines). Sections in order:
  path bootstrap → trusted imports → `PipelineResult` + `run_pipeline()` → `parity_check()` →
  payload/detail builders → snapshot → `AppState`/`STATE` → `Handler` → `HTML_PAGE` → `main()`.
- **CURRENT_GRAPH** global is set on each refresh so `ga_is_past_last_paint()` can read
  `last_paint_seq` without threading the graph through every card call.
- **Indexes** (built once per refresh by `build_indexes`): `internal_to_top` (walk Parent Release ID
  to top external id), `alloc_by_top` (top id → rows, **includes** internal-child rows so cross-part
  coverage rolls up), `alloc_by_relid` (exact id → rows, used for per-op card allocatedHere),
  `rework_by_partop`, `swatch_map`, `ext_by_id`.
- **Coverage buckets** (`_bucket_rows`): pastPaint = `Past Last Paint Op`; else paintable if
  `Next Operation` contains EC/PC; else pipeline. short = relBal − sum.
- **concernAuto** (`concern_from_coverage`): good (past≥bal) → low (past+paintable≥bal) →
  medium (+pipeline≥bal) → high. Matches §5.2.
- **Detail** built on demand (`GET /detail?rid=`), NOT embedded in snapshot (keeps it small;
  read-only local server makes per-click compute fine).
- **KNOWN v1 APPROXIMATION:** cross-part coverage rolls child rows into parent at face value
  (BOM multiplier assumed ~1 for the *coverage bar bucketing*). Detail pane shows true scaled
  `bomScaledNet`. Refine later if non-unit multipliers matter for the bar. Documented here so it
  isn't mistaken for a bug.

## How to run / test
```
cd PaintAllocationDashboard
../venv/Scripts/python.exe paint_allocation_dashboard.py --no-browser   # serves on a free port
# port is logged: "Serving dashboard at http://127.0.0.1:PORT/"
# curl http://127.0.0.1:PORT/snapshot   (queue JSON)
# curl "http://127.0.0.1:PORT/detail?rid=15"   (detail tree)
../venv/Scripts/python.exe paint_allocation_dashboard.py --parity --no-browser  # also runs parity
```

## Session log (newest first)
### 2026-06-03 — session 3 header alignment + filter presets (views)
- (1) Header mismatch fixed: both title bars get class `headbar` with `.pane-head.headbar{min-height:48px}`
  so "Release Queue" and "Selected Release" line up (the right one carries the taller Stack/Flow seg).
  `.pane-head h3` bumped 12→13px + `line-height:1`. Verified: both bars 48px, titles same Y, same 13px/700 font.
- (2) Filter area split into "Views" (left) | vertical `.fdivider` | "Quick filters" (right) via a
  `.filterbar` flex row. Quick-filter chips/search/count moved into `.quickfilters` (right, flex:1, wraps).
  `.presets{flex:0 0 auto;max-width:46%}` keeps the views strip a tidy row (collapsed to a vertical stack
  with the initial flex:0 1 — fixed to 0 0).
- Filter presets ("views"): `+ Save view` prompts a name and stores `captureFilters()` (cust/ec/pc/colour/
  invP10/hide/search + date range as ISO) in `localStorage['paintPresets']`. Saved views render as chips
  (click = `applyFilters()` restores ALL filters + chip visuals + date slider + count; `×` deletes).
  `Clear` resets all quick filters (full date range). Local-only view state — does NOT modify data
  (consistent with read-only). `loadPresets()/renderPresets()` on init.
- Verified live (preview): headers aligned; division order presets→divider→quick correct with labels;
  save→chip+persist; Clear→1415/1415; Apply→restores EC+hide(good/high)→348/1415 with chips re-lit;
  persists across reload; `×` deletes + updates localStorage; "no saved views" placeholder when empty.
  No console errors. Filter bar is taller (~143px at a 610px pane) because quick filters wrap in the
  narrower right column — mitigated by the now-draggable pane. .ini 8765→0. Client-only; rebuild exe to ship.

### 2026-06-03 — session 3 resizable pane + animated Stack/Flow toggle
- (1) Draggable splitter: `.twopane` cols now `var(--leftw,46%) 10px minmax(0,1fr)` (gap:0). New
  `.gutter` element (id #gutter, col-resize, 4px centered handle → accent on hover/drag) between the
  panes. JS IIFE: pointerdown/move/up with `setPointerCapture`; `clamp()` keeps left in
  [MIN_LEFT=440, container-24-GUT(10)-MIN_RIGHT(340)]; sets `--leftw` px; saves to
  `localStorage['paintLeftW']` on release; `resize` listener re-clamps; `body.resizing` for cursor/
  no-select. Default = 46% when no saved value.
- (2) Stack/Flow toggle = animated segmented control. Added `<span class="thumb">` inside `#viewtoggle`;
  buttons fixed 74px, transparent, color-transition; `.seg .thumb` slides via
  `transform .2s cubic-bezier(.4,0,.2,1)`, `.seg.flow .thumb{translateX(100%)}`. Handler toggles
  `#viewtoggle.flow`, swaps panes, and replays a 200ms `@keyframes vfade` (`.vfade`, reflow-retrigger)
  on the shown pane for a quick fade-in.
- Verified live (preview): drag tracked 571→721 on +150; clamped max 891 (=container-gutter-340) &
  min 440; persisted "440"; classes cleared. Toggle: thumb target `translateX(74px)`↔`0` at 0.2s
  (verified with transition disabled — live frames frozen by the same offscreen-compositor artifact as
  the refresh anim), panes swap (flow flex/stack none), vfade applied, toggling back clears `.flow`.
  No console errors. .ini 8765→0. Client-only; rebuild exe to ship.

### 2026-06-03 — session 3 FIX: row highlight/overflow at narrow widths
- Bug: at small window widths the qrow's fixed-width grid overflowed (old hard-min ≈476px:
  `18 86 34 minmax(96,1fr) 68 66 46` + gaps + padding). Left pane floors at 500px, and once the
  vertical scrollbar (~15px) appears the content area drops below 476 → row content overflows right;
  the `.qrow.sel` highlight only paints to the row's box, so the ship date + balance spilled OUTSIDE
  the blue highlight and the part # got crushed.
- Fix: shrinkable tracks so the row always fits the pane —
  `18px minmax(0,84px) 30px minmax(56px,1fr) minmax(38px,64px) 60px minmax(40px,auto)`, plus
  `min-width:0;overflow:hidden` on `.qrow` (overflow:hidden also guarantees nothing ever paints
  outside the highlighted box). New hard-min ≈314px. bal uses minmax(40px,auto) so big qty numbers
  don't clip; date 60px fits MM-DD-YY nowrap.
- Verified live across widths (preview): viewport 720/430 → pane held at 500px WITH scrollbar present,
  `row.scrollWidth==clientWidth` (no overflow), balance inside the row box, highlight covers full row;
  desktop → columns at caps (cust 84 / cov 64 / date 60 / bal 40), part # takes remaining space.
  No console errors. .ini port toggled 8765 then reverted to 0. Client-only; rebuild exe to ship.

### 2026-06-03 — session 3 UI feedback round 2 (copy left, dates, refresh anim)
- (1) Copy button moved to LEFT of the part number (first child of `.pnwrap`).
- (2) Copy icon → universal Material "content_copy" glyph (two overlapping pages), `COPY_ICON` SVG.
- (3) Ship dates now MM-DD-YY on one line: JS `fmtDate('YYYY-MM-DD'→'MM-DD-YY')` used in qrow + day
  divider; `.qrow .date` got `white-space:nowrap`, column widened (date col 46→66px, grid retuned).
- (4) Text darker + larger + non-uniform hierarchy: `--ink`→#0b141f, `--muted`→#33404f, `--faint`→#4a576b;
  pn 14→15px, bal 14→15px(800), cust 13→13.5px, plant/date →13px (pn/bal largest, then cust, then plant/date).
- (5) Refresh button reworked: now `<button class="btn refresh"><span class="ricon"><span class="rlabel">`.
  Bold(800) poppy WHITE pill on the navy header. Click → `refreshTransition()` animates button WIDTH
  from current to the new content's natural width (measured with transitions off, animated via rAF) while
  `.ricon` slides in from the left (width 0→16, `.ricon.show`); label "Refreshing" + CSS `.spin` ring.
  On success → spinner swaps to check-in-circle (`CHK_CIRCLE` SVG), bg→green (`.done`), label "Refreshed";
  after 1.2s slides icon away + shrinks back to idle "Refresh". Error → red `.fail` + "Failed" → idle.
  `refreshing` guard blocks re-entrancy. **`flex:0 0 auto` on `.btn.refresh`** is required — its
  `overflow:hidden` (for the width clip) otherwise lets the header flexbox squeeze it below content width.
- Verified live (preview :8765): copy btn first in pnwrap; date "04-07-26" nowrap; muted #33404f, pn/bal 15px;
  refresh idle 89px bold white → busy "Refreshing"+spinner, icon shown, width 89→136 → done green +
  check-circle "Refreshed" (bg rgb(31,157,77)) → idle 89px (not clipped). No console errors.
  .ini port toggled 8765 for preview, reverted to 0. Client-only; rebuild exe to ship.

### 2026-06-03 — session 3 readability + copy button (UI feedback)
- (1) Larger/darker text: body 13px→14px; `--ink` #16202e→#101924; `--muted` #5a6678→#3c4757;
  `--faint` #8a93a3→#5a6678; qrow cust 12→13px, plant 11→12.5px, date 12→12.5px, pn/bal →14px.
- (2) Releases pane wider: `.twopane` cols `minmax(430px,1fr) 1.55fr` → `minmax(500px,1fr) 1.22fr`
  (left pane now ~45% of the split, was ~39%). qrow grid widened (customer 76→86, part min 70→80).
- (3) Copy button per release row: small icon `.copybtn` inside `.pnwrap` after the part #. Copies
  `r.part` via `navigator.clipboard.writeText` (localhost = secure context) with a `document.execCommand`
  fallback; shows a green check for ~0.9s; `stopPropagation` so it doesn't select the row.
  Helpers `COPY_ICON`/`CHECK_ICON`/`copyPart`/`fallbackCopy`.
- Verified live (preview :8765): 879 rows each with a copy button, body 14px, --muted #3c4757,
  cust 13px, pn 14px, left pane 45% (560px). Copy click → green check, row NOT selected. No console
  errors. (preview_screenshot was hanging on the renderer; confirmed via computed-style eval instead.)
- .ini port toggled 8765 for preview, reverted to 0. Client-only change; rebuild exe to ship.

### 2026-06-03 — session 3 docs: verify comments + separate reference file
- Verified `graph_allocator_V2.py` comments/docstrings against the code — accurate throughout;
  the only stale spot was the module docstring's Outputs list (missing Rework_MRB_V2.csv + the new
  Filter: columns). Rewrote that block (now documents Inputs, all 4 outputs, the Filter: columns,
  and points to the new README). No logic touched; `ast.parse` OK.
- Created `Python Script\graph_allocator_V2_README.md` — standalone reference: purpose, how to run,
  Inputs (the 6 raw folders via `path_*`, .xlsx via calamine, key columns), Outputs (full column
  lists incl. the 7 Filter: columns + the Condition mapping), Dependencies (Python 3.12.10,
  pandas 3.0.2, python-calamine 0.6.2, numpy 2.4.4, pyinstaller 6.20.0, stdlib, the trusted local
  module), consumers (standalone CSV run vs dashboard in-memory), and invariants. Versions captured
  live from the venv.

### 2026-06-03 — session 3 FIX: internal-release rows leaked synthetic customer
- Verifying internal releases / sub-routings in the new `Filter:` columns surfaced a bug:
  internal-release (sub-component) allocation rows stored `Filter: Customer` =
  `"Internal-<customer>-Release ID:N"` (the synthetic anchor customer from `emit_allocation`),
  so filtering Allocation_V2.csv by customer would miss every sub-component row.
- Fix (`attach_filter_columns`): `Filter: Customer` now rolls up to the top-level external release
  (`customer_by_id[top]`) just like Condition/Inventory-at-P10 — real customer on every row.
- Confirmed the rest were already right: EC/PC/Colour describe the top-level release part
  (Release Part Number carries `root_part`); Ship Date/Condition/P10 roll up to the parent.
  `Releases_V2.csv` sub-routing lineage (Parent Release ID / Consumed At Op / Parent Part) untouched.
- Re-verified vs dashboard: **0 condition / 0 P10 / 0 customer mismatches**; **PARITY OK** (5596=5596);
  0 `Internal-` leaks; every allocated row has a resolved `Filter: Customer`.

### 2026-06-03 — session 3 propagate filters into graph_allocator_V2.py CSV
- **NOTE:** user explicitly authorised editing `graph_allocator_V2.py` for this task (overrides the
  usual "never edit trusted module" rule, just for adding output columns — allocation logic untouched).
- Propagated the dashboard's per-release derived attributes into the engine and emit them as
  `Filter: xyz` columns on **Allocation_V2.csv** (decision: per-row/denormalised; decision: a column
  for *every* HTML filter, even where an equivalent column already exists).
- New (in graph_allocator_V2): `CONDITION_LABEL`, `P10_PLANT`/`P10_LOCATION`, `_container_at_p10`,
  `_bucket_rows`, `concern_from_coverage`, and `attach_filter_columns(alloc_df, graph, releases_df,
  internal_df)` — mirrors the dashboard's `_bucket_rows`/`concern_from_coverage`/internal-to-top
  roll-up/`reachable_parts ∩ parts_with_p10_inv` exactly. Called in `main()` after the allocation
  check, before `write_v2_outputs`.
- Columns added (names chosen to match the HTML filters): `Filter: Customer`, `Filter: EC`,
  `Filter: PC`, `Filter: Colour`, `Filter: Inventory at P10`, `Filter: Condition`
  (Past Paint / WIP only / Pipeline only / Empty Pipeline), `Filter: Ship Date`. Existing column
  names unchanged; allocation rows/qty unchanged (5596 rows).
- Condition/Inventory-at-P10 are per-release (computed per external release, rolled up from internal
  rows) then denormalised onto each allocation row; EC/PC/Colour/Customer/Ship-Date mirror the
  per-row fields. Unallocated rows (no Release ID) get blank Condition/Inventory-at-P10.
- **Verified end-to-end via venv:** ran `ga.main()` → CSV has all 7 Filter columns (27 cols total).
  Cross-checked engine vs dashboard per-release: **0 condition mismatches, 0 P10 mismatches** across
  1146 releases (rolled to top). 262 dashboard releases have no CSV row at all — all "Empty Pipeline"
  (zero allocations); expected for the per-row Allocation_V2.csv granularity (they never had rows).
  Dashboard **PARITY OK** (5596=5596) — adding columns didn't disturb allocation.
- Dashboard unaffected: it has its own `run_pipeline` (doesn't call `ga.main`) and its own copies of
  the helpers; no signature changes to imported functions.

### 2026-06-03 — session 3 "Inventory at P10" filter
- New toggle chip **"Inventory at P10"** (queue header, off by default). When on, it hides any
  release whose `releasePlant === 'P6'` AND whose entire routing has no inventory at P10.
- Replaces the old trusted `elim_p6_releases` per-part rule with a **graph-wide** test, so a P6
  release stays visible if *any* component anywhere in its subtree sits at P10 (recovers the
  pipeline visibility the old blanket filter destroyed).
- Server-side (`build_queue_payload`): new per-release bool `p10Inventory`. Computed once via
  `parts_with_p10_inv = {n.part for n in graph.nodes.values() if any(_container_at_p10(c) ...)}`
  then a cached `reach & parts_with_p10_inv` per release part (`ga.reachable_parts`).
  `_container_at_p10(c)` = `container_plant=='P10'` OR `location=='Modineer - P10'`
  (P10-owned stock OR P6 stock transferred to the P10 location — matches the trusted module's literal).
- Client: `invP10` state; filter `if(invP10 && r.releasePlant==='P6' && !r.p10Inventory)return;`;
  chip toggles `.on`. No trusted-module edits.
- Verified against live data via venv: 1408 releases (P6=514, P10=894). Filter on → hides 151 P6
  releases (no P10 inventory in routing); keeps 363 P6 (have P10 inventory) + all 894 P10.
  `p10Inventory` present on every row. Read-only/reversible (toggle), so nothing is ever lost.
  Rebuild + redistribute exe to ship.

### 2026-06-03 — session 3 hide-by-condition filters
- Replaced the single "hide good" checkbox with **four toggle chips** (good/low/med/short →
  green/yellow/orange/red), so the planner can hide any combination of release conditions.
- New JS state `hideConcern = new Set()`; filter is `if(hideConcern.has(r.concernAuto))return;`.
  Chips wired via `.hchip` click → toggle membership + `.on` class; off by default (nothing hidden).
- New CSS `.hidegrp`/`.hchip`/`.hchip.on` (coloured dot + label; struck-through+dimmed when hiding).
  Colours pull from existing `--t-good/--t-low/--t-med/--t-high` (matches the concern pips & legend).
- No Python/payload changes — purely client-side over the existing `concernAuto` field. Syntax-checked OK.
  No rebuild needed for behaviour, but distribute a fresh exe so coworkers get the new UI.

### 2026-06-01 — session 2 (cont.) explicitly bundle calamine
- Coworker hit "missing dependency calamine" (pandas' built-in hook didn't reliably bundle the
  calamine engine). Re-added to the dashboard build target: `--collect-all python_calamine`
  + `--hidden-import pandas.io.excel._calamine`. Verified via `collect_all('python_calamine')`:
  hiddenimports include `python_calamine._python_calamine` (the compiled .pyd) and datas include the
  dist-info metadata (pandas checks the installed distribution). Building via venv (3.12) → bundled
  cp312 .pyd matches the bundled interpreter. Rebuild to apply.
  (InventoryAllocator/Crosscheck left as-is; add the same two flags if either ever shows the error.)


### 2026-06-01 — session 2 (cont.) build.ps1 pinned to venv
- All three targets now invoke `& $py -m PyInstaller` where `$py = $PSScriptRoot\venv\Scripts\python.exe`
  (was bare `pyinstaller`, which resolved to Python 3.13 on PATH without python-calamine). Keeps the
  simple rolled-back structure otherwise. Verified venv has PyInstaller 6.20.0 + python_calamine.


### 2026-06-01 — session 2 (cont.) build.ps1 rolled back to simple style
- Per user: build PaintAllocationDashboard the SAME way as InventoryAllocator. Reverted build.ps1 to
  the original minimal form (bare `pyinstaller --onefile --clean`, in-place dist/build, dist→move).
  Removed: temp-dir workpath/distpath, venv `-m PyInstaller` pinning, preflight dep check,
  `--collect-all python_calamine`, `--hidden-import`, `--add-data`, `--collect-submodules`, Stop-Process.
- Kept ONLY `--paths "Python Script"` on the dashboard target — required because its entry script is in
  PaintAllocationDashboard\ but imports the trusted modules from Python Script\ (InventoryAllocator is
  self-contained so doesn't need it). Calamine now relies on pandas' PyInstaller hook (same as
  InventoryAllocator, which works).
- Runtime frozen-guard fix in the .py is RETAINED (not a build-file concern) — it's what fixes the
  Errno 22 (exe imports trusted modules from its own bundle, not the OneDrive source .py).


### 2026-06-01 — session 2 (cont.) FIX: frozen exe read OneDrive source (.py) → Errno 22
- Coworker (sgroff) crash: `OSError [Errno 22] Invalid argument` reading
  `...\Python Script\inventory_to_release_allocation.py` during import in patch_trusted_paths.
  Cause: bootstrap did `sys.path.insert(0, PROJECT_ROOT/"Python Script")` **even when frozen**, so the
  exe imported the trusted modules from the on-disk OneDrive source — which on a coworker's machine are
  **online-only placeholders** that importlib's get_data can't read (Errno 22). (Confirmed coworker's
  OneDrive mounts the lib WITHOUT the `Projects\000 - Info\` segment — relative-path resolution still
  worked; only the source read failed.)
- FIX (needs rebuild):
  1. Code: guard `sys.path.insert(0, …Python Script)` with `if not getattr(sys,'frozen',False)`. Frozen
     exe imports trusted modules from its own bundle; never touches on-disk .py.
  2. build.ps1: add `--add-data "Python Script\inventory_to_release_allocation.py;."` +
     `…graph_allocator_V2.py;.` so they're guaranteed inside the exe (auto-collection had missed them).
  Dev/script mode unchanged (guard inserts the path; verified import OK, BASE→Production Planning).
- NOTE: raw DATA folders are still read from disk at runtime (by design); OneDrive hydrates those on
  normal open() — only importlib's source read tripped on placeholders.
- (Earlier this session: AV quarantined the onefile exe after a coworker clicked "Block" on a security
  prompt. Mitigations discussed: AV exclusion/whitelist (IT for managed AV), or `--onedir` build to
  reduce PyInstaller false positives. Not yet applied — revisit if AV keeps eating the exe.)


### 2026-06-01 — session 2 (cont.) Bold Slate theme
- Applied "Bold Slate" palette (from concepts file, theme A) to the real dashboard HTML_PAGE:
  slate canvas `#e6e8ee`, white panels, **deep navy header `#27457e`** (white title, light-on-navy
  "Data Pulled At" chip + read-only label, white Refresh btn), navy accent, navy bold pane-head h3,
  vivid coverage `#1f9d4d/#f2bf0b/#f47b1f/#df3b3b`, strong selected-row left-rail + inset ring.
  Converted the datapulled chip to a `.pulled` class (+`.pulled.flash` for auto-update flash) so the
  flash no longer wipes the resting background. VERIFIED via screenshot; no JS errors. Rebuild for exe.


### 2026-06-01 — session 2 (cont.) header trim + ERP auto-update
- **Removed program-start (`generatedAt`) from header.** Header now shows only the title + the
  "Data Pulled At: MM-DD-YY HH:MM:SS" chip (= last raw-data update). Dropped `#genat` element and
  its render line. `generatedAt` still in payload (harmless, unused by UI).
- **Auto-update on new ERP pulls (SUPERSEDES design §8 row 24 "no auto-refresh").**
  - `_raw_data_mtime_epoch()` = max mtime float across raw folders (latest_raw_data_mtime formats it).
  - `start_watcher()` daemon: polls every WATCH_POLL_SEC=15s; when max mtime exceeds the mtime the
    current payload was built from AND has been stable WATCH_DEBOUNCE_SEC=12s (so we don't read a
    half-written export), calls STATE.refresh(). AppState gained `source_mtime` + `refresh_lock`
    (serialises manual+watcher refreshes; refresh captures src mtime BEFORE the read).
  - Gated by config `[refresh] auto_update = true` (default true) and `--no-watch` flag.
  - Browser: 15s `setInterval` polls /snapshot; if `dataPulledAt` changed, `applyPayload()` swaps
    payload, re-inits slider, re-renders, reloads the selected release if still present, flashes the
    chip. No manual action needed.
  - Read-only intact: the watcher only READS raw data + rebuilds derived payload/snapshot.
  - VERIFIED: watcher trigger logic unit-tested (stable→0; settled change→1; mid-pull churn debounced
    →fires once; no double-fire). Header screenshot confirms genat gone. No JS console errors.
- Requires rebuild to land in exe.


### 2026-06-01 — session 2 (cont.) release plant column
- Added `releasePlant` to queue payload (from `Release Plant` col). Queue row order now:
  concern · customer · **plant** · part(+badge) · coverage · ship · bal. New `.qrow .plant` style.
- Row grid retuned: `18px 76px 30px minmax(70px,1fr) 74px 44px 38px`, gap 7. NOTE: the part (1fr)
  column collapsed to 0 when first added — at the 800px preview the left pane pins to 430px and the
  fixed columns summed > pane width, starving 1fr. Trimmed cust/cov/bal widths + `minmax(70px,…)`
  guarantees the part never collapses. VERIFIED via screenshot (P10/P6 between customer and part,
  part numbers visible; aliases Cab Blk/Csc Blk/Ind Chrd render). Requires rebuild for exe.


### 2026-06-01 — session 2 (cont.) "Data Pulled At" header
- Added `latest_raw_data_mtime()` → max file mtime across the raw ERP folders (Inventory,
  Inventory P6, Releases, Process Routings, Part Attributes, BOM/Exploded+Flat), formatted
  `MM-DD-YY HH:MM:SS`. Baked into queue payload as `dataPulledAt`; recomputed every pipeline run
  (so Refresh updates it). Header shows a mono chip "Data Pulled At: …". VERIFIED 06-01-26 12:25:45
  (matches source file timestamps). Requires rebuild to land in exe.


### 2026-06-01 — session 2 (cont.) queue: all-releases, date slider, tri-state EC/PC
- **#1 "look-ahead limit":** investigated — there is NO temporal/count cap in the dashboard OR
  the trusted loader (grep clean). Queue already loads every painted release (1564/1564 across 47
  unique ship dates 2026-04-02..06-15). The only reduction is the by-design paint filter. If the
  user expects later-dated releases, those simply aren't in the current export / are non-paint.
- **#2 date slider:** ship-date range slider (two range inputs `#dLo`/`#dHi` over sorted unique
  DATES), defaults to full range = all visible; `all dates` reset chip. Filter in renderQueue:
  `r.shipDate < DATES[dLo] || > DATES[dHi]` (ISO string compare = chronological). Re-init on
  refresh + load. VERIFIED: hi→0 yields 1 release; reset→1564.
- **#3 tri-state EC/PC:** replaced paintFilter Set with `ecState`/`pcState` ∈ {0 off,1 require,
  -1 exclude}. Chips cycle off→"EC"→"not EC"; `.chip.neg` (red) styling. Colour btn shows only
  when pcState===1. VERIFIED: EC require=1443, not-EC=121, off=1564 (1443+121=1564).
- All in paint_allocation_dashboard.py → requires rebuild to land in exe.


### 2026-06-01 — session 2 (cont.) swatch alias column
- Swatch CSV schema is now **`colour_name, hex, alias`**. `alias` = optional, possibly-longer
  label painted inside the swatch; blank → falls back to auto initials (`_initials`).
- `load_swatch_map()` now returns `name_lower -> {"hex","alias"}`; `paint_badge()` sets
  `colourInitials` = alias-or-initials-or-"?". CSS `.swatch` is now `min-width:21px;width:auto`
  + padding + nowrap so longer aliases grow the chip; colour-filter dots no longer use the
  `.swatch` class (avoids inheriting the min-width). VERIFIED: alias "Cab-Black-Satin" renders;
  no-alias colour falls back to initials. Requires rebuild to land in the .exe.


### 2026-06-01 — session 2 (cont.) build-env fix + 4 UI fixes
- **build.ps1 root cause:** bare `pyinstaller` on PATH = **Python 3.13** (no python-calamine);
  project venv = 3.12 (has it). So `--collect-all python_calamine` bundled nothing → exe failed
  "Missing optional dependency 'python-calamine'" on P6 .xlsx. **Fix:** build.ps1 now invokes
  `venv\Scripts\python.exe -m PyInstaller` for ALL targets, with a preflight import check that
  fails loudly. (Agent cannot run pyinstaller here — drive blocks it — user builds; logic verified.)
- **4 UI fixes (all in paint_allocation_dashboard.py):**
  1. Coverage colours → Green(past)/Yellow(paintable)/Orange(pipeline)/Red(short). Solid fills now
     (dropped the patterns); `--c-*` and `--t-*` vars + legend updated. VERIFIED via screenshot.
  2. Refresh button: `textContent='Refreshing&hellip;'` showed the literal entity → use real `…`.
  3. EC / PC filter chips + a Colour multiselect that appears only when PC is active (with swatch
     dots). Filter logic added to renderQueue. VERIFIED (PC → Colour ▾ appears, count filters).
  4. **Swatch CSV didn't update:** frozen exe's `__file__` points into PyInstaller _MEIPASS, so
     `HERE`/SWATCH_CSV/SNAPSHOT/CONFIG resolved to the temp extract, NOT next to the exe. **Fix:**
     `HERE = _exe_or_script_dir()` (exe dir when frozen). VERIFIED: edit CSV → /refresh → payload
     swatchHex updates (#1a1a1a, white glyph). Seed CSV left as all-grey placeholders.

### 2026-06-01 — session 2 (read-only build)
### 2026-06-01 — session 2 (read-only build)
- Updated design → v10 read-only. Verified step-1 parity (fixed float key bug). Built steps 2–5,7,8
  into `paint_allocation_dashboard.py`. Removed `overrides\`. Server + UI verified via curl
  (queue 1582 releases; detail rid=15 cross-part sub-routing renders).
- NEXT: step 9 polish (ini, swatch csv, .bat, build.ps1, docstring warning). Then have user
  eyeball the live UI in browser.

## Settled decisions (don't re-litigate) — design §8 rows 1–39 + v10 callout
ship-date ASC queue w/ day dividers; Stack default + Flow toggle; heather-gray; auto-only concern;
server-side swatch hex; pie past-paint chip; no overrides/writes (read-only).
