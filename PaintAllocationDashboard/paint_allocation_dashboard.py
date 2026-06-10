r"""
Paint Allocation Dashboard  (READ-ONLY) — entry point
=====================================================
Thin launcher for the :mod:`paint_dashboard` package. The dashboard re-runs the V2
graph-allocation pipeline in memory and serves a read-only, two-pane view from a
local ``http.server``. It is fully self-contained under ``PaintAllocationDashboard\``:
the allocation engine it runs is a vendored copy in :mod:`paint_dashboard.engine`, so
nothing here depends on the external ``Python Script\`` folder.

This file stays the launch target so existing tooling keeps working unchanged:
``Launch Paint Allocation Dashboard.bat``, ``build-PaintAllocationDashboard.ps1``
(PyInstaller entry), and ``.claude/launch.json``. All real code lives in the package.

Run (dev):  ``..\venv\Scripts\python.exe paint_allocation_dashboard.py``
            (equivalently: ``..\venv\Scripts\python.exe -m paint_dashboard``)

CLI flags: ``--no-browser``, ``--no-watch``, ``--parity``, ``--config <path>``.
Design + build log: ``DESIGN.md`` / ``PROGRESS.md`` (in this folder).
"""

from __future__ import annotations

import os
import sys

# When launched as a loose script (``python paint_allocation_dashboard.py``) the
# script's own folder is already on sys.path, so ``paint_dashboard`` imports cleanly.
# Belt-and-braces for odd launchers: ensure this folder is importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paint_dashboard.app import run  # noqa: E402

if __name__ == "__main__":
    run()
