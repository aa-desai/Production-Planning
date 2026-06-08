# Paint Allocation Dashboard — Build Progress

**Resumable build log.** If the session ends, read this top-to-bottom to pick up where we
left off. Single design doc: [DESIGN.md](DESIGN.md) (consolidates the former
`Python Script\paint_dashboard_V2_design.md` + the runlist feature). Engine internals:
`Python Script\graph_allocator_V2_README.md`. UI visual reference:
`Python Script\paint_dashboard_ui_refined.html`.

---

## Status at a glance
- **Part 1 — read-only allocation dashboard: BUILT, verified, shipping** (frozen exe exists).
- **Refactor (2026-06-05): DONE** — now a self-contained `paint_dashboard\` package + vendored engine.
- **Part 2 — PC/EC floor runlists: BUILT & verified (P1–P7 + packaging), 2026-06-05.** Exes not yet produced —
  run `build-PaintAllocationDashboard.ps1`.
- **V2.0.0 — ALL workstreams complete (code):** version-in-header ✅, structural-graph/allocation split ✅, shared
  snapshot pool ✅, personal+shared views ✅, stdlib-only viewers ✅, 10-min event-driven heartbeat ✅. **To ship:**
  run the build (3 exes), bump `__version__` `2.0.0-dev`→`2.0.0`, in-browser click-through smoke. Optional: structural-graph clone.

## Ground rules (do not violate)
- **Never edit** `..\Python Script\inventory_to_release_allocation.py` (trusted; not used by the dashboard).
- **Never change the allocation logic** of `graph_allocator_V2` / `allocation_common`. The dashboard
  vendors byte-identical copies in `paint_dashboard\engine\` (only `graph_allocator_v2.py`'s import is
  package-relative). If the trusted source changes, re-vendor.
- Raw ERP data folders are read-only.
- All dashboard code lives under `PaintAllocationDashboard\`; it is fully self-contained (no imports
  from `..\Python Script\`).
- Paths relative / config-driven for OneDrive portability.
- **Part 1 stays read-only over ERP data.** Part 2 introduces writable runlist state, but **single-writer**
  (planner lock owner) + floor read-only — see DESIGN.md §0/§9/§14.

## Environment (verified)
- Python `3.12.10` at `..\venv\Scripts\python.exe`. pandas 3.0.2, calamine 0.6.2, pyinstaller 6.20.0.
- Run dev: `..\venv\Scripts\python.exe paint_allocation_dashboard.py [--no-browser] [--no-watch] [--parity]`
  (equivalently `..\venv\Scripts\python.exe -m paint_dashboard`). Picks a free 127.0.0.1 port, opens browser.

---

## Part 1 — build status (all done)
- [x] **1. Skeleton** — in-memory `run_pipeline()` mirrors `ga.main()`; returns `PipelineResult`. PARITY OK
      vs `..\Allocations\Allocation_V2.csv` (per-(serial,release) qty exact; float-key normalisation fixed).
- [x] **2. Payload builder** — `build_queue_payload()` → `releases[]` (coverage + concernAuto + paintBadge +
      p10Inventory + hasPaintedSubcomponents). naturalKey = `customer__part__shipISO__relBal__dedupeIdx`.
- [x] **3. Snapshot cache** — atomic `.tmp`→replace; instant open then live rebuild.
- [x] **4. Local server + HTML shell** — `ThreadingHTTPServer`; `GET /`, `/snapshot`, `/detail?rid=`, `POST /refresh`.
- [x] **5. Refresh endpoint** — re-run pipeline; retry once on PermissionError/OSError; 503 on hard fail; atomic swap.
- [~] **6. ~~Override persistence~~ — REMOVED (v10 read-only pivot).** No `overrides\`.
- [x] **7. Detail pane** — routing final-op-first, collapse default (`seq < firstPaintSeq-1`), container cards,
      7-field popover, aggregated MRB card → breakout, Stack + Flow.
- [x] **8. Sub-routings** — recursive `build_detail_tree` for internal releases (Parent Release ID / Consumed At Op).
- [x] **9. Polish** — `.ini` + `load_config`; `powder_colour_swatches.csv` (26 real colours, grey placeholders);
      `Launch …bat`; `build-PaintAllocationDashboard.ps1`; auto-select first release; `.claude/launch.json`.
- [x] **Frozen exe built & verified** (calamine bundled via `--collect-all`; build scratch outside OneDrive;
      frozen path bootstrap resolves the project root from the exe location). 41 MB onefile.
- [x] **Refactor to self-contained modular package** (2026-06-05) — see session log + Key facts below.

## Part 2 — runlist plan (NOT STARTED)
Full spec in **DESIGN.md §8–22**; decisions in **DESIGN.md §21 (R1–R9)**. Build order (DESIGN §20):
- [x] **P1. Model + store + viewer mode** — **DONE 2026-06-05** (riskiest infra bet, proven):
      - [x] **P1a (2026-06-05):** `runlists/model.py` (`RunItem` + `new_doc`/`items_from_doc`, JSON-friendly doc =
            ordered `pc[]`/`ec[]`) + `runlists/store.py` (atomic draft `<run dir>/runlist_draft.json` + live
            `<shared>/Runlists/runlist_live.json`). **Stdlib-only — verified pandas-free import** (R15). Round-trip
            verified (order/identity/fields preserved). PC colour→release grouping derived at render (P7 adds explicit order).
      - [x] **P1b (2026-06-05):** `runlists/grouping.py` `group_pc()` (colour→release→items, order-preserving, qty
            rollups). `runlists/ui.py` (`PC_PAGE`/`EC_PAGE`, Bold-Slate, poll every 15s). `runlists/viewer.py` (stdlib
            `ThreadingHTTPServer`: `GET /` page + `GET /runlist.json` = PC grouped / EC flat). Entry shims
            `runlist_pc.py` / `runlist_ec.py`. Verified: both viewers serve + return correct data (PC 2 colour groups,
            EC 1 item), **viewer import pandas-free** (R15).
- [x] **P2 (2026-06-05).** `runlists/lock.py` — `runlist_owner.lock` on the shared path (machine/user/pid/instance +
      acquired/heartbeat epochs). `acquire()` (free/stale/mine, never seizes a live foreign lock), `try_takeover()`
      (event-driven, missed-heartbeat confirmation window before seizing), `heartbeat()`/`start_heartbeat()` (10-min),
      `release()`. Per-process `instance` id; atomic writes; race re-verify. Unit-tested (5 scenarios incl. revived-owner).
      Integration into the publish path lands with P3/P7.
- [x] **P3 (2026-06-05).** Push → draft → publish.
      - `runlists/push.py`: draft ops (`load/save/add_items/remove_item/clear`), `run_item_from_input` (sanitizes client
        input, server-stamps id/pushedAt/source), `publish()` (takes the lock via `try_takeover`, writes live, starts heartbeat).
      - `server.py`: `GET /runlist/draft.json` (+ pcGroups), `GET /runlist/lock`, `POST /runlist/push`, `POST /runlist/publish`.
      - `ui.py`: per-card checkboxes + "Select allocation"; **qty popup (Required/Entire/Manual) for engine-partial
        containers** (R8); "Push → PC/EC" + "Publish" runbar with draft counts + lock owner.
      - Verified: endpoint cycle (push pc/ec → draft → publish → lock owner=adesai → live written); `node --check` JS OK;
        app boots and serves the runlist UI.
- [x] **P4 (2026-06-05).** `push.cascade_items()` distributes pushed qty across same-part releases FIFO, capping each
      at `relBal − already-placed`, **splitting the boundary container**; overflow beyond all balances stays (never
      dropped) + reported. `server._cascade_context()` builds the FIFO release list + placed-qty from STATE + draft;
      wired into `/runlist/push`. Unit-tested (40/45/50→A100/B35, under-alloc, placed-capacity, overflow) + e2e (live).
- [x] **P5 (2026-06-05).** `push.ec_deficit_items(detail, pc_run_qty, release)` (pure): for a part with both EC & PC ops
      (EC before PC), if the PC run qty exceeds past-EC ("PC-ready") allocated qty, walks needs-EC containers (ops before
      EC) in allocation order and emits EC items (split last) with `source=auto-ec-deficit`. `server._pc_ec_deficit()`
      wires it into `/runlist/push` (PC only). Runbar shows a "⚠ N EC auto-added — review" notice (R4).
      Unit-tested (deficit/no-deficit/not-applicable/shortfall) + live e2e (EC+PC release → applicable). **Colour-coding
      of auto-adds lands in the P7 reorder tab.**
- [x] **P6 (2026-06-05).** `runlists/reconcile.py` — `build_serial_index(result)` (serial→seq/qty/part from the fresh
      graph) + pure `reconcile_items`/`reconcile_doc`: drop containers past their queued paint op or gone from inventory;
      reduce partially-run ones to remaining qty; releases persist (no whole-release drop). `AppState._reconcile_runlist`
      runs it each refresh and republishes live if we own the lock. Unit-tested (keep/reduce/remove/gone) + live e2e
      (fake serial dropped on refresh, real kept; reconcile logged).
- [x] **P7 (2026-06-05).** `push.reorder()` + `POST /runlist/reorder`. UI: "Runlist editor" header button → overlay
      with PC (grouped by colour) + EC lists, **HTML5 drag-and-drop** reordering; auto-EC items amber + review banner;
      "Save order", "Confirm & Publish", and **auto-publish every 10 min while open**. Verified: reorder unit + JS
      `node --check` + live e2e (push S1/S2/S3 → reverse → publish → live order S3/S2/S1).
      NOTE: order is controlled at the item level (colour order follows item order); explicit nested colour-block drag
      can be a later refinement if needed.
- [x] **Packaging (2026-06-05).** `build-PaintAllocationDashboard.ps1` now builds **all three** exes
      (`PaintAllocationDashboard` + `PaintRunlistPC` + `PaintRunlistEC`) via a `Build-Exe` helper; dashboard keeps the
      calamine flags, viewers are plain `--onefile` (stdlib-only). Dropped the obsolete `--paths "Python Script"`.
      Added `Launch PC Runlist.bat` / `Launch EC Runlist.bat` (project root, `%~dp0`-relative). New `[shared] dir`
      config section (blank = local). Script parses; entries import pandas-free. **Run the build to produce the exes**
      (agent doesn't run PyInstaller here, per established practice).

**V2.0.0 cross-cutting workstreams (independent of P1–P7; DESIGN §V/§3.1/§7/§7a):**
- [x] **Graph/allocation split** (DESIGN §3.1, R13/R14) — **DONE 2026-06-05 (2a/2b/2c):**
      - [x] **2a (2026-06-05):** `pipeline.py` split into `load_daily_inputs()` (routing/BOM/attrs/paint flags +
            painted_set) + `run_allocation(daily)` (inventory+releases → build_graph → anchor/allocate). `run_pipeline()`
            now just chains them. Pure refactor — numbers identical (routing 17406, bom 27292, painted 1266, graph 17376, 5091).
      - [x] **2b (2026-06-05):** `AppState.daily` caches `DailyInputs`; `_ensure_daily(force)` rebuilds only on
            first build / new local day / force; `refresh(rebuild_graph=False)` reuses. Verified: 2nd refresh logs
            "Reusing daily inputs" (skips routing/BOM reload). `refresh(rebuild_graph=True)` already wired for 2c.
      - [x] **2c (2026-06-05):** `POST /rebuild-graph` → `refresh(rebuild_graph=True)`; header "Rebuild graph"
            button (forces routing/BOM reload + re-allocate). Verified: forced rebuild logged; button in page.
      - [ ] (optional) structural-graph reuse to skip `build_graph` per refresh (clone) — only if refresh latency still matters.
            NOTE: 2a/2b cache the heavy *daily inputs* (routing/BOM load + paint flags) but `build_graph` still runs each
            refresh (fresh container state → safe, no shared-mutation hazard with concurrent `/detail`).
- [x] **Version** (DESIGN §V, R10) — **DONE 2026-06-05.** `paint_dashboard.__version__` (`2.0.0-dev` for in-dev
      builds; → `2.0.0` when shipped); `appVersion` in queue payload; header shows `v<ver>` via `#appver`.
      Verified end-to-end (snapshot `appVersion=2.0.0-dev`, header span present).
