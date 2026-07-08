# Talkin to PLEX Code
## How Moddy communicates with Plex (cloud.plex.com)

This document explains everything Claude needs to know to write code that talks to Plex
the same way the Moddy proxy server does. This is the proven, working approach.

---

## The Big Picture

Plex is a cloud ERP at cloud.plex.com. It does NOT have a public API — it uses the
same web session that a human uses in a browser. Every data call is a POST request
that pretends to be an AJAX call from the Plex web UI.

Two things are required to make any call:
1. Session cookies — captured from an active browser session
2. ASID — the account session ID embedded in every Plex URL (?__asid=...)

---

## Step 1 — Get the Session Cookie

Plex uses HTTP-only cookies, so JavaScript in the page can't read them. The only way
to get them without a password is via the Chrome DevTools Protocol (CDP).

The process:
1. Open Edge (or Chrome) with remote debugging enabled on port 9235:
   msedge.exe --remote-debugging-port=9235 --user-data-dir=C:\Temp\plex-session
2. Have the user sign in to Plex in that browser window.
3. From PowerShell, connect to CDP and call Storage.getCookies:

```powershell
function Invoke-CDPCommand($wsUrl, $id, $method, $paramsJson) {
    $ws = New-Object System.Net.WebSockets.ClientWebSocket
    $cts = New-Object System.Threading.CancellationTokenSource
    $ws.ConnectAsync([Uri]$wsUrl, $cts.Token).Wait()
    $msg = [System.Text.Encoding]::UTF8.GetBytes("{`"id`":$id,`"method`":`"$method`",`"params`":$paramsJson}")
    $ws.SendAsync($msg, 'Text', $true, $cts.Token).Wait()
    $buf = New-Object byte[] 131072
    $seg = New-Object ArraySegment[byte] $buf
    $res = $ws.ReceiveAsync($seg, $cts.Token).Result
    $ws.CloseAsync('NormalClosure', '', $cts.Token).Wait()
    return [System.Text.Encoding]::UTF8.GetString($buf, 0, $res.Count) | ConvertFrom-Json
}

function Get-PlexCookiesViaCDP {
    $port = 9235
    $allCookies = $null

    # Try Storage.getCookies on the browser root first
    $ver = Invoke-WebRequest -Uri "http://127.0.0.1:$port/json/version" -UseBasicParsing -TimeoutSec 2 | ConvertFrom-Json
    if ($ver.webSocketDebuggerUrl) {
        $resp = Invoke-CDPCommand $ver.webSocketDebuggerUrl 1 'Storage.getCookies' '{}'
        if ($resp.result.cookies) { $allCookies = $resp.result.cookies }
    }

    # Fallback: enumerate tabs and call Network.getAllCookies
    if (-not $allCookies) {
        $tabs = (Invoke-WebRequest "http://127.0.0.1:$port/json/list" -UseBasicParsing).Content | ConvertFrom-Json
        foreach ($tab in $tabs | Where-Object { $_.type -eq 'page' -and $_.webSocketDebuggerUrl }) {
            $resp = Invoke-CDPCommand $tab.webSocketDebuggerUrl 1 'Network.getAllCookies' '{}'
            if ($resp.result.cookies.Count -gt 0) { $allCookies = $resp.result.cookies; break }
        }
    }

    # Get ASID from an open Plex tab URL
    $tabs2 = (Invoke-WebRequest "http://127.0.0.1:$port/json/list" -UseBasicParsing).Content | ConvertFrom-Json
    $plexTab = $tabs2 | Where-Object { $_.url -like '*plex.com*' } | Select-Object -First 1
    if ($plexTab -and $plexTab.url -match '__asid=([^&]+)') { $script:Asid = $Matches[1] }

    # Filter to Plex cookies only and join into Cookie header string
    $plexCookies = @($allCookies | Where-Object { $_.domain -like '*plex.com*' })
    return ($plexCookies | ForEach-Object { "$($_.name)=$($_.value)" }) -join '; '
}
```

The resulting cookie string is ~1130 characters long and contains the plex-auth-prod
cookie. Save it — sessions last 4-8 hours.

---

## Step 2 — Make a Plex API Call

Every Plex data search is a POST to a URL of this form:
  https://cloud.plex.com/{Module}/{Object}/Search?__asid={ASID}&limit=true&sourceActionKey={SAK}

The SAK (sourceActionKey) is a numeric ID for the search screen. Each Plex page has
its own SAK. See the SAK table below.

```powershell
function Invoke-PlexPost($url, $bodyJson, [int]$TimeoutMs = 30000, [string]$Referer = '', [string]$CookieString = '') {
    $req             = [System.Net.HttpWebRequest]::Create($url)
    $req.Method      = 'POST'
    $req.ContentType = 'application/json; charset=UTF-8'
    $req.Timeout     = $TimeoutMs
    $req.Accept      = 'application/json, text/javascript, */*; q=0.01'
    $req.UserAgent   = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0'
    $req.Referer     = if ($Referer) { $Referer } else { 'https://cloud.plex.com/' }
    $req.Headers.Add('X-Requested-With',              'XMLHttpRequest')
    $req.Headers.Add('Accept-Language',               'en-US,en;q=0.9')
    $req.Headers.Add('Origin',                        'https://cloud.plex.com')
    $req.Headers.Add('Plex-Cookie-Verification-Token', '')
    $req.Headers.Add('Plex-Form-Verification-Token',   '')
    $req.Headers.Add('Cookie',                         $CookieString)

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($bodyJson)
    $req.ContentLength = $bytes.Length
    $rs = $req.GetRequestStream(); $rs.Write($bytes, 0, $bytes.Length); $rs.Close()

    $resp   = $req.GetResponse()
    $rdr    = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
    $result = $rdr.ReadToEnd()
    $rdr.Close(); $resp.Close()
    return $result
}
```

Response rows are at response.Data.Rows or response.Rows (try Data.Rows first):
```powershell
$parsed = $json | ConvertFrom-Json
$rows = if ($parsed.Data -and $parsed.Data.Rows) { $parsed.Data.Rows } else { $parsed.Rows }
```

---

## SAK Reference Table (Modineer Plant 10, PCN 327667)

SAK    | What it queries
-------|------------------------------------------------------------------
4404   | SalesAndCRM / SalesReleases / ReleaseSearch
4843   | Costing / PartCost
4887   | Engineering / PartRouting
9580   | Inventory / Container / Search
13303  | Inventory / ContainerHistory / Search
13582  | Engineering / PartWhereUsed / Search
18690  | ProductionTracking / ProductionHistory / Search
20815  | Engineering / WhereUsed (alternate)
3994   | ProductionManagement / JobDispatch / Search
765    | ProductionTracking / ProductionStatus Search

PCN = 327667 — always include in the POST body JSON when Plex requires it.

---

## Example: Query Sales Releases (SAK 4404)

```powershell
$asid    = "YOUR_ASID_HERE"     # from CDP tab URL
$cookies = "YOUR_COOKIE_STRING" # ~1130 chars from Get-PlexCookiesViaCDP
$sak     = 4404

