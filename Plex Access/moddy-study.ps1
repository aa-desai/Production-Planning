<#
=============================================================================
  MODDY STUDY LOOP — Autonomous Plex API Discovery & Learning System
  Version 2.0 | Modineer Group / Shareable
=============================================================================

HOW PLEX CLOUD API WORKS
─────────────────────────────────────────────────────────────────────────────
Plex uses three main API patterns. All require the same session cookies.

  PATTERN 1 — MetaDataSource (visual screen data, e.g. Actual Depletion):
    POST https://cloud.plex.com/api/MetaDataSource/{metaKey}
         ?limit=true&__asid={asid}&sourceActionKey={sak}
    Body: [{ "PCN": 327667, "WorkcenterKey": "...", "BeginDate": "...", ... }]
    Returns: { "Data": { "Rows": [...] } }
    ⚠ Requires VisionPlex to have been visited first in the browser session.
    ⚠ In PowerShell 7, NEVER write "$var?something" — the ? is treated as a
      null-conditional operator. ALWAYS use "${var}?something" syntax.
    ✓ Supports batching: pass array with multiple objects → summed result.

  PATTERN 2 — Production Tracking (structured history):
    POST https://cloud.plex.com/ProductionTracking/ProductionHistory/
         SearchProductionHistoryProductionByOperatorGrid
         ?__asid={asid}&sourceActionKey={sak}
    Body: { "PCN": 0, "StartDate": "...", "EndDate": "...", "WorkcenterGroups": "Laser" }
    Returns rows with: WorkcenterCode, Shift, ReportDate, ProductionValue, Employee

  PATTERN 3 — DataSources (inventory, containers, etc.):
    POST https://cloud.plex.com/api/datasources/{key}?__asid={asid}&sourceActionKey={sak}
    Body: [{ "PCN": 327667, ...filters... }]

AUTHENTICATION
─────────────────────────────────────────────────────────────────────────────
Plex uses HTTP-only session cookies (inaccessible to JavaScript).
Capture via Chrome DevTools Protocol (CDP):

  1. Launch Edge with --remote-debugging-port=9228
  2. User signs in at https://cloud.plex.com
  3. Navigate to VisionPlex: https://cloud.plex.com/VisionPlex/screen?__actionKey=7212
     (This primes the MetaDataSource session — without it, MetaDataSource returns 419)
  4. Wait ~8 seconds for VisionPlex JS to initialize
  5. Use CDP Storage.getCookies to capture ALL cookies
  6. Join as "name=value; name=value; ..." string
  7. Include as Cookie header in every Plex API request

  Key cookies: plex-auth-prod (main auth), apt.sid, apt.uid, idsrv, idsrv.session

KNOWN GOTCHAS
─────────────────────────────────────────────────────────────────────────────
  • MetaDataSource + 419 → VisionPlex not primed. Re-auth and prime first.
  • MetaDataSource + 500 → SAK+key combination invalid. Stop retrying.
  • PCN 0 vs PCN 327667 → some endpoints need PCN=0, others need plant PCN.
  • The __asid changes per browser navigation. Capture it from the URL.
  • Plex dates: ISO 8601 UTC. EDT = UTC-4 in summer. Shift boundaries matter.
  • ProductionValue in production history = PIECES, not lbs. Use
    MetaDataSource ActualDepletion for material weight.

LEARNING ALGORITHM
─────────────────────────────────────────────────────────────────────────────
Maintains plex-knowledge.json with:
  - endpoints: working APIs, their columns, sample params, call count
  - failedPatterns: { path, reason, http_code } — never retry these
  - discoveries: plain-text observations about data patterns and relationships

Error learning rules:
  419 → MetaDataSource needs VisionPlex priming. Flag; skip until re-auth.
  500 → SAK+key invalid. Add to failedPatterns.
  200 + empty rows → Endpoint valid but no data. Record as "sparse" note.
  200 + rows → Full success. Record path, columns, sampleParams, notes.
  New columns vs known → Merge column list; note the new fields.
=============================================================================
#>

param([int]$IntervalSec = 240)

$ScriptDir   = $PSScriptRoot
$KbFile      = "$ScriptDir\plex-knowledge.json"
$SessionFile = "$ScriptDir\plex-session.json"
$LogFile     = "$ScriptDir\study-log.txt"
$ConfigFile  = "$ScriptDir\study-config.json"

# ── Config (overrides defaults if config file exists) ────────────────────────
$cfg = @{ PCN=327667; UserPUN=15969610; CostModelKey=6103; PlantName='Plant 10'; MetaKey='uwWPN7SEaFxvTv3-QIrWsQ'; ApiKey='' }
if (Test-Path $ConfigFile) {
    try {
        $loaded = Get-Content $ConfigFile -Raw | ConvertFrom-Json
        foreach ($p in $loaded.PSObject.Properties) { $cfg[$p.Name] = $p.Value }
    } catch { Write-Host "[Study] Warning: could not load config file." -ForegroundColor Yellow }
}

