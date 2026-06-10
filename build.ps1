# Builds every distributable .exe by running each per-exe build script in turn.
# To build just one, run its build-<Name>.ps1 directly. Any failure stops the run.
Set-Location $PSScriptRoot

& "$PSScriptRoot\build-GraphAllocator.ps1"
& "$PSScriptRoot\build-PaintAllocationDashboard.ps1"

Write-Host "All builds complete."
