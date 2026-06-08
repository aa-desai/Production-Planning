@echo off
REM Launch the EC Runlist floor view (read-only).
REM %~dp0 = the folder THIS .bat lives in, so the path stays correct on every machine.
start "" "%~dp0PaintAllocationDashboard\PaintRunlistEC.exe"