# API key: config file > environment variable > error
if (-not $cfg.ApiKey) { $cfg.ApiKey = $env:ANTHROPIC_API_KEY }
if (-not $cfg.ApiKey) {
    Write-Host "[Study] ERROR: No API key. Set ApiKey in study-config.json or ANTHROPIC_API_KEY env var." -ForegroundColor Red
    exit 1
}

$PCN      = [int]$cfg.PCN
$UserPUN  = [int]$cfg.UserPUN
$MetaKey  = [string]$cfg.MetaKey
$ApiKey   = [string]$cfg.ApiKey

# ── Logging ──────────────────────────────────────────────────────────────────
function Write-Log([string]$msg, [string]$Color = 'DarkGray') {
    $line = "[$([DateTime]::Now.ToString('HH:mm:ss'))] $msg"
    Write-Host $line -ForegroundColor $Color
    try { Add-Content $LogFile $line -Encoding UTF8 } catch {}
}

# ── Session ──────────────────────────────────────────────────────────────────
function Load-Session {
    foreach ($sf in @($SessionFile, "$ScriptDir\pressbrake-session.json")) {
        if (-not (Test-Path $sf)) { continue }
        try {
            $s = Get-Content $sf -Raw | ConvertFrom-Json
            if ($s.Cookies) { return @{ cookies=[string]$s.Cookies; asid=[string]$s.Asid } }
        } catch {}
    }
    return @{ cookies=''; asid='' }
}

# ── Knowledge Base ───────────────────────────────────────────────────────────
function Load-Kb {
    $empty = @{
        endpoints      = [ordered]@{}
        failedPatterns = [System.Collections.Generic.List[hashtable]]::new()
        discoveries    = [System.Collections.Generic.List[string]]::new()
    }
    if (-not (Test-Path $KbFile)) { return $empty }
    try {
        $raw = Get-Content $KbFile -Raw | ConvertFrom-Json
        $ep  = [ordered]@{}
        if ($raw.endpoints) {
            foreach ($p in $raw.endpoints.PSObject.Properties) {
                $e = $p.Value
                $ep[$p.Name] = @{
                    description  = [string]$e.description
                    columns      = if ($e.columns)  { @($e.columns  | ForEach-Object { [string]$_ }) } else { @() }
                    sampleParams = $e.sampleParams
                    callCount    = [int]($e.callCount)
                    notes        = [string]$e.notes
                    lastSuccess  = [string]$e.lastSuccess
                }
            }
        }
        $fp   = [System.Collections.Generic.List[hashtable]]::new()
        if ($raw.failedPatterns) {
            foreach ($f in $raw.failedPatterns) {
                $fp.Add(@{ path=[string]$f.path; reason=[string]$f.reason; code=[int]$f.code })
            }
        }
        $disc = [System.Collections.Generic.List[string]]::new()
        if ($raw.discoveries) { foreach ($d in $raw.discoveries) { $disc.Add([string]$d) } }
        return @{ endpoints=$ep; failedPatterns=$fp; discoveries=$disc }
    } catch {
        Write-Log "KB load error: $_" 'Yellow'
        return $empty
    }
}

function Save-Kb([hashtable]$Kb) {
    try {
        # Endpoints
        $epLines = @()
        foreach ($k in $Kb.endpoints.Keys) {
            $e       = $Kb.endpoints[$k]
            $colsJ   = ($e.columns | ForEach-Object { '"' + ($_ -replace '"','\"') + '"' }) -join ','
            $paramsJ = if ($e.sampleParams) { try { $e.sampleParams | ConvertTo-Json -Compress -Depth 6 } catch { 'null' } } else { 'null' }
            $desc    = [string]($e.description) -replace '\\','\\' -replace '"','\"'
            $notes   = [string]($e.notes)       -replace '\\','\\' -replace '"','\"'
            $ls      = [string]($e.lastSuccess) -replace '"','\"'
            $kk      = $k -replace '\\','\\' -replace '"','\"'
            $epLines += "`"$kk`":{`"description`":`"$desc`",`"columns`":[$colsJ],`"sampleParams`":$paramsJ,`"callCount`":$($e.callCount),`"lastSuccess`":`"$ls`",`"notes`":`"$notes`"}"
        }
        # Failed patterns
        $fpLines = $Kb.failedPatterns | ForEach-Object {
            $p = ($_.path   -replace '\\','\\' -replace '"','\"')
            $r = ($_.reason -replace '\\','\\' -replace '"','\"')
            "{`"path`":`"$p`",`"reason`":`"$r`",`"code`":$($_.code)}"
        }
        $discLines = $Kb.discoveries | ForEach-Object { '"' + ($_ -replace '\\','\\' -replace '"','\"') + '"' }
        $json = "{`"endpoints`":{$($epLines -join ',')},`"failedPatterns`":[$($fpLines -join ',')],`"discoveries`":[$($discLines -join ',')]}"
        $json = [regex]::Replace($json, '[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ')
        [System.IO.File]::WriteAllText($KbFile, $json, [System.Text.Encoding]::UTF8)
    } catch { Write-Log "KB save error: $_" 'Yellow' }
}

