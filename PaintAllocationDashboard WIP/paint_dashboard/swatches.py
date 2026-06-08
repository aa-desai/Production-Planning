"""
Powder-colour swatches + paint badges (server-side, design B6)
==============================================================
Reads the planner-curated swatch CSV and builds the paint badge (EC / PC + colour
swatch) attached to each release in the queue payload.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from . import log
from .config import run_dir

# Planner-curated swatch CSV, beside the run directory.
SWATCH_CSV = run_dir() / "powder_colour_swatches.csv"


def load_swatch_map() -> dict[str, dict]:
    """colour_name -> {"hex", "alias"} from the planner-curated CSV (server-side, B6).

    Schema: ``colour_name, hex, alias``. ``hex`` blank → neutral grey. ``alias``
    is the (optionally longer) label painted inside the swatch; blank → the UI
    falls back to auto-generated initials.
    """
    if not SWATCH_CSV.exists():
        return {}
    try:
        df = pd.read_csv(SWATCH_CSV, dtype=str).fillna("")
        out = {}
        for _, r in df.iterrows():
            name = str(r.get("colour_name", "")).strip()
            hexv = str(r.get("hex", "")).strip()
            alias = str(r.get("alias", "")).strip()
            if name:
                out[name.lower()] = {"hex": hexv or "#9aa0a8", "alias": alias}
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read swatch CSV: %s", e)
        return {}


def _glyph_for(hexv: str) -> str:
    """Contrast-aware glyph colour for initials painted inside a swatch."""
    try:
        h = hexv.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#222" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#fff"
    except Exception:  # noqa: BLE001
        return "#fff"


def _initials(name: str) -> str:
    parts = [p for p in str(name).replace("-", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def paint_badge(ecoat: bool, powdercoat: bool, colour: str, swatch_map: dict) -> Optional[dict]:
    if not (ecoat or powdercoat):
        return None
    if powdercoat:
        cname = colour if colour not in (None, "", "None", "Not Found") else None
        entry = swatch_map.get(str(colour).lower()) if cname else None
        hexv = (entry or {}).get("hex") or "#9aa0a8"
        alias = (entry or {}).get("alias") or ""
        # Swatch label: planner-set alias wins; else auto initials; else "?".
        label = alias if alias else (_initials(cname) if cname else "?")
        badge = {
            "type": "EC+PC" if ecoat else "PC",
            "colourName": cname or "Unknown",
            "colourInitials": label,
            "swatchHex": hexv,
            "glyphHex": _glyph_for(hexv),
        }
        return badge
    return {"type": "EC"}
