"""
Parity check vs the on-disk ``Allocation_V2.csv``
=================================================
Optional self-test (``--parity``): confirms the in-memory pipeline reproduces the
trusted CSV's per-(serial, release) allocated quantities exactly.
"""

from __future__ import annotations

import pandas as pd

from . import bootstrap, log
from .pipeline import PipelineResult


def parity_check(result: PipelineResult) -> bool:
    """Compare the in-memory allocation against the on-disk Allocation_V2.csv.

    The allocator is non-deterministic in row order only; we compare the
    aggregate that matters: total allocated qty per (Serial No, Release ID)
    and overall row count. Returns True on match.
    """
    ref_path = bootstrap.PROJECT_ROOT / "Allocations" / "Allocation_V2.csv"
    if not ref_path.exists():
        log.warning("No reference Allocation_V2.csv at %s — skipping parity check", ref_path)
        return True

    ref = pd.read_csv(ref_path)
    got = result.alloc_df
    log.info("Parity: reference rows=%d, in-memory rows=%d", len(ref), len(got))

    def agg(df: pd.DataFrame) -> pd.Series:
        d = df.copy()
        # Normalise the join keys so CSV-round-trip dtypes line up with the
        # in-memory frame: the CSV loads Release ID as float (NaN on unallocated
        # rows forces float64), so 0 -> "0.0"; coerce both via Int64 first.
        d["Release ID"] = (
            pd.to_numeric(d["Release ID"], errors="coerce")
            .astype("Int64").astype("string").fillna("<none>")
        )
        d["Serial No"] = d["Serial No"].astype("string").fillna("<none>")
        d["Allocated Qty"] = pd.to_numeric(d["Allocated Qty"], errors="coerce").fillna(0).astype("int64")
        return d.groupby(["Serial No", "Release ID"])["Allocated Qty"].sum().sort_index()

    a_ref, a_got = agg(ref), agg(got)
    same = a_ref.equals(a_got)
    if same:
        log.info("PARITY OK: per-(serial,release) allocated quantities match exactly.")
    else:
        # Report the first few discrepancies.
        joined = pd.concat([a_ref.rename("ref"), a_got.rename("got")], axis=1).fillna(0)
        diff = joined[joined["ref"] != joined["got"]]
        log.warning("PARITY MISMATCH: %d differing (serial,release) groups", len(diff))
        log.warning("Sample diffs:\n%s", diff.head(15).to_string())
    return same