- [x] **Shared snapshot pool** (DESIGN §7, R11) — **DONE 2026-06-05.** Writes to `<shared>/Snapshots/` named
      `Dashboard Snapshot - <ver> - <ComputerID> - <YYYY-MM-DD_HHMMSS>.json` (time = build-init); prunes to the
      5 most-recent (ordered by the **embedded filename time**, not mtime — OneDrive-sync-proof); startup reads the
      newest. New `[shared] dir` config (relative; blank = local default). `platform.node()` ID, sanitized.
- [x] **Personal + shared views** (DESIGN §7a, R12) — **DONE 2026-06-05.** `paint_dashboard/views.py` (one JSON per
      view in `<shared>/Views/`, `{name,filters,creator,updatedAt}`; creator-owned overwrite/delete). Endpoints
      `GET/POST /views`, `POST /views/delete`. UI "Shared" chip row + "+ Share" (publish current filters); `×` on own
      only. Personal presets unchanged (localStorage). Verified e2e (save/list/apply/delete; foreign delete+overwrite blocked).

### Part 2 — open items (DESIGN §22)
- **Resolved:** OneDrive latency accepted; manual split confirmed (15→A, 25→B, 10 unrun); heartbeat 10 min
  event-driven (R16); viewers stdlib-only (R15); snapshots shared/5-total (R11); views personal+shared (R12);
  graph split daily + button (R13/R14).
