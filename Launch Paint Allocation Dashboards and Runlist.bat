@echo off
REM DEV launcher: run the dashboard suite from SOURCE (PaintAllocationDashboard\) using the
REM project venv -- no frozen exes. Opens three windows: the planner dashboard + both runlist
REM floor views. Use this to try code changes before rebuilding the exes.
REM %~dp0 = the folder THIS .bat lives in, so paths stay correct on every machine.
REM /d sets each process's working dir so the .ini / data paths resolve as in dev.
set "PY=%~dp0venv\Scripts\python.exe"
set "SRC=%~dp0PaintAllocationDashboard"
start "Paint Allocation Dashboard (source)" /d "%SRC%" "%PY%" paint_allocation_dashboard.py
start "PC Runlist (source)" /d "%SRC%" "%PY%" runlist_pc.py
start "EC Runlist (source)" /d "%SRC%" "%PY%" runlist_ec.py
