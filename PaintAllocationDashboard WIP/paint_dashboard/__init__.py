r"""Paint Allocation Dashboard (READ-ONLY)
======================================
Interactive, in-memory replacement for the ``Allocation_V2.csv`` Excel workflow.

The dashboard re-runs the V2 graph-allocation pipeline in memory and serves a
two-pane, read-only view from a local ``http.server``. No UI action mutates any
file; the only file written is a local, per-machine snapshot cache
(``paint_allocation_dashboard_snapshot.json``) — a derived performance file.

This package is fully self-contained under ``PaintAllocationDashboard\``: the
allocation engine it runs lives in :mod:`paint_dashboard.engine` (a vendored copy
of the trusted ``graph_allocator_V2`` / ``allocation_common`` modules).

Module map
----------
* :mod:`~paint_dashboard.config`        — config file + run-dir / project-root paths.
* :mod:`~paint_dashboard.bootstrap`     — resolve the project root, point the engine at it.
* :mod:`~paint_dashboard.pipeline`      — ``run_pipeline`` -> ``PipelineResult``.
* :mod:`~paint_dashboard.parity`        — optional parity check vs the on-disk CSV.
* :mod:`~paint_dashboard.datasource`    — raw-data mtime helpers ("Data Pulled At").
* :mod:`~paint_dashboard.coverage`      — coverage bucketing + concern classification.
* :mod:`~paint_dashboard.serialization` — JSON-safe scalar coercion.
* :mod:`~paint_dashboard.swatches`      — powder-colour swatch map + paint badges.
* :mod:`~paint_dashboard.indexes`       — derived lookup indexes over a ``PipelineResult``.
* :mod:`~paint_dashboard.payload`       — queue payload + on-demand detail tree.
* :mod:`~paint_dashboard.snapshot`      — local snapshot cache read/write.
* :mod:`~paint_dashboard.state`         — in-memory ``AppState`` (refresh under lock).
* :mod:`~paint_dashboard.watcher`       — ERP auto-update watcher.
* :mod:`~paint_dashboard.server`        — read-only HTTP endpoints.
* :mod:`~paint_dashboard.ui`            — embedded single-page UI.
* :mod:`~paint_dashboard.app`           — ``main`` / ``run`` entry point.

Design + build log: ``DESIGN.md`` / ``PROGRESS.md`` (in the PaintAllocationDashboard folder).
"""

from __future__ import annotations

import logging
import sys

# Configure logging once for the whole package. ``basicConfig`` is idempotent, so a
# later call from the vendored engine modules is a harmless no-op.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Application version (SemVer; see DESIGN.md §V). MAJOR = capability epoch
# (1 = read-only dashboard, 2 = + PC/EC runlists). In-development builds toward the
# next release carry a "-dev" suffix; drop it when that version is complete & verified.
__version__ = "2.0.0-dev"

# Shared logger name, matching the original single-file module.
log = logging.getLogger("paint_dashboard")

__all__ = ["log", "__version__"]