- **Still to pin during build:** the shared paths + a `[shared]` config section + write permissions per machine;
  the missed-heartbeat confirmation grace window; snapshot-prune concurrency (atomic rename, tolerate races).

---

## Key implementation facts (for resuming)
- **Structure (refactored 2026-06-05):** self-contained package `paint_dashboard\` under
  `PaintAllocationDashboard\`. `paint_allocation_dashboard.py` is a thin launcher shim (kept as the
  build/`.bat`/launch entry) → `paint_dashboard.app.run()`. Logic unchanged (functions moved verbatim).
  Module map: `config`→`bootstrap`→`pipeline`→`parity`→`datasource`→`coverage`/`serialization`/`swatches`→
  `indexes`→`payload`(holds `CURRENT_GRAPH`)→`snapshot`→`state`→`watcher`→`server`→`ui`→`app`.
  Engine vendored in `paint_dashboard\engine\`: `allocation_common.py` (byte-identical) + `graph_allocator_v2.py`
  (only the import is package-relative). No imports from `..\Python Script\`.
- **CURRENT_GRAPH** (in `payload.py`) is set each refresh via `payload.set_current_graph()` so
  `ga_is_past_last_paint()` can read `last_paint_seq` without threading the graph through every call.
- **Indexes** (`build_indexes`): `internal_to_top` (walk Parent Release ID to top external id),
  `alloc_by_top` (top id → rows, **includes** internal-child rows so cross-part coverage rolls up),
  `alloc_by_relid` (exact id → rows), `rework_by_partop`, `swatch_map`, `ext_by_id`.
- **Coverage buckets** (`_bucket_rows`): pastPaint = `Past Last Paint Op`; else paintable if Next Op contains
  EC/PC; else pipeline. short = relBal − sum.
- **concernAuto** (`concern_from_coverage`): good (past≥bal) → low (past+paintable≥bal) → medium (+pipeline≥bal) → high.
- **Detail** built on demand (`GET /detail?rid=`), NOT embedded in the snapshot (keeps it small).
- **KNOWN v1 APPROXIMATION:** cross-part coverage rolls child rows into the parent at face value (BOM multiplier
  assumed ~1 for the *coverage-bar bucketing*). Detail pane shows the true scaled `bomScaledNet`.

## How to run / test
```
cd PaintAllocationDashboard
../venv/Scripts/python.exe paint_allocation_dashboard.py --no-browser           # serves on a free port
# port logged: "Serving dashboard at http://127.0.0.1:PORT/"
# curl http://127.0.0.1:PORT/snapshot              (queue JSON)
# curl "http://127.0.0.1:PORT/detail?rid=15"       (detail tree)
../venv/Scripts/python.exe paint_allocation_dashboard.py --parity --no-browser  # also runs parity
```

---

## Session log (newest first)
### 2026-06-05 — Runlist editor: per-pane Clear buttons
- Added a **Clear** button to each editor pane (PC, EC): empties that target's draft (confirm dialog; floor view
  unaffected until next publish). Backend `POST /runlist/clear {target}` (omit/invalid = both) over the existing
  `push.clear()`; UI `clearTarget()` wired to `#clearPC`/`#clearEC` in the `.ecolhead`.
