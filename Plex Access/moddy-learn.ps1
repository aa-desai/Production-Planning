# moddy-learn.ps1  --  Moddy's continuous-learning CAPTURE loop.
# It does NOT reason (a script can't). It gathers real experience since the last run --
# errors from the proxy log + new session transcripts -- appends them to the journal, and
# raises a LEARN-NOW flag. Moddy (Claude Code) reads the flag at session start and distills
# durable lessons into her memory. Runs on a schedule so capture is always-on.

$ErrorActionPreference = 'SilentlyContinue'
$root      = "$env:LOCALAPPDATA\Moddy\learning"
$journal   = "$root\moddy-journal.jsonl"
$flag      = "$root\LEARN-NOW.md"
$watermark = "$root\.watermark.json"
$proxyLog  = "$env:TEMP\moddy-log.txt"
$transcripts = "$env:USERPROFILE\.claude\projects"
New-Item -ItemType Directory -Path $root -Force | Out-Null

# ---- load watermark (what we've already captured) ----
$wm = if (Test-Path $watermark) { Get-Content $watermark -Raw | ConvertFrom-Json } else { $null }
$lastLogLine = if ($wm) { [int]$wm.logLine } else { 0 }
$lastRun     = if ($wm -and $wm.lastRun) { [DateTime]$wm.lastRun } else { (Get-Date).AddDays(-7) }

$new = @()
function Add-Entry($type, $text, $src) {
    $rec = [ordered]@{ ts = (Get-Date).ToString('o'); type = $type; text = "$text"; src = "$src" }
    Add-Content -Path $journal -Value ($rec | ConvertTo-Json -Compress)
    $script:new += $rec
}

# ---- 1) new error/warning lines from the proxy log ----
if (Test-Path $proxyLog) {
    $lines = Get-Content $proxyLog
    if ($lines.Count -gt $lastLogLine) {
        $fresh = $lines[$lastLogLine..($lines.Count-1)]
        foreach ($ln in $fresh) {
            if ($ln -match '(?i)\b(error|fail|failed|exception|denied|timeout|419|401|403|500|502|refused|unable|could not|invalid)\b') {
                Add-Entry 'proxy-issue' ($ln.Trim()) 'moddy-log.txt'
            }
        }
        $lastLogLine = $lines.Count
    }
}

# ---- 2) new Claude session transcripts (raw learning material) ----
if (Test-Path $transcripts) {
    $newSessions = Get-ChildItem $transcripts -Recurse -Filter *.jsonl -File |
                   Where-Object { $_.LastWriteTime -gt $lastRun }
    foreach ($s in $newSessions) {
        Add-Entry 'session' ("New session transcript to review: $($s.Name) ($([math]::Round($s.Length/1KB))KB, $($s.LastWriteTime.ToString('g')))") $s.FullName
    }
}

# ---- 3) raise the LEARN-NOW flag if there's fresh experience ----
if ($new.Count -gt 0) {
    $issues   = @($new | Where-Object { $_.type -eq 'proxy-issue' })
    $sessions = @($new | Where-Object { $_.type -eq 'session' })
    $md = @()
    $md += "# LEARN-NOW  --  new experience for Moddy to digest"
    $md += ""
    $md += "Captured $(Get-Date -f 'yyyy-MM-dd HH:mm'). Moddy: read this + the journal, extract"
    $md += "durable lessons (mistakes-to-avoid + new discoveries), append to your memory files in"
    $md += "the standard format, then DELETE this file. Don't duplicate what memory already holds."
    $md += ""
    $md += "## New proxy issues since last run: $($issues.Count)"
    foreach ($i in ($issues | Select-Object -First 40)) { $md += "- $($i.text)" }
    $md += ""
    $md += "## New session transcripts to mine for lessons: $($sessions.Count)"
    foreach ($s in $sessions) { $md += "- $($s.text)`n  -> $($s.src)" }
    $md += ""
    $md += "Journal: $journal"
    Set-Content -Path $flag -Value ($md -join "`r`n") -Encoding utf8
    Write-Host "moddy-learn: captured $($new.Count) new items ($($issues.Count) issues, $($sessions.Count) sessions). LEARN-NOW raised."
} else {
    Write-Host "moddy-learn: nothing new since last run."
}

# ---- save watermark ----
@{ logLine = $lastLogLine; lastRun = (Get-Date).ToString('o') } | ConvertTo-Json |
    Set-Content -Path $watermark -Encoding utf8
