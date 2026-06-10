@echo off
REM Launch the Paint Allocation Dashboard (read-only).
REM %~dp0 = the folder THIS .bat lives in, so the path stays correct on every
REM coworker's machine regardless of their C:\Users\<name>\OneDrive prefix.
start "" "%~dp0PaintAllocationDashboard\PaintAllocationDashboard.exe"
