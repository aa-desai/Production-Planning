"""
Project-root bootstrap (design §6a.4)
=====================================
Resolve the project root (``Production Planning\\``) regardless of whether we run as
a script or a frozen ``.exe``, and point the vendored engine's data layer at it.
``configure()`` must run before any pipeline call.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from . import log
from .config import CONFIG, RAW_DATA_SUBFOLDERS, run_dir

# Resolved project root (the folder holding the raw-data subfolders). Populated by
# :func:`configure`; ``None`` until then.
PROJECT_ROOT: Optional[Path] = None


def _looks_like_project_root(p: Path) -> bool:
    """True if *p* contains the expected raw-data subfolders."""
    try:
        return all((p / sub).is_dir() for sub in ("Inventory", "Releases", "Process Routings"))
    except OSError:
        return False


def _find_project_root(start: Path) -> Optional[Path]:
    """Walk up from *start* looking for a dir that holds the raw-data folders."""
    for cand in [start, *start.parents]:
        if _looks_like_project_root(cand):
            return cand
    return None


def resolve_project_root() -> Path:
    """Resolve the project root (``Production Planning\\``).

    Order: explicit env/CLI override (future) → walk up from this file →
    walk up from cwd → walk up from the frozen exe dir. Fails loudly.
    """
    # 1. Explicit config override wins, if it points at a valid root.
    cfg_root = CONFIG.get("project_root")
    if cfg_root is not None and _looks_like_project_root(cfg_root):
        return cfg_root
    here = run_dir()
    candidates = [here, Path.cwd().resolve()]
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.executable).resolve().parent)
    for c in candidates:
        root = _find_project_root(c)
        if root is not None:
            return root
    raise SystemExit(
        "Could not locate the project root (a folder containing "
        f"{RAW_DATA_SUBFOLDERS}). Looked up from: {[str(c) for c in candidates]}"
    )


def patch_trusted_paths(project_root: Path) -> None:
    """Repoint the vendored data layer (and graph_allocator_v2's copies) at *project_root*.

    ``allocation_common`` owns ``BASE`` + the ``path_*`` constants; ``rebind_base``
    updates them in place. ``graph_allocator_v2`` imported a subset of those names by
    value at import time, so we refresh its copies too. No module source is edited.
    """
    from .engine import allocation_common as common
    from .engine import graph_allocator_v2 as ga

    common.rebind_base(project_root)

    ga.BASE = project_root
    for name in ("path_releases", "path_process_routings", "path_attributes", "path_bom_exploded"):
        if hasattr(ga, name):
            setattr(ga, name, getattr(common, name))

    # Sanity: the resolved root must actually hold the raw-data folders.
    for sub in ("Inventory", "Releases", "Process Routings"):
        assert (project_root / sub).is_dir(), f"Expected raw-data folder missing: {project_root / sub}"
    log.info("Project root resolved + paths patched: %s", project_root)


def configure() -> Path:
    """Resolve the project root and patch the engine. Idempotent; returns the root."""
    global PROJECT_ROOT
    PROJECT_ROOT = resolve_project_root()
    patch_trusted_paths(PROJECT_ROOT)
    return PROJECT_ROOT