function Is-FailedPattern([string]$path, [hashtable]$Kb) {
    return ($Kb.failedPatterns | Where-Object { $_.path -eq $path } | Measure-Object).Count -gt 0
}

function Add-FailedPattern([string]$path, [string]$reason, [int]$code, [hashtable]$Kb) {
    if (-not (Is-FailedPattern $path $Kb)) {
        $Kb.failedPatterns.Add(@{ path=$path; reason=$reason; code=$code })
        if ($Kb.failedPatterns.Count -gt 300) {
            $Kb.failedPatterns.RemoveRange(0, 100)
        }
    }
}

function Add-Discovery([string]$text, [hashtable]$Kb) {
    $prefix = $text.Substring(0, [Math]::Min(80, $text.Length))
    $dup    = $Kb.discoveries | Where-Object { $_.Length -ge 80 -and $_.Substring(0,80) -eq $prefix }
    if ($dup) { return $false }
    $trimmed = if ($text.Length -gt 300) { $text.Substring(0,297) + '...' } else { $text }
    $Kb.discoveries.Add($trimmed)
    if ($Kb.discoveries.Count -gt 30) { $Kb.discoveries.RemoveRange(0, 10) }
    return $true
}

function Format-KbSummary([hashtable]$Kb) {
    $lines = @()
    $lines += "=== PLEX KNOWLEDGE BASE: $($Kb.endpoints.Count) endpoints, $($Kb.failedPatterns.Count) known failures, $($Kb.discoveries.Count) observations ==="

    foreach ($k in $Kb.endpoints.Keys) {
        $e       = $Kb.endpoints[$k]
        $colStr  = if ($e.columns.Count -gt 0) { ($e.columns | Select-Object -First 8) -join ', ' } else { 'unknown' }
        if ($e.columns.Count -gt 8) { $colStr += " +$($e.columns.Count - 8) more" }
        $lines += "ENDPOINT: $k"
        $lines += "  desc: $($e.description) | calls: $($e.callCount) | last: $($e.lastSuccess)"
        $lines += "  cols: $colStr"
        if ($e.notes) { $lines += "  notes: $($e.notes)" }
    }

    if ($Kb.discoveries.Count -gt 0) {
        $lines += "OBSERVATIONS (last $([Math]::Min(8,$Kb.discoveries.Count))):"
        $Kb.discoveries | Select-Object -Last 8 | ForEach-Object { $lines += "  - $_" }
    }

    $recentFails = $Kb.failedPatterns | Select-Object -Last 5
    if ($recentFails) {
        $lines += "RECENT FAILURES:"
        foreach ($f in $recentFails) { $lines += "  HTTP $($f.code) — $($f.path) ($($f.reason))" }
    }

    return $lines -join "`n"
}