- Verified: compile + `node --check` + tokens; live e2e (push pc+ec → clear pc → pc=0, ec=1). DESIGN §16/§19 updated.

### 2026-06-05 — V2 build: shared saved-views bank (§7a) — V2 code COMPLETE
- `paint_dashboard/views.py` (stdlib): per-view JSON files in `<shared>/Views/`, creator-owned overwrite/delete.
  Server `GET/POST /views` + `POST /views/delete` (requester = `getpass.getuser()`). UI: "Shared" chip row in the Views
  bar + "+ Share" (publish current `captureFilters()`); apply on click; `×` only on your own. Personal presets untouched.
- Verified: save/list/apply/delete e2e; foreign-owned delete **and** overwrite correctly blocked (409). Compile + JS clean.
- **All V2.0.0 code complete** (34 files compile clean). To ship: run the build, flip `__version__` to `2.0.0`,
  do an in-browser click-through smoke (DnD reorder, qty popup) since those are the only un-automated bits.

### 2026-06-05 — V2 build: packaging (3 exes) + capstone integration
- `build-PaintAllocationDashboard.ps1` rewritten with a `Build-Exe` helper → builds `PaintAllocationDashboard`,
  `PaintRunlistPC`, `PaintRunlistEC` (viewers plain `--onefile`, stdlib-only). Added `Launch PC Runlist.bat` /
  `Launch EC Runlist.bat`. Dropped obsolete `--paths "Python Script"`.
- **Capstone e2e verified:** planner push (PC+EC) → publish → both floor viewers render the shared `runlist_live.json`
  (PC group "TestColour" qty 3 w/ PC1; EC item EC1 qty 2). Full architecture proven on one machine.
- Full package compiles clean (33 files, no SyntaxWarnings); planner + viewer import OK. PS build script parses.
- **Runlist feature (Part 2) functionally complete.** Exes to be produced by running the build. Remaining V2: shared
  saved-views bank (§7a/R12); optional structural-graph clone; in-browser click-through smoke before shipping.

### 2026-06-05 — V2 build: runlist P7 (reorder editor + publish) — P1–P7 COMPLETE
- `push.reorder(draft,target,order_ids)` + `POST /runlist/reorder`. UI editor overlay (`#editor`): PC list grouped by
  colour + EC list, HTML5 drag-and-drop reorder, amber auto-EC + review banner, Save order / Confirm&Publish / Close,
  10-min auto-publish while open. Header "Runlist editor" button.
- Verified: `reorder` unit (+ missing/unlisted safety); `node --check` JS; live e2e (push S1/S2/S3 → reorder reversed →
  draft + published live both S3/S2/S1).
