@echo off
REM Launch the WIP suite from SOURCE (the "PaintAllocationDashboard WIP" folder), using the
REM project venv -- no frozen exes. Opens three windows: the planner dashboard + both runlist
REM floor views. Use this to try in-progress changes.
REM %~dp0 = the folder THIS .bat lives in, so paths stay correct on every machine.
REM /d sets each process's working dir to the WIP folder so the .ini / data paths resolve as in dev.
set "PY=%~dp0venv\Scripts\python.exe"
set "WIP=%~dp0PaintAllocationDashboard WIP"
start "Paint Allocation Dashboard (WIP)" /d "%WIP%" "%PY%" paint_allocation_dashboard.py
start "PC Runlist (WIP)" /d "%WIP%" "%PY%" runlist_pc.py
start "EC Runlist (WIP)" /d "%WIP%" "%PY%" runlist_ec.py
