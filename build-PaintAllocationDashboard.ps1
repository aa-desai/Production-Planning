# Builds the three Paint dashboard / runlist exes:
#   PaintAllocationDashboard.exe  — the planner dashboard (read-only allocation + runlist authoring)
#   PaintRunlistPC.exe            — PC floor viewer (read-only, stdlib-only, no pandas)
#   PaintRunlistEC.exe            — EC floor viewer (read-only, stdlib-only, no pandas)
# Self-contained: run this file directly to (re)build all three.
Set-Location $PSScriptRoot

# Use the project's OWN venv interpreter, NOT a bare `pyinstaller` on PATH — on this
# machine that resolves to a different Python that lacks python-calamine.
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

# PyInstaller scratch dirs MUST live outside OneDrive. Building into OneDrive-synced
# folders intermittently fails with "Access is denied" (PermissionError [WinError 5])
# because OneDrive locks files under build\...\localpycs while --clean removes them.
function Build-Exe([string]$name, [string]$entry, [string[]]$extra) {
  $work = Join-Path $env:TEMP "pai_${name}_build"
  $dist = Join-Path $env:TEMP "pai_${name}_dist"
  $spec = Join-Path $env:TEMP "pai_${name}_spec"
  Remove-Item -Recurse -Force $work, $dist, $spec -ErrorAction SilentlyContinue
  # Stop any running instance so the destination .exe isn't file-locked on copy.
  Get-Process $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  $pyargs = @('-m', 'PyInstaller', '--onefile', '--clean',
              '--workpath', $work, '--distpath', $dist, '--specpath', $spec) + $extra + @('--name', $name, $entry)
  & $py @pyargs
  if ($LASTEXITCODE -ne 0) { throw "$name build failed (exit $LASTEXITCODE)" }
  # Output goes BESIDE the entry scripts in PaintAllocationDashboard\ — the folder the
  # launch bats run these exes from.
  $src = Join-Path $dist "$name.exe"
  $dst = Join-Path ".\PaintAllocationDashboard" "$name.exe"
  # A still-running instance file-locks $dst, so the copy would otherwise fail. Stop any
  # instance that (re)started during the multi-minute build, give Windows a moment to release
  # the handle, then copy and VERIFY it actually landed — never silently ship a stale exe.
  Get-Process $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 500
  try { Copy-Item -Force $src $dst -ErrorAction Stop }
  catch { throw "${name}: could not overwrite '$dst' (is an instance still running / file locked?): $_" }
  if ((Get-Item $dst).Length -ne (Get-Item $src).Length) {
    throw "${name}: copy did not update '$dst' (size mismatch) - stale exe still in place."
  }
  Write-Host "Built $name.exe -> PaintAllocationDashboard\ ($((Get-Item $dst).LastWriteTime))"
}

# Planner dashboard. Bundles the vendored engine automatically (it is imported as a normal
# package now — no --paths needed). Excel-engine bundling: pandas reads .xlsx via
# engine="calamine", a lazy string-triggered import PyInstaller's static analysis can miss
# (→ "Missing optional dependency 'python-calamine'"); collect it explicitly.
Build-Exe "PaintAllocationDashboard" "PaintAllocationDashboard\paint_allocation_dashboard.py" `
  @('--collect-all', 'python_calamine', '--hidden-import', 'pandas.io.excel._calamine')

# Floor viewers: pipeline-free, stdlib-only (the runlists viewer path never imports pandas /
# the engine), so no special collection flags — the exes stay tiny.
Build-Exe "PaintRunlistPC" "PaintAllocationDashboard\runlist_pc.py" @()
Build-Exe "PaintRunlistEC" "PaintAllocationDashboard\runlist_ec.py" @()

Write-Host "All Paint dashboard/runlist exes built."