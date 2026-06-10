"""
Raw ERP data freshness ("Data Pulled At")
=========================================
Reports the most-recent mtime across the raw ERP source folders. Used both for the
header's "Data Pulled At" label and the auto-update watcher.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from .engine import allocation_common as common


def _raw_data_mtime_epoch() -> float:
    """Most recent file mtime (epoch seconds) across the raw ERP source folders.

    Reads the patched `path_*` on allocation_common (already pointed at the
    resolved project root). Used both for the "Data Pulled At" label and the
    auto-update watcher.
    """
    dirs = [
        common.path_inv_p6, common.path_inv_p10, common.path_releases,
        common.path_process_routings, common.path_attributes,
        common.path_bom_exploded, common.path_bom_flat,
    ]
    latest = 0.0
    for d in dirs:
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_file():
                        m = e.stat().st_mtime
                        if m > latest:
                            latest = m
        except OSError:
            continue
    return latest


def latest_raw_data_mtime() -> Optional[str]:
    """"MM-DD-YY HH:MM:SS" of the most recent raw-data file, or None."""
    ep = _raw_data_mtime_epoch()
    return datetime.fromtimestamp(ep).strftime("%m-%d-%y %H:%M:%S") if ep > 0 else None
