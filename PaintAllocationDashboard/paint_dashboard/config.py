"""
Configuration + run-directory resolution
=========================================
The dashboard is otherwise zero-config; this module is its only configuration
surface. It reads the optional ``paint_allocation_dashboard.ini`` and resolves the
"run directory" — the folder that holds the planner-facing files (``.ini``, the
swatch CSV, the snapshot cache) and, when frozen, the ``.exe`` itself.
"""

from __future__ import annotations

import configparser as _cp
import sys
from pathlib import Path
from typing import Optional

from . import log

# Raw-data subfolders that identify a valid project root (design §6a.4).
RAW_DATA_SUBFOLDERS = ("Inventory", "Releases", "Process Routings", "Part Attributes", "BOM")


def run_dir() -> Path:
    """Folder the planner's files live beside (config / swatch CSV / snapshot / exe).

    Resolves next to the EXE when frozen (NOT PyInstaller's temp ``_MEIPASS`` that
    ``__file__`` points at), else the ``PaintAllocationDashboard\\`` folder that
    contains this package. This is the same directory the original single-file
    script resolved via ``_exe_or_script_dir()``.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # This module lives at ``PaintAllocationDashboard\paint_dashboard\config.py``; the
    # run directory is two levels up (``PaintAllocationDashboard\``).
    return Path(__file__).resolve().parent.parent


def load_config() -> dict:
    """Read ``paint_allocation_dashboard.ini`` if present (design §6a.4).

    Search order: ``--config <path>`` → exe/script dir → one level up → cwd.
    Returns a plain dict with optional keys: ``project_root`` (absolute Path),
    ``host`` (str), ``port`` (int). Missing file / keys → empty/defaults; the
    auto-resolver fills the rest. This is the only configuration surface; the
    dashboard is otherwise zero-config.
    """
    cfg_path: Optional[Path] = None
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        if i + 1 < len(sys.argv):
            cfg_path = Path(sys.argv[i + 1]).expanduser().resolve()
    if cfg_path is None:
        d = run_dir()
        for cand in (d / "paint_allocation_dashboard.ini",
                     d.parent / "paint_allocation_dashboard.ini",
                     Path.cwd() / "paint_allocation_dashboard.ini"):
            if cand.is_file():
                cfg_path = cand
                break
    out: dict = {}
    if cfg_path is None or not cfg_path.is_file():
        return out
    try:
        cp = _cp.ConfigParser(inline_comment_prefixes=(";", "#"))
        cp.read(cfg_path, encoding="utf-8")
        base = cfg_path.parent
        if cp.has_option("paths", "project_root"):
            pr = cp.get("paths", "project_root").strip()
            if pr:
                out["project_root"] = (base / pr).resolve()
        if cp.has_option("server", "host"):
            out["host"] = cp.get("server", "host").strip() or "127.0.0.1"
        if cp.has_option("server", "port"):
            try:
                out["port"] = int(cp.get("server", "port").strip())
            except ValueError:
                pass
        if cp.has_option("refresh", "auto_update"):
            out["auto_update"] = cp.getboolean("refresh", "auto_update", fallback=True)
        if cp.has_option("shared", "dir"):
            sd = cp.get("shared", "dir").strip()
            if sd:
                out["shared_dir"] = (base / sd).resolve()
        log.info("Loaded config: %s", cfg_path)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not parse config %s: %s", cfg_path, e)
    return out


# Resolved once at import, as in the original single-file module.
CONFIG = load_config()

# Planner-facing files that live in the run directory.
CONFIG_FILE = run_dir() / "paint_allocation_dashboard.ini"


def shared_dir() -> Path:
    """Shared root for cross-machine files (snapshots now; runlists / views / lock later).

    Configured via ``[shared] dir`` (relative to the config file, OneDrive-portable).
    Defaults to the local run directory when unset, so the dashboard stays zero-config and
    fully local until a shared OneDrive/network folder is pointed at.
    """
    d = CONFIG.get("shared_dir")
    return d if d is not None else run_dir()
