"""
JSON-safe scalar coercion
=========================
Helpers to turn pandas / NumPy / Timestamp scalars into plain JSON-serialisable
values for the payloads served to the browser.
"""

from __future__ import annotations

from datetime import datetime, date

import pandas as pd


def _jsonsafe(v):
    """Coerce pandas/NumPy/Timestamp scalars to JSON-serialisable values."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    if hasattr(v, "item"):
        try:
            return v.item()
        except (ValueError, AttributeError):
            pass
    return v


def _ship_iso(v) -> str:
    s = _jsonsafe(v)
    return s if isinstance(s, str) else ""