# ── Plex HTTP ────────────────────────────────────────────────────────────────
function Invoke-PlexCall([string]$Path, [object]$Body, [hashtable]$Session) {
    # Classify the error so the learning loop can react appropriately.
    # Returns: @{ json, statusCode, error, isEmpty }
    try {
        $asid = $Session.asid
        $fullUrl = if ($Path -match '^https://') { $Path } else { "https://cloud.plex.com/$($Path.TrimStart('/'))" }

        # Inject ASID if missing — use ${asid} not $asid? to avoid PS7 null-conditional parse
        if ($fullUrl -notmatch '__asid=') {
            $sep = if ($fullUrl -match '\?') { '&' } else { '?' }
            $fullUrl += "${sep}__asid=$([Uri]::EscapeDataString($asid))"
        }

        $bodyJson = if ($Body) {
            $j = $Body | ConvertTo-Json -Compress -Depth 10
            if ($j.TrimStart().StartsWith('{')) { "[$j]" } else { $j }
        } else { '{}' }

        $req             = [Net.HttpWebRequest]::Create($fullUrl)
        $req.Method      = 'POST'
        $req.ContentType = 'application/json; charset=UTF-8'
        $req.Timeout     = 30000
        $req.Accept      = 'application/json, text/javascript, */*; q=0.01'
        $req.UserAgent   = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0'
        $req.Referer     = 'https://cloud.plex.com/'
        $req.Headers.Add('X-Requested-With', 'XMLHttpRequest')
        $req.Headers.Add('Accept-Language',  'en-US,en;q=0.9')
        $req.Headers.Add('Cookie',           $Session.cookies)

        $bytes = [Text.Encoding]::UTF8.GetBytes($bodyJson)
        $req.ContentLength = $bytes.Length
        $rs = $req.GetRequestStream(); $rs.Write($bytes, 0, $bytes.Length); $rs.Close()

        $resp = $req.GetResponse()
        $rdr  = New-Object IO.StreamReader($resp.GetResponseStream(), [Text.Encoding]::UTF8)
        $json = $rdr.ReadToEnd(); $rdr.Close(); $resp.Close()

        # Detect empty result
        $isEmpty = ($json -match '"Rows"\s*:\s*\[\s*\]' -or $json -eq '{}' -or $json -eq '[]' -or $json.Length -lt 20)

        if ($json.Length -gt 8000) { $json = $json.Substring(0, 8000) + '... [truncated]' }
        return @{ json=$json; statusCode=200; error=''; isEmpty=$isEmpty }

    } catch [Net.WebException] {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        $body = ''
        if ($_.Exception.Response) {
            try {
                $er = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream(), [Text.Encoding]::UTF8)
                $body = $er.ReadToEnd().Substring(0, [Math]::Min(200, $er.ReadToEnd().Length)); $er.Close()
            } catch {}
        }
        $reason = switch ($code) {
            419 { 'Authentication timeout — MetaDataSource needs VisionPlex session prime' }
            500 { 'Server error — SAK+key combination likely invalid' }
            403 { 'Forbidden — check PCN or permissions' }
            404 { 'Not found — endpoint pattern does not exist at this plant' }
            default { "HTTP $code" }
        }
        return @{ json=''; statusCode=$code; error=$reason; isEmpty=$true }
    } catch {
        return @{ json=''; statusCode=0; error=$_.Exception.Message; isEmpty=$true }
    }
}

# ── Extract columns from raw JSON ─────────────────────────────────────────────
function Extract-Columns([string]$json) {
    $m = [regex]::Match($json, '"Rows"\s*:\s*\[\s*\{([^}]{1,4000})\}')
    if (-not $m.Success) { return @() }
    return @([regex]::Matches($m.Groups[1].Value, '"(\w+)"\s*:') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
}

# ── Claude API (tool-use loop) ────────────────────────────────────────────────
$ToolsJson = @'
[
  {
    "name": "plex_query",
    "description": "Query the Plex Cloud API. Use the three patterns described in the system prompt. For MetaDataSource, body is auto-wrapped in array if it's a single object. Always try the known endpoints first, then explore.",
    "input_schema": {
      "type": "object",
      "properties": {
        "description": { "type": "string", "description": "What you expect this query to return" },
        "path": { "type": "string", "description": "Full URL or path after cloud.plex.com/" },
        "body": { "type": "object", "description": "Request body (will be JSON-encoded)" },
        "referer": { "type": "string", "description": "Optional Referer header for VisionPlex endpoints" }
      },
      "required": ["description", "path"]
    }
  },
  {
    "name": "plex_learn",
    "description": "Save a discovered endpoint or observation to the knowledge base. Call after every successful query and whenever you learn something non-obvious.",
    "input_schema": {
      "type": "object",
      "properties": {
        "path":        { "type": "string" },
        "description": { "type": "string" },
        "columns":     { "type": "array", "items": { "type": "string" } },
        "sampleParams":{ "type": "object" },
        "notes":       { "type": "string", "description": "Quirks, required params, data quality notes" },
        "discovery":   { "type": "string", "description": "New factual observation about Plex data (not already in KB)" }
      }
    }
  },
  {
    "name": "plex_flag_failure",
    "description": "Record a path that definitively does not work, so it is never retried. Use when you get 500 (invalid SAK+key) or 404 (endpoint does not exist).",
    "input_schema": {
      "type": "object",
      "properties": {
        "path":   { "type": "string" },
        "reason": { "type": "string" },
        "code":   { "type": "integer" }
      },
      "required": ["path", "reason", "code"]
    }
  }
]
'@

function ConvertTo-MsgJson([array]$Messages) {
    $parts = @()
    foreach ($m in $Messages) {
        $roleJson = $m.role | ConvertTo-Json -Compress
        $contentRaw = $m.content
        if ($contentRaw -is [string]) {
            $contentJson = $contentRaw | ConvertTo-Json -Compress
        } elseif ($contentRaw -is [System.Array] -or $contentRaw -is [System.Collections.IList]) {
            $items = @()
            foreach ($blk in $contentRaw) { try { $items += ($blk | ConvertTo-Json -Compress -Depth 15) } catch {} }
            $contentJson = '[' + ($items -join ',') + ']'
        } else {
            try { $contentJson = $contentRaw | ConvertTo-Json -Compress -Depth 15 } catch { $contentJson = '""' }
        }
        $parts += "{`"role`":$roleJson,`"content`":$contentJson}"
    }
    return '[' + ($parts -join ',') + ']'
}