$url     = "https://cloud.plex.com/SalesAndCRM/SalesReleases/ReleaseSearch?__asid=$asid&limit=true&sourceActionKey=$sak"
$body    = '{"Search":false,"PCN":327667,"Status":"Released"}'
$referer = "https://cloud.plex.com/SalesAndCRM/SalesReleases?__asid=$asid"

$json = Invoke-PlexPost $url $body 30000 $referer $cookies
$rows = ($json | ConvertFrom-Json).Data.Rows
```

---

## Example: Query WIP Containers (SAK 9580)

```powershell
$sak     = 9580
$url     = "https://cloud.plex.com/Inventory/Container/Search?__asid=$asid&limit=true&sourceActionKey=$sak"
$referer = "https://cloud.plex.com/Inventory/Container?__asid=$asid"
# Plex supports SQL LIKE wildcards — %wld matches any location containing "wld"
$body    = '{"Search":false,"FromPartMenu":false,"GroupBy":"PartNo","Active":true,"Location":"%wld","PCN":327667}'

$json = Invoke-PlexPost $url $body 30000 $referer $cookies
$rows = ($json | ConvertFrom-Json).Data.Rows
```

---

## Saving and Loading Sessions

```powershell
# Save
@{ Cookies = $cookieString; Asid = $asid } | ConvertTo-Json | Set-Content "plex-session.json"

# Load
$session = Get-Content "plex-session.json" | ConvertFrom-Json
$cookies = $session.Cookies
$asid    = $session.Asid
```

Sessions expire after ~4-8 hours. When Plex returns an HTML login page instead of JSON,
re-run Get-PlexCookiesViaCDP with the browser open.

---

## How to Discover a New SAK

If you need a Plex page not in the table above:
1. Open Edge with remote-debugging-port=9235
2. Navigate to the Plex page and trigger a search
3. Use CDP Network.enable + Network.requestWillBeSent to intercept XHR traffic
4. Find a request URL matching sourceActionKey=(\d+) — that number is the SAK
5. Copy the POST body from the same request as a template

---

## Key Rules

- Always POST, never GET — even for reads.
- Always include X-Requested-With: XMLHttpRequest or Plex returns HTML.
- Plex-Cookie-Verification-Token and Plex-Form-Verification-Token must be present (empty string is fine).
- ASID goes in the URL query string, not the POST body.
- PCN goes in the POST body JSON.
- Filter results client-side — Plex returns broad sets, narrow them yourself.
