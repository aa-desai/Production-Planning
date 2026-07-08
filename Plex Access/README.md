# Moddy's Brain — Plex + Claude Code

This is **Moddy** — the Plex-fluent Claude Code assistant. This package is Moddy's brain:
everything Claude Code needs to talk to **Plex** (cloud.plex.com), answer questions about your
Plex data, and run the automated **MRP buyer system** that reads demand and places clean firm
purchase-order releases.

Plex has **no public API**. It uses the same web session a human uses in a browser. This
package gives Claude Code (1) the *knowledge* of how Plex's internal calls work, (2) the
*method* to authenticate using your own logged-in session, and (3) a working *MRP buyer system*.

Drop this on any machine, capture your Plex session, and your Claude Code becomes Moddy.

---

## What's in here

| Folder | What it is |
|---|---|
| `memory/` | The deep, hard-won knowledge — how to read/write MRP releases, the connection foundation, part mappings, buyer rules. **This is the brain.** Drop these into your Claude Code project so they load every session. |
| `mrp-system/` | **Moddy's automated MRP buyer** — reads MRP, cancels over-ordering, places clean firm releases to demand. See `mrp-system/README-MRP-SYSTEM.md`. |
| `knowledge/` | `talkin-to-PLEX-code.md` (step-by-step: cookies, ASID, making calls) and `plex-knowledge.json` (SAKs, endpoints, field mappings). |
| `scripts/` | `save-plex-credentials.ps1` (capture your Plex session), `cdp-lib.ps1` (reusable CDP/WebSocket helpers), `proxy-server.ps1` (optional local proxy for dashboards). |
| `CLAUDE.md` | Drop-in project instructions so Claude Code auto-loads Moddy's brain. |

---

## Setup (one time, ~5 minutes)

### 1. Put the brain where Claude Code will read it
Copy this whole folder somewhere on your machine, then either:
- **Simplest:** copy `CLAUDE.md` into the root of the project you'll run Claude Code in, and
  copy the `memory/*.md` files into that project's `.claude/.../memory/` folder (or just keep
  them next to CLAUDE.md — CLAUDE.md points Claude at them).

### 2. Capture your Plex session
Plex cookies are HTTP-only (JavaScript can't read them), so we grab them from a browser
via the Chrome DevTools Protocol. Run this in PowerShell:

```powershell
# a) Launch Edge with debugging on port 9235, sign in to Plex in the window that opens
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
    --remote-debugging-port=9235 --user-data-dir="$env:TEMP\plex-session" `
    "https://cloud.plex.com"

# b) After you're logged in and see your Plex home, run the capture:
powershell -ExecutionPolicy Bypass -File .\scripts\save-plex-credentials.ps1
```

This writes `plex-session.json` (your cookie string + ASID). That file is your key — treat it
like a password; it expires after a few hours, so re-run the capture when calls start failing
with **419/401/403**.

### 3. Ask Claude Code about Plex
Open Claude Code in your project and ask, e.g.:
- *"Pull my open MRP releases for supplier X and tell me what's over-ordered."*
- *"What SAK does the SPC checksheet search use?"*
- *"Read inventory for part 12345 at plant 10."*

Claude now knows how to build the calls (see `knowledge/`) and authenticate (your
`plex-session.json`).

---

## The core idea (for the curious)

Every Plex data call is a `POST` to a URL like:
```
https://cloud.plex.com/<Area>/<Screen>/<Action>?__asid=<ASID>&sourceActionKey=<SAK>
```
with headers `Cookie: <your session>`, `X-Requested-With: XMLHttpRequest`,
`Content-Type: application/json`, and a JSON body. The **ASID** identifies your session; the
**SAK** (sourceActionKey) identifies the screen's action. `knowledge/plex-knowledge.json`
lists the SAKs and endpoints already discovered.

To find a *new* SAK: open the screen in the debug browser (port 9235), do the action, and
watch the Network tab — the request URL contains the SAK.

---

## Safety rules (baked into the memory, read before writing anything)

- **Reads are safe. Writes create real records** (POs, releases) that suppliers see and act on.
- **Always snapshot before writing** — save the current state so you can restore.
- **Verify by reloading** — never trust a `"Success": true` response alone; re-read and check.
- **Test vs Production:** test.cloud.plex.com (`plex-auth-test` cookie) is a safe sandbox that
  refreshes from prod; cloud.plex.com (`plex-auth-prod`) is live. Same code, different session.

See `memory/feedback-plex-connection.md` and `memory/project-mrp-p6-releases.md` for the full,
battle-tested playbook.

---

*Built by Mason Waggoner's Claude Code. Share freely inside Modineer.*