function Invoke-Claude([array]$Messages, [string]$SystemPrompt) {
    $sysJson  = $SystemPrompt | ConvertTo-Json -Compress
    $msgsJson = ConvertTo-MsgJson $Messages
    $reqBody  = "{`"model`":`"claude-haiku-4-5-20251001`",`"max_tokens`":1024,`"tools`":$ToolsJson,`"system`":$sysJson,`"messages`":$msgsJson}"
    $bBytes   = [Text.Encoding]::UTF8.GetBytes($reqBody)

    $req             = [Net.HttpWebRequest]::Create('https://api.anthropic.com/v1/messages')
    $req.Method      = 'POST'
    $req.ContentType = 'application/json'
    $req.Timeout     = 90000
    $req.Headers.Add('x-api-key',         $ApiKey)
    $req.Headers.Add('anthropic-version', '2023-06-01')
    $req.ContentLength = $bBytes.Length
    $ws = $req.GetRequestStream(); $ws.Write($bBytes, 0, $bBytes.Length); $ws.Close()

    try {
        $resp = $req.GetResponse()
        $rdr  = New-Object IO.StreamReader($resp.GetResponseStream(), [Text.Encoding]::UTF8)
        $raw  = $rdr.ReadToEnd(); $rdr.Close(); $resp.Close()
        return $raw | ConvertFrom-Json
    } catch [Net.WebException] {
        $sc = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        $detail = ''
        try {
            $er = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream(), [Text.Encoding]::UTF8)
            $detail = $er.ReadToEnd(); $er.Close()
        } catch {}
        throw "Claude HTTP ${sc}: $detail"
    }
}

# ── Scenarios ────────────────────────────────────────────────────────────────
# Discovery: probe new SAK ranges on the known MetaDataSource key
$DiscoveryScenarios = @(
    @{ name='MetaData SAK 1000-5000';    prompt='Try SAKs 1000,1500,2000,2500,3000,3500,4000,4500,5000 on the MetaDataSource key. Body: {PCN,WorkcenterGroups:""}. Save successes immediately via plex_learn. Flag failures via plex_flag_failure.' }
    @{ name='MetaData SAK 5001-10000';   prompt='Try SAKs 5500,6000,6500,7000,7500,8000,8500,9000,9500,10000 on the MetaDataSource key. Body: {PCN}. Save successes, flag definitive failures.' }
    @{ name='MetaData SAK 10001-15000';  prompt='Try SAKs 10500,11000,11500,12000,12500,13000,13500,14000,14500,15000 on MetaDataSource key. Body: {PCN}. Save successes.' }
    @{ name='MetaData SAK 15001-20000';  prompt='Try SAKs 15500,16000,16500,17000,17500,18000,18500,19000,19500,20000 on MetaDataSource key. Body: {PCN}. Save successes.' }
    @{ name='MetaData SAK 20001-25000';  prompt='Try SAKs 20500,21000,21500,22000,22500,23000,23500,24000,24500,25000 on MetaDataSource key. Body: {PCN}. Save successes.' }
    @{ name='MetaData SAK 25001-30000';  prompt='Try SAKs 25500,26000,27000,28000,29000,30000 on MetaDataSource key. Body: {PCN}. Save successes.' }
    @{ name='Production History Explore';prompt='Query production history SAK 18690 with WorkcenterGroups set to: "Laser", "Pressbrake", "Weld", "Assembly", "Paint" one at a time. Record which groups return data and what fields come back.' }
    @{ name='Container Inventory Probe'; prompt='Query datasource endpoints for containers using SAKs near 4404 (known container SAK). Try 4400-4410, 4300-4320, 4500-4520. Body: {PCN, Container_Status:"OK"}. Record working SAKs and their columns.' }
    @{ name='Sales Release Probe';       prompt='Probe for sales release endpoints. Try datasource SAKs 9575-9590 and MetaDataSource SAKs 9575-9590. Body: {PCN}. Record any that return release/demand data.' }
    @{ name='Part Routing Probe';        prompt='Probe for part routing endpoints near SAK 13582 (known routing SAK). Try 13570-13600. Also try MetaDataSource with these SAKs. Body: {PCN, PartNo:""}. Record working ones.' }
    @{ name='Alt MetaData Keys';         prompt='The known MetaDataSource base key is stored in the config. Try to discover alternate keys by probing paths: /api/MetaDataSource/inventory, /api/MetaDataSource/production, /api/MetaDataSource/quality. Also try calling /api/MetaDataSource with no key to see if a list is returned.' }
    @{ name='Workcenter Status Probe';   prompt='Probe for workcenter status endpoints (SAKs 760-770). Body: {PCN, DeptNo:40193}. These should return machine/workcenter status. Record columns.' }
)

