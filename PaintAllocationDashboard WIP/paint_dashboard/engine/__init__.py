r"""
Vendored allocation engine
===========================
Self-contained copies of the two trusted modules the dashboard runs in memory:

* :mod:`allocation_common`   — shared ERP-data layer (paths, loaders, cleaners).
* :mod:`graph_allocator_v2`  — the graph allocation engine.

The source of truth for both lives in the project's ``Python Script\`` folder; these
are vendored here so the dashboard depends on nothing outside ``PaintAllocationDashboard\``.
``allocation_common`` is an unmodified copy; ``graph_allocator_v2`` differs only in a
single import line (made package-relative). No allocation logic was changed.

Import them as the dashboard always has::

    from .engine import allocation_common as common
    from .engine import graph_allocator_v2 as ga
"""
