# Builds GraphAllocator.exe (the graph-based paint allocation engine, graph_allocator_V2.py).
# Self-contained: run this file directly to (re)build just this exe.
Set-Location $PSScriptRoot

# Use the project's OWN venv interpreter, NOT a bare `pyinstaller` on PATH — on this
# machine that resolves to a different Python that lacks python-calamine.
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

# PyInstaller scratch dirs MUST live outside OneDrive. Building into OneDrive-synced
# folders intermittently fails with "Access is denied" (PermissionError [WinError 5])
# because OneDrive locks files under build\...\localpycs while --clean removes them.
$work = Join-Path $env:TEMP "pai_GraphAllocator_build"
$dist = Join-Path $env:TEMP "pai_GraphAllocator_dist"
$spec = Join-Path $env:TEMP "pai_GraphAllocator_spec"
Remove-Item -Recurse -Force $work, $dist, $spec -ErrorAction SilentlyContinue

# Stop any running instance so the destination .exe isn't file-locked on copy.
Get-Process GraphAllocator -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# Excel-engine bundling: pandas reads .xlsx via engine="calamine", a lazy string-
# triggered import PyInstaller's static analysis can miss (→ "Missing optional
# dependency 'python-calamine'" at runtime). Collect it explicitly rather than
# relying on the bundled pandas hook.
& $py -m PyInstaller --onefile --clean --workpath $work --distpath $dist --specpath $spec `
  --collect-all python_calamine --hidden-import pandas.io.excel._calamine `
  --name GraphAllocator "Python Script\graph_allocator_V2.py"
if ($LASTEXITCODE -ne 0) { throw "GraphAllocator build failed (exit $LASTEXITCODE)" }

Copy-Item -Force (Join-Path $dist "GraphAllocator.exe") .\
Write-Host "Built GraphAllocator.exe"