# Analysis: extract plant insights from known good data
$AnalysisScenarios = @(
    @{ name='Production Trend Analysis'; cooldown=20; prompt='Query production history for the current month with WorkcenterGroups="Laser". Rank workcenters by total pieces produced. What are the most and least active? What does shift distribution look like? Record as discovery.' }
    @{ name='Container Status Map';      cooldown=20; prompt='Query container data (SAK 4404 or similar if known). List all distinct Container_Status values and counts. What is the most common status? Record the taxonomy.' }
    @{ name='Part Volume Leaders';       cooldown=20; prompt='Query production history for the past 30 days with WorkcenterGroups="Pressbrake". Which parts (PartNo) have the highest piece counts? List top 10. Record as discovery.' }
    @{ name='Shift Utilization Check';   cooldown=20; prompt='Query production history for the current month. Compare shift 1 vs shift 2 totals across all workcenter groups. Which shifts are more productive? Record findings.' }
    @{ name='Operator Performance';      cooldown=30; prompt='Query production history for the past 14 days. Rank operators by total pieces. Flag any operator who appears on both high and low productivity days — that variation is worth noting. Record as discovery.' }
)

$script:RunAt = @{}

function Pick-NextScenario([int]$idx, [hashtable]$Kb) {
    # Prefer unrun discovery first
    $unrun = $DiscoveryScenarios | Where-Object { -not $script:RunAt.ContainsKey($_.name) } | Select-Object -First 1
    if ($unrun) { return $unrun }

    # Every 4th session run analysis if eligible
    if ($idx % 4 -eq 0) {
        $eligible = $AnalysisScenarios | Where-Object {
            $lastRun = if ($script:RunAt.ContainsKey($_.name)) { $script:RunAt[$_.name] } else { -999 }
            ($idx - $lastRun) -ge $_.cooldown
        } | Sort-Object { if ($script:RunAt.ContainsKey($_.name)) { $script:RunAt[$_.name] } else { -999 } } | Select-Object -First 1
        if ($eligible) { return $eligible }
    }

    # Cycle through discovery scenarios (least-recently-run first)
    return $DiscoveryScenarios | Sort-Object {
        if ($script:RunAt.ContainsKey($_.name)) { $script:RunAt[$_.name] } else { -999 }
    } | Select-Object -First 1
}

# ── Main Loop ─────────────────────────────────────────────────────────────────
Write-Log "=== Moddy Study Loop v2.0 | PCN=${PCN} | $($DiscoveryScenarios.Count) discovery + $($AnalysisScenarios.Count) analysis scenarios ===" 'Cyan'
Write-Log "KB file: $KbFile" 'DarkGray'

$PauseFile  = "$ScriptDir\study-paused.txt"
$sessionIdx = 0