- **Runlist feature P1–P7 all done.** Remaining: packaging (build all 3 exes + viewer launch bats).

### 2026-06-05 — V2 build: runlist P6 (reconciliation on refresh)
- `runlists/reconcile.py` (pure logic + `build_serial_index` over the fresh graph); `AppState._reconcile_runlist`
  called after each successful refresh (best-effort; republishes live when we own the lock so the floor auto-drops run
  containers). Rule R2: past queued paint op / gone → remove; on-hand qty dropped → reduce; release persists until met.
- Verified: unit (keep/reduce/remove/gone, runQtyRemoved=15) + live e2e (push real+fake serial, `/refresh` → fake
  removed, real kept, reconcile log removed=1 kept=1).
- **Next:** P7 — reorder tab (drag-and-drop) + Confirm/publish + 10-min auto-publish (last runlist step before packaging).

### 2026-06-05 — V2 build: runlist P5 (PC→EC deficit auto-fill)
- `push.ec_deficit_items()` (pure, from the detail tree): EC+PC branch only; PC-ready = allocated qty between EC & PC;
  deficit = PC run − PC-ready; covered from needs-EC containers (ops before EC) in allocation order, split last; items
  stamped `source=auto-ec-deficit`, `queuedPaintSeq=ec_seq`. `server._pc_ec_deficit()` adds them on PC push; runbar
  shows the review notice.
- Verified: unit (15-deficit, no-deficit, not-applicable, 14-shortfall) + JS `node --check` + live e2e (EC+PC release,
  applicable=True, 0 added because past-EC covered it).
- **Heuristic flagged for review:** "PC-ready" = allocated qty at ops with `ec_seq ≤ seq < pc_seq` (by op-name contains
  EC/PC). Confirm this matches the floor's notion of "already e-coated" before shipping.
- **Next:** P6 — reconciliation on refresh (remove/reduce run containers; release persists until met).

### 2026-06-05 — V2 build: runlist P4 (over-allocation cascade)
- `push.cascade_items(items, releases_fifo, placed)` (pure): fill selected release to balance, spill surplus to next
  same-part releases (FIFO), split the boundary container; overflow beyond all balances kept on the last release + reported.
- `server._cascade_context()` derives the FIFO same-part release list (Ship Date, Release ID) + already-placed qty from
  STATE + the draft; `/runlist/push` now cascades before adding.
- Verified: 4 unit cases incl. the 40/45/50→A100/B35 example; live e2e (bal 4, pushed 54 → 4 + 50 overflow, total preserved).
- **Next:** P5 — PC→EC deficit auto-fill (auto-add EC feedstock when PC run exceeds past-EC inventory; colour-coded + review).

### 2026-06-05 — V2 build: runlist P3 (selection + push + qty popup + publish)
- Backend `runlists/push.py` (draft authoring + `publish` gated by the P2 lock) + planner endpoints in `server.py`
  (`/runlist/push`, `/runlist/publish`, `/runlist/draft.json`, `/runlist/lock`; added `_read_json`).
- UI (`ui.py`): container checkboxes + "Select allocation"; **qty popup Required/Entire/Manual for engine-partial
  containers** (R8); "Push → PC/EC" + "Publish" runbar showing draft counts + lock owner; selection resets per release.
- Verified: HTTP push/draft/publish/lock cycle (owner=adesai, live written); `node --check` on the embedded JS passes;
  app boots + serves the runlist UI; py_compile clean.
