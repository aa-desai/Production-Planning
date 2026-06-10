"""
Floor runlists (design Part 2)
==============================
PC / EC run queues authored by the planner and published to a shared file the floor
viewers render. This subpackage is **stdlib-only** (no pandas / engine) so the floor
viewer exes that import it stay tiny (R15).

* :mod:`~paint_dashboard.runlists.model` — ``RunItem`` + the published-document shape.
* :mod:`~paint_dashboard.runlists.store` — atomic read/write of the draft (local) and
  live (shared) runlist files.
"""