while ($true) {
    try {
        if (Test-Path $PauseFile) {
            Write-Log '[paused] Waiting for resume (delete study-paused.txt to continue)...' 'DarkYellow'
            Start-Sleep -Seconds 15; continue
        }

        # Yield while user is active (avoids rate-limit contention with chat)
        $activeFile = "$ScriptDir\user-active.txt"
        if (Test-Path $activeFile) {
            try {
                $lastActive = [DateTime]::Parse((Get-Content $activeFile -Raw).Trim())
                $secSince   = ([DateTime]::Now - $lastActive).TotalSeconds
                if ($secSince -lt 180) {
                    Write-Log "  [yield] User active — waiting for quiet window..." 'DarkYellow'
                    Start-Sleep -Seconds ([Math]::Min(180 - $secSince, 30)); continue
                }
            } catch {}
        }

        $session = Load-Session
        if (-not $session.cookies) {
            Write-Log 'No Plex session. Sign in via a Moddy dashboard and ensure plex-session.json is present.' 'Yellow'
            Start-Sleep -Seconds 60; continue
        }

        $kb       = Load-Kb
        $kbText   = Format-KbSummary $kb
        $scenario = Pick-NextScenario $sessionIdx $kb
        $script:RunAt[$scenario.name] = $sessionIdx
        $sessionIdx++

        Write-Log "--- Session ${sessionIdx}: $($scenario.name) ---" 'Cyan'

        $today       = [DateTime]::Now
        $monthStart  = $today.ToString('yyyy-MM-01T00:00:00.000Z')
        $last30Start = $today.AddDays(-30).ToString('yyyy-MM-ddT00:00:00.000Z')
        $todayEnd    = $today.ToString('yyyy-MM-ddT23:59:59.999Z')

        $systemPrompt = @"
You are an autonomous Plex API explorer for ${($cfg.PlantName)} (PCN=${PCN}).
Your mission: discover every accessible Plex data source and build a complete knowledge base.

HOW PLEX API WORKS:
1. MetaDataSource (visual screen data): POST to /api/MetaDataSource/${MetaKey}?limit=true&__asid=ASID&sourceActionKey=SAK
   Body: [{"PCN":${PCN}, ...filter fields...}]
   Returns: {"Data":{"Rows":[...]}} — each row is a record from that screen.

2. Production History: POST to /ProductionTracking/ProductionHistory/SearchProductionHistoryProductionByOperatorGrid?__asid=ASID&sourceActionKey=18690
   Body: {"PCN":0,"StartDate":"...","EndDate":"...","WorkcenterGroups":"Laser"}
   Returns rows: WorkcenterCode, Shift, ReportDate, ProductionValue (pieces), Employee

3. DataSources: POST to /api/datasources/KEY?__asid=ASID&sourceActionKey=SAK
   Body: [{"PCN":${PCN}, ...}]

CURRENT KB ($($kb.endpoints.Count) endpoints, $($kb.failedPatterns.Count) known failures):
${kbText}

DATE REFS: currentMonth=${monthStart} to ${todayEnd} | last30days=${last30Start} to ${todayEnd}

STUDY TASK: $($scenario.prompt)

RULES:
- After EVERY successful query, immediately call plex_learn with path, description, columns, sampleParams, notes.
- After EVERY 500 or 404, call plex_flag_failure so we never retry that combination.
- 419 means MetaDataSource needs VisionPlex session — don't retry, just note it and try other SAKs.
- Empty rows (200 but Rows:[]) = valid endpoint, no data for these params. Still call plex_learn with a "sparse" note.
- Skip any path already in failedPatterns.
- Only call plex_learn for NEW facts not already in the KB.
- Be methodical: try 2-3 variants per approach, then move on.
"@

        $messages = @(@{ role='user'; content="Begin study session: $($scenario.name). $($scenario.prompt)" })
        $depth    = 0; $maxDepth = 12

        while ($depth -lt $maxDepth) {
            try {
                $cr    = Invoke-Claude -Messages $messages -SystemPrompt $systemPrompt
                $texts = @($cr.content | Where-Object { $_.type -eq 'text' })
                $tools = @($cr.content | Where-Object { $_.type -eq 'tool_use' })

                if ($texts.Count) {
                    $t = ($texts | ForEach-Object { $_.text }) -join ' '
                    Write-Log "  Moddy: $($t.Substring(0,[Math]::Min(220,$t.Length)))"
                }

                if ($cr.stop_reason -eq 'end_turn' -or -not $tools.Count) {
                    Write-Log '  Session complete.' 'DarkGreen'; break
                }

                $messages   += @{ role='assistant'; content=@($cr.content) }
                $toolResults = [System.Collections.Generic.List[hashtable]]::new()

                foreach ($tool in $tools) {
                    $result = ''

                    switch ($tool.name) {

                        'plex_query' {
                            Write-Log "  plex_query: $($tool.input.description)" 'DarkCyan'
                            $path    = [string]$tool.input.path
                            $qResult = Invoke-PlexCall -Path $path -Body $tool.input.body -Session $session

                            if ($qResult.statusCode -eq 200) {
                                $cols = Extract-Columns $qResult.json
                                $cleanPath = $path -replace '[\?&]__asid=[^&]*', '' -replace '[\?&]$', ''

                                if (-not $kb.endpoints.ContainsKey($cleanPath)) {
                                    $kb.endpoints[$cleanPath] = @{
                                        description = "Auto-discovered ($($scenario.name))"
                                        columns     = $cols
                                        sampleParams= $tool.input.body
                                        callCount   = 1
                                        lastSuccess = [DateTime]::Now.ToString('yyyy-MM-dd')
                                        notes       = if ($qResult.isEmpty) { 'Returns empty rows for this param set' } else { '' }
                                    }
                                    Write-Log "  Auto-learned: $cleanPath ($($cols.Count) cols)" 'Green'
                                } else {
                                    $ep = $kb.endpoints[$cleanPath]
                                    $ep.callCount++
                                    $ep.lastSuccess = [DateTime]::Now.ToString('yyyy-MM-dd')
                                    # Merge new columns
                                    if ($cols.Count -gt $ep.columns.Count) {
                                        $newCols = $cols | Where-Object { $ep.columns -notcontains $_ }
                                        if ($newCols) {
                                            $ep.columns += $newCols
                                            Write-Log "  Merged $($newCols.Count) new columns into $cleanPath" 'DarkGreen'
                                        }
                                    }
                                }
                                Save-Kb $kb
                                $result = if ($qResult.isEmpty) { 'HTTP 200 — valid endpoint but empty rows for these params' } else { $qResult.json }

                            } else {
                                # Learn from failure
                                $code = $qResult.statusCode
                                if ($code -eq 500 -or $code -eq 404) {
                                    Add-FailedPattern $path $qResult.error $code $kb
                                    Save-Kb $kb
                                }
                                $result = "ERROR $code — $($qResult.error)"
                                Write-Log "  HTTP ${code}: $($qResult.error)" 'DarkYellow'
                            }
                        }

                        'plex_learn' {
                            $lPath = if ($tool.input.path)        { [string]$tool.input.path }        else { '' }
                            $lDesc = if ($tool.input.description) { [string]$tool.input.description } else { '' }
                            $lCols = if ($tool.input.columns)     { @($tool.input.columns | ForEach-Object { [string]$_ }) } else { @() }
                            $lNote = if ($tool.input.notes)       { [string]$tool.input.notes }       else { '' }
                            $lDisc = if ($tool.input.discovery)   { [string]$tool.input.discovery }   else { '' }
                            $lPrms = $tool.input.sampleParams

                            if ($lPath) {
                                $cleanPath = $lPath -replace '[\?&]__asid=[^&]*', '' -replace '[\?&]$', ''
                                if ($kb.endpoints.ContainsKey($cleanPath)) {
                                    $ep = $kb.endpoints[$cleanPath]
                                    if ($lDesc) { $ep.description = $lDesc }
                                    if ($lNote) { $ep.notes       = $lNote }
                                    if ($lCols.Count -gt 0) {
                                        $newCols = $lCols | Where-Object { $ep.columns -notcontains $_ }
                                        $ep.columns += $newCols
                                    }
                                    if ($lPrms) { $ep.sampleParams = $lPrms }
                                } else {
                                    $kb.endpoints[$cleanPath] = @{
                                        description = $lDesc
                                        columns     = $lCols
                                        sampleParams= $lPrms
                                        callCount   = 0
                                        lastSuccess = [DateTime]::Now.ToString('yyyy-MM-dd')
                                        notes       = $lNote
                                    }
                                    Write-Log "  plex_learn: new endpoint → $cleanPath" 'Green'
                                }
                            }
                            if ($lDisc) {
                                $added = Add-Discovery $lDisc $kb
                                if ($added) { Write-Log "  plex_learn: obs → $($lDisc.Substring(0,[Math]::Min(100,$lDisc.Length)))" 'DarkGreen' }
                                else        { Write-Log '  plex_learn: obs skipped (duplicate)' 'DarkGray' }
                            }
                            Save-Kb $kb
                            $result = "Saved. KB: $($kb.endpoints.Count) endpoints, $($kb.discoveries.Count) observations."
                        }

                        'plex_flag_failure' {
                            $fp   = [string]$tool.input.path
                            $fr   = [string]$tool.input.reason
                            $fc   = [int]$tool.input.code
                            Add-FailedPattern $fp $fr $fc $kb
                            Save-Kb $kb
                            Write-Log "  plex_flag_failure: $fp ($fr)" 'DarkYellow'
                            $result = "Flagged. $($kb.failedPatterns.Count) total failures recorded."
                        }
                    }

                    $toolResults.Add(@{ type='tool_result'; tool_use_id=[string]$tool.id; content=[string]$result })
                }

                $messages += @{ role='user'; content=$toolResults.ToArray() }
                $depth++

                # Trim conversation to avoid token accumulation
                if ($messages.Count -gt 9) {
                    $messages = @($messages[0]) + ($messages | Select-Object -Last 6)
                }

                if (Test-Path $PauseFile) { Write-Log '  [paused mid-session]' 'DarkYellow'; break }

                Start-Sleep -Seconds 30  # ~2 Claude calls/min — stays under rate limits

            } catch {
                Write-Log "  Depth error: $_" 'Red'; break
            }
        }

        Write-Log "Session ${sessionIdx} done. KB: $($kb.endpoints.Count) endpoints, $($kb.failedPatterns.Count) failures | sleeping ${IntervalSec}s" 'DarkGray'

    } catch {
        Write-Log "Outer loop error: $_" 'Red'
    }

    Start-Sleep -Seconds $IntervalSec
}