- **Next:** P4 — over-allocation cascade (push qty beyond a release's balance spills to the next same-part release, FIFO).

### 2026-06-05 — V2 build: runlist P2 (single-writer lock)
- `runlists/lock.py` (stdlib-only): lock file `runlist_owner.lock` under `<shared>/Runlists/`; per-process `instance`
  token; `acquire`/`try_takeover`/`heartbeat`/`start_heartbeat`/`release`; `HEARTBEAT_SEC=600`, `STALE_SEC=900`,
  `CONFIRM_SEC=20`. Event-driven takeover with a missed-heartbeat confirmation (re-check before seizing); atomic write
  + re-verify guards simultaneous seizes.
- Verified (5 unit scenarios): fresh acquire; re-acquire preserves `acquiredEpoch`; foreign-LIVE blocks acquire+takeover;
  foreign-STALE seizes after confirmation ("Seizing stale runlist lock" logged); owner revived during confirm window → not seized.
- **Next:** P3 — planner selection + push (+ qty popup) → draft → publish (wires the lock into publish).

### 2026-06-05 — V2 build: runlist P1 COMPLETE (floor viewers)
- Added `runlists/ui.py` (PC + EC floor pages, Bold-Slate theme, fetch `/runlist.json` + 15s poll, flash on new
  publish), `runlists/viewer.py` (stdlib-only `ThreadingHTTPServer`; `GET /` page, `GET /runlist.json` → PC grouped via
  `group_pc` / EC flat; free-port + browser-open like the planner), and entry shims `runlist_pc.py` / `runlist_ec.py`.
- Verified end-to-end against a seeded `runlist_live.json`: PC viewer serves the page + 2 colour groups (Granite, Cab
  Black); EC viewer serves the page + 1 item (qty 8); both `GET /` pages correct; **viewer import is pandas-free** (R15).
- **Next:** P2 — lock owner / heartbeat (`runlist_owner.lock`, 10-min heartbeat, event-driven takeover w/ missed-heartbeat
  confirmation, R6/R16) so only one planner writes the live runlist.

### 2026-06-05 — V2 build (runlist P1b, partial): PC grouping helper
- `runlists/grouping.py`: `group_pc(items)` → `[{colour, qty, releases:[{releaseId, customer, part, shipDate, qty,
  items[]}]}]`, preserving runlist order at every level and rolling up `allocQty`. Pure + stdlib-only (the PC floor
  page renders straight from this). Unit-tested: colour/release order preserved, qty rollups correct (Granite=22 over
  2 releases, Cab Black=3), internal index removed.
- **Next:** the two floor HTML pages (PC via `group_pc`, EC flat) + `runlist_pc.py`/`runlist_ec.py` viewer entries +
  poll loop, against a hand-made `runlist_live.json` (finishes P1b).

### 2026-06-05 — V2 build step 4 (runlist P1a): model + store
- New subpackage `paint_dashboard/runlists/` (stdlib-only, so the floor viewer exes stay tiny — R15):
  `model.py` (`RunItem` dataclass: pushed `partNo/serial/location/allocQty` + internal `releaseId/customer/shipDate/
  powderColour/part/queuedPaintSeq/source/runItemId/pushedAt`; `new_doc()`/`items_from_doc()`); `store.py`
  (atomic `.tmp`→replace for the local draft + shared `Runlists/runlist_live.json`; reuses `[shared] dir`).
- Verified: compile (no warnings); **`import paint_dashboard.runlists.store` pulls no pandas/numpy/engine**; write→read
  round-trip keeps item order, ids, and all fields (pc=2 ec=1; schema/appVersion correct).
- **Next (P1b):** viewer mode — `runlist_pc.py`/`runlist_ec.py` thin entries + the two floor HTML pages that read and
  poll `runlist_live.json` (prove the shared-file round-trip + OneDrive latency with a hand-made live file).

### 2026-06-05 — V2 build step 3: shared snapshot pool (DONE)
- `config.py`: new `[shared] dir` (relative to the .ini, OneDrive-portable) + `shared_dir()` helper (defaults to
  the local run dir → zero-config/local until pointed at a shared folder). `.ini` gains a documented `[shared]` block.
- `snapshot.py`: rewritten as a pool under `<shared>/Snapshots/`. Filename
  `Dashboard Snapshot - <__version__> - <ComputerID> - <YYYY-MM-DD_HHMMSS>.json` (ID = sanitized `platform.node()`;
  time = build-init, threaded from `state.refresh` as `started`). Atomic `.tmp`→replace, then prune to 5 most-recent.
  Ordering uses the **embedded filename timestamp** (parsed via `_TS_RE`), NOT mtime — robust to OneDrive rewriting
  mtimes and to sub-second write bursts. `read_snapshot()` returns the newest.
- `state.py`: captures `started = datetime.now()` per attempt → `write_snapshot(payload, started)`.
- Verified: unit test (7 writes → 5 kept, newest = i6, no SyntaxWarning) + end-to-end (run 1 writes to `Snapshots/`,
  no cached-open; run 2 logs "Loaded cached snapshot (1300 releases)"). Removed 18 orphaned old-scheme snapshots.
- **Next:** personal + shared saved-views bank (§7a/R12), then runlist P1.

### 2026-06-05 — V2 build step 2c: Rebuild-graph endpoint + button (graph split DONE)
- `server.py`: `POST /rebuild-graph` → `STATE.refresh(rebuild_graph=True)` (forces daily-inputs rebuild, then
  re-allocates; otherwise identical to `/refresh`). `ui.py`: header "Rebuild graph" button → `fetch('/rebuild-graph')`
  → swaps in the result (mirrors the Refresh success path; disabled + "Rebuilding…" while in flight).
- Verified: `/rebuild-graph` HTTP 200, log shows "Building daily inputs (forced)", button present in `GET /`.
- **Graph/allocation split workstream complete.** Net effect: routine refreshes reuse the day's routing/BOM-derived
  inputs (skip ~the routing+BOM load + paint-flag compute); the planner can force a full rebuild after a mid-day
  routing/BOM change. (`build_graph` itself still runs per refresh — see the optional structural-clone follow-up.)
- **Next candidate steps:** Shared snapshot pool (§7/R11) or Personal+shared views (§7a/R12), then the runlist P1.

### 2026-06-05 — V2 build step 2b: daily-inputs cache in AppState
- `state.py`: `AppState.daily` + `_ensure_daily(force)` (rebuild on first build / new local day / force) and
  `refresh(rebuild_graph=False)` now calls `run_allocation(self._ensure_daily(...))` instead of `run_pipeline()`.
  Mid-day routing/BOM changes are intentionally not auto-detected (R14) — they need the force path (2c button).
- Verified: cold start logs "Building daily inputs (first build)"; a `POST /refresh` logs "Reusing daily inputs"
  (no routing/BOM reload), releaseCount unchanged (1300). `rebuild_graph=True` force path already in place for 2c.
- **Next (2c):** `POST /rebuild-graph` endpoint + a header "Rebuild graph" button.

### 2026-06-05 — V2 build step 2a: split pipeline (daily inputs vs allocation)
- `pipeline.py`: new `DailyInputs` dataclass + `load_daily_inputs()` (routing/BOM/attributes + paint_flags +
  painted_set, with `built_date`/`built_at`) and `run_allocation(daily)` (inventory+releases → rework split →
  add_prev_next → build_graph → filter/anchor/allocate → finalize). `run_pipeline()` = `run_allocation(load_daily_inputs())`.
- Pure refactor, **no behaviour change**: verified end-to-end — identical numbers (routing 17406, bom 27292,
  painted 1266, inventory 21099, releases 2818, graph nodes 17376, 5091 painted rows, 1300 releases) and still serves.
- **Next (2b):** wire a per-local-day `DailyInputs` cache into `state.py` so routine refreshes skip the daily load.

### 2026-06-05 — V2 build step 1: version in header (DONE)
- Added `paint_dashboard.__version__ = "2.0.0-dev"` (in-dev label; → `2.0.0` on ship). Surfaced as `appVersion`
  in the queue payload (`build_queue_payload`); header `<small id="appver">` shows `v<ver>`, set in `renderQueue`
  (so it follows refresh/auto-update too). Files: `__init__.py`, `payload.py`, `ui.py`.
- Verified: static (HTML markers + payload source) + end-to-end (`/snapshot` `appVersion=2.0.0-dev`; `GET /` has the span).
- **Next:** graph/allocation split (DESIGN §3.1, R13/R14) — the do-first, highest-value workstream.

### 2026-06-05 — consolidate docs (this file + DESIGN.md) + plan Part 2 runlists
- Merged the former `Python Script\paint_dashboard_V2_design.md` (Draft v10) into a single
  `PaintAllocationDashboard\DESIGN.md` (updated to current post-refactor reality) and folded in the full
  PC/EC runlist feature spec. Consolidated this progress log. **Deleted** the merged originals
  (`paint_dashboard_V2_design.md`, and the prior progress file superseded by this one); kept the engine
  README + UI mockup HTML.
- Captured Part-2 decisions R1–R9 (DESIGN §21) and the P1–P7 build order. Nothing implemented yet.

### 2026-06-05 — refactor to self-contained modular package (NO logic change)
- The 1577-line single file became package `paint_dashboard\` (one concern per module). Every function body
  moved **verbatim**; only edits are import wiring, `CURRENT_GRAPH` set via `payload.set_current_graph()`,
  and `config.run_dir()` path arithmetic (still returns the same `PaintAllocationDashboard\` run dir).
  `paint_allocation_dashboard.py` is now a thin shim → `app.run()`.
- **Self-containment:** trusted modules vendored into `paint_dashboard\engine\`. `diff` confirms
  `allocation_common.py` byte-identical; `graph_allocator_v2.py` differs only by the package-relative import
  (+ a header comment). No allocation logic touched. Dashboard no longer reads `..\Python Script\`.
- **HTML** extracted verbatim into `paint_dashboard\ui.py` (in-module string → one-file exe needs no `--add-data`).
- **Verified (venv, live data):** clean byte-compile (no SyntaxWarnings), import OK (no cycles), full run builds
  graph (nodes=17376, painted=1266), allocates (5091 rows), caches snapshot, serves. Endpoints checked:
  `GET /` 601KB w/ payload injected, `/snapshot` 1300 releases/19 customers, `/detail?rid=0` → 5 ops.
- **Parity note:** `--parity` mismatches the stale `..\Allocations\Allocation_V2.csv` (5471 vs 5091) — stale
  reference data, not a regression (engine byte-identical). Regenerate the CSV via `ga.main()` for a clean pass.
- **Build:** `build-PaintAllocationDashboard.ps1` still works unchanged; its `--paths "Python Script"` flag is
  now unnecessary (harmless). Rebuild the exe to ship.

### 2026-06-03 — session 3 header alignment + filter presets (views)
- Both title bars get `.pane-head.headbar{min-height:48px}` so "Release Queue"/"Selected Release" line up.
- Filter area split into "Views" (presets) | divider | "Quick filters". Filter presets (`+ Save view`) store
  `captureFilters()` in `localStorage['paintPresets']`; chips apply/delete; `Clear` resets. Local-only (read-only safe).

### 2026-06-03 — session 3 resizable pane + animated Stack/Flow toggle
- Draggable splitter (`.gutter`, `--leftw`, clamp [440, container−gutter−340], persisted to `localStorage`).
- Stack/Flow = animated segmented control (sliding thumb 0.2s; 200ms vfade on the shown pane).

### 2026-06-03 — session 3 FIX: row highlight/overflow at narrow widths
- `.qrow` grid switched to shrinkable tracks `18 minmax(0,84) 30 minmax(56,1fr) minmax(38,64) 60 minmax(40,auto)`
  + `min-width:0;overflow:hidden` so the row always fits the pane and the selection highlight covers it fully.

### 2026-06-03 — session 3 UI feedback round 2 (copy left, dates, refresh anim)
- Copy button moved left of the part #; Material content_copy glyph; ship dates MM-DD-YY nowrap; darker/larger text;
  Refresh button reworked (animates width, spinner→check-circle, green done / red fail; `flex:0 0 auto` required).

### 2026-06-03 — session 3 readability + copy button
- Larger/darker text; releases pane widened (~45%); per-row copy button (`navigator.clipboard` + execCommand fallback).

### 2026-06-03 — session 3 docs: verify comments + engine README
- Verified `graph_allocator_V2.py` comments vs code (only stale spot: module-docstring Outputs list — rewrote).
- Created `Python Script\graph_allocator_V2_README.md` (purpose/run/inputs/outputs/columns/deps/consumers/invariants).

### 2026-06-03 — session 3 FIX: internal-release rows leaked synthetic customer
- `attach_filter_columns`: `Filter: Customer` now rolls up to the top-level external release (`customer_by_id[top]`)
  instead of the synthetic `Internal-…` anchor customer. Re-verified: 0 customer/condition/P10 mismatches; PARITY OK.

### 2026-06-03 — session 3 propagate filters into graph_allocator_V2.py CSV
- **NOTE:** user explicitly authorised editing `graph_allocator_V2.py` for this (adding output columns only).
- Added `Filter: Customer/EC/PC/Colour/Inventory at P10/Condition/Ship Date` columns to Allocation_V2.csv via
  `attach_filter_columns` (mirrors the dashboard's bucketing/roll-up exactly). Allocation rows/qty unchanged. PARITY OK.

### 2026-06-03 — session 3 "Inventory at P10" filter
- New queue toggle: hides P6 releases whose entire routing has no P10 inventory. Server computes `p10Inventory` via
  `parts_with_p10_inv` ∩ `reachable_parts`; `_container_at_p10` = plant P10 OR location `Modineer - P10`.

### 2026-06-03 — session 3 hide-by-condition filters
- Replaced "hide good" with four hide chips (good/low/med/short → green/yellow/orange/red); client-only over `concernAuto`.

### 2026-06-01 — session 2 (cont.) bundle calamine + build-env fixes
- `--collect-all python_calamine` + `--hidden-import pandas.io.excel._calamine` (pandas' hook missed the .pyd).
- `build.ps1` invokes `venv\Scripts\python.exe -m PyInstaller` (bare `pyinstaller` on PATH = 3.13, no calamine).
- Build scratch to `%TEMP%` (OneDrive locks `build\...\localpycs` during `--clean`). Stop running exe before copy.

### 2026-06-01 — session 2 (cont.) FIX: frozen exe read OneDrive source (.py) → Errno 22
- Guard `sys.path.insert(0, …Python Script)` with `if not frozen` so the frozen exe imports trusted modules from its
  own bundle (coworker OneDrive online-only placeholders failed importlib's get_data with Errno 22). [Now moot: the
  refactor vendors the engine inside the package.]

### 2026-06-01 — session 2 (cont.) Bold Slate theme + header trim + ERP auto-update
- Applied Bold Slate palette. Removed program-start `generatedAt` from header (kept "Data Pulled At").
- Auto-update watcher: `_raw_data_mtime_epoch` + `start_watcher` (poll 15s, debounce 12s) → `STATE.refresh()`;
  browser polls `/snapshot` (15s) and swaps in place. Gated by `[refresh] auto_update` / `--no-watch`.

### 2026-06-01 — session 2 (cont.) queue extras
- `releasePlant` column; all-releases (no look-ahead cap — only the paint filter reduces); ship-date range slider;
  tri-state EC/PC; swatch alias column; "Data Pulled At" header; server-side swatch hex (`HERE = _exe_or_script_dir()`).

### 2026-06-01 — session 2 (read-only build)
- Updated design → v10 read-only. Step-1 parity (float key bug fixed). Built steps 2–5,7,8. Removed `overrides\`.

## Settled decisions (don't re-litigate)
See **DESIGN.md §21**. Headline: ship-date-ASC queue w/ day dividers; Stack default + Flow toggle; Bold Slate;
auto-only quantity-based concern; server-side swatch hex; pie past-paint chip; **no overrides/writes in Part 1**
(read-only); Part 2 runlists are single-writer (planner lock owner) + floor read-only.
