r"""
EC Runlist — floor viewer entry point
=====================================
Read-only shop-floor view of the EC runlist published by the planner dashboard. Reads the
shared ``runlist_live.json`` (no pipeline, no pandas) and serves the EC floor page.

This is the build/launch target for ``PaintRunlistEC.exe`` (see build script). Keep it a
thin shim so the packaged exe stays tiny.

Run (dev):  ``..\venv\Scripts\python.exe runlist_ec.py``   (``--no-browser`` to skip auto-open)
Config:     ``[shared] dir`` in ``paint_allocation_dashboard.ini`` locates the shared runlist.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paint_dashboard.runlists.viewer import run  # noqa: E402

if __name__ == "__main__":
    run("ec")
