"""
HTTP handler (read-only endpoints)
==================================
A tiny ``ThreadingHTTPServer`` request handler exposing the read-only surface:

* ``GET  /``          — the embedded UI with the queue payload inlined.
* ``GET  /snapshot``  — the current queue payload as JSON.
* ``GET  /detail``    — on-demand routing detail tree for a release.
* ``POST /refresh``   — re-run the pipeline and return the fresh payload.
* ``POST /rebuild-graph`` — force a daily-inputs rebuild, then re-allocate.

Runlist authoring (planner-side; design Part 2):
* ``GET  /runlist/draft.json`` — the planner's working draft (+ PC grouped for display).
* ``GET  /runlist/lock``       — current writer-lock owner + whether it's ours.
* ``POST /runlist/push``       — append selected containers to the draft (``{target, items}``).
* ``POST /runlist/publish``    — publish the draft to the shared live file (needs the lock).
"""

from __future__ import annotations

import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .payload import build_detail_tree
from .runlists import lock, push
from .runlists.grouping import group_pc
from .runlists.model import SOURCE_AUTO_EC, items_from_doc
from .serialization import _ship_iso
from .state import STATE
from .ui import HTML_PAGE
from . import log, views


def _cascade_context(target: str, raw_items: list, draft: dict):
    """Build the FIFO same-part release list + already-placed qty for the over-allocation
    cascade (design §12). Returns ``(releases_fifo, placed)`` from STATE + the current draft.
    """
    rid0 = next((it.get("releaseId") for it in raw_items if it.get("releaseId") is not None), None)
    if rid0 is None:
        return [], {}
    with STATE.lock:
        result, idx = STATE.result, STATE.idx
    if result is None or idx is None:
        return [], {}
    rel = idx.ext_by_id.get(int(rid0))
    if not rel:
        return [], {}
    part = rel.get("Part Number")
    sub = result.releases_with_id
    sub = sub[sub["Part Number"] == part].sort_values(["Ship Date", "Release ID"])
    fifo_all = [{"releaseId": int(x["Release ID"]), "relBal": int(x["Rel Bal"]),
                 "customer": str(x.get("Customer", "") or ""), "shipDate": _ship_iso(x["Ship Date"])}
                for x in sub.to_dict("records")]
    start = next((i for i, r in enumerate(fifo_all) if r["releaseId"] == int(rid0)), 0)
    placed: dict = {}
    for d in draft.get(target, []):
        k = d.get("releaseId")
        placed[k] = placed.get(k, 0) + int(d.get("allocQty") or 0)
    return fifo_all[start:], placed


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter console
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}")
        except (ValueError, TypeError):
            return {}

    def _release_detail(self, raw: list):
        """Build the detail tree for the release these pushed items belong to (or ``None``)."""
        rid0 = next((it.get("releaseId") for it in raw if it.get("releaseId") is not None), None)
        if rid0 is None:
            return None
        with STATE.lock:
            result, idx = STATE.result, STATE.idx
        if result is None or idx is None:
            return None
        rel = idx.ext_by_id.get(int(rid0))
        if not rel:
            return None
        return build_detail_tree(result, idx, int(rid0), int(rel.get("Rel Bal") or 0))

    def _pc_ec_deficit(self, raw: list, draft: dict, detail: dict = None):
        """Compute + add PC→EC deficit EC items to *draft* (design §13). Returns (count, report).

        *detail* may be a pre-built tree for this release (avoids rebuilding it on the push path).
        """
        rid0 = next((it.get("releaseId") for it in raw if it.get("releaseId") is not None), None)
        if rid0 is None:
            return 0, {"applicable": False}
        with STATE.lock:
            result, idx = STATE.result, STATE.idx
        if result is None or idx is None:
            return 0, {"applicable": False}
        rel = idx.ext_by_id.get(int(rid0))
        if not rel:
            return 0, {"applicable": False}
        if detail is None:
            detail = build_detail_tree(result, idx, int(rid0), int(rel.get("Rel Bal") or 0))
        if not detail:
            return 0, {"applicable": False}
        pc_run_qty = sum(int(it.get("allocQty") or 0) for it in raw)
        relmeta = {"releaseId": int(rid0), "customer": str(rel.get("Customer", "") or ""),
                   "shipDate": _ship_iso(rel.get("Ship Date"))}
        ec_raw, ec_rep = push.ec_deficit_items(detail, pc_run_qty, relmeta)
        if ec_raw:
            push.add_items(draft, "ec", [push.run_item_from_input("ec", it, source=SOURCE_AUTO_EC)
                                         for it in ec_raw])
        return len(ec_raw), ec_rep

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            html = HTML_PAGE.replace("__PAYLOAD__", json.dumps(STATE.queue_payload or {}))
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif u.path == "/snapshot":
            self._json(STATE.queue_payload or {})
        elif u.path == "/detail":
            q = parse_qs(u.query)
            key = q.get("key", [""])[0]
            rid = q.get("rid", [""])[0]
            with STATE.lock:
                result, idx = STATE.result, STATE.idx
            try:
                release_id = int(rid)
            except (TypeError, ValueError):
                # resolve from natural key
                release_id = None
                for r in (STATE.queue_payload or {}).get("releases", []):
                    if r["naturalKey"] == key:
                        release_id = r["releaseId"]
                        break
            if release_id is None or result is None:
                self._json({"error": "release not found"}, 404)
                return
            rel_bal = idx.ext_by_id.get(release_id, {}).get("Rel Bal", 0)
            tree = build_detail_tree(result, idx, release_id, int(rel_bal or 0))
            self._json(tree or {"error": "no routing"})
        elif u.path == "/runlist/draft.json":
            draft = push.load_draft()
            self._json({
                "pc": draft.get("pc", []),
                "ec": draft.get("ec", []),
                "pcGroups": group_pc(items_from_doc(draft, "pc")),
            })
        elif u.path == "/runlist/lock":
            self._json({"owner": lock.read_owner(), "mine": lock.own()})
        elif u.path == "/views":
            self._json({"me": views.current_user(), "views": views.list_views()})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/refresh":
            try:
                payload = STATE.refresh()
                self._json(payload)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 503)
        elif u.path == "/rebuild-graph":
            # Force a daily-inputs rebuild (routing/BOM reload), e.g. after a mid-day
            # routing/BOM change — then re-allocate. Otherwise identical to /refresh.
            try:
                payload = STATE.refresh(rebuild_graph=True)
                self._json(payload)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 503)
        elif u.path == "/runlist/push":
            body = self._read_json()
            target = str(body.get("target", ""))
            try:
                draft = push.load_draft()
                raw = body.get("items", [])
                detail = self._release_detail(raw)
                # Drop containers already in/past the target paint op (R17); never repaint.
                raw, skipped = push.eligible_items(detail, target, raw)
                fifo, placed = _cascade_context(target, raw, draft)
                raw2, report = push.cascade_items(raw, fifo, placed)  # over-allocation cascade
                items = [push.run_item_from_input(target, it) for it in raw2]
                push.add_items(draft, target, items)
                resp = {"ok": True, "added": len(items), "skipped": skipped, "cascade": report}
                if target == "pc":  # PC→EC deficit auto-fill (R4)
                    ec_added, ec_rep = self._pc_ec_deficit(raw, draft, detail)
                    resp["ecAutoAdded"] = ec_added
                    resp["ecDeficit"] = ec_rep
                push.save_draft(draft)
                resp["draftCounts"] = {"pc": len(draft.get("pc", [])), "ec": len(draft.get("ec", []))}
                self._json(resp)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 400)
        elif u.path == "/runlist/reorder":
            body = self._read_json()
            try:
                draft = push.load_draft()
                push.reorder(draft, str(body.get("target", "")), body.get("order", []))
                push.save_draft(draft)
                self._json({"ok": True, "draftCounts": {"pc": len(draft.get("pc", [])),
                                                         "ec": len(draft.get("ec", []))}})
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 400)
        elif u.path == "/runlist/ack":
            # Acknowledge (or un-acknowledge) an auto-added EC draft item (planner review, §13).
            body = self._read_json()
            try:
                draft = push.load_draft()
                found = push.acknowledge(draft, str(body.get("runItemId", "")),
                                         bool(body.get("acknowledged", True)))
                if found:
                    push.save_draft(draft)
                self._json({"ok": found})
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 400)
        elif u.path == "/runlist/reset":
            # Revert a target's draft to the live published list (design §16, Reset button).
            body = self._read_json()
            t = body.get("target")
            t = t if t in ("pc", "ec") else None   # None = reset both
            try:
                draft = push.load_draft()
                push.reset_to_live(draft, t)
                push.save_draft(draft)
                self._json({"ok": True, "draftCounts": {"pc": len(draft.get("pc", [])),
                                                         "ec": len(draft.get("ec", []))}})
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 400)
        elif u.path == "/runlist/clear":
            body = self._read_json()
            t = body.get("target")
            t = t if t in ("pc", "ec") else None   # None = clear both
            try:
                draft = push.load_draft()
                push.clear(draft, t)
                push.save_draft(draft)
                self._json({"ok": True, "draftCounts": {"pc": len(draft.get("pc", [])),
                                                         "ec": len(draft.get("ec", []))}})
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 400)
        elif u.path == "/runlist/publish":
            res = push.publish(push.load_draft())
            self._json(res, 200 if res.get("ok") else 409)
        elif u.path == "/views":
            body = self._read_json()
            res = views.save_view(body.get("name", ""), body.get("filters", {}), views.current_user())
            self._json(res, 200 if res.get("ok") else 409)
        elif u.path == "/views/delete":
            body = self._read_json()
            res = views.delete_view(body.get("name", ""), views.current_user())
            self._json(res, 200 if res.get("ok") else 409)
        else:
            self._send(404, b"not found", "text/plain")


class DashboardServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that logs unhandled request errors to the package logger.

    The stdlib default prints request tracebacks to ``stderr``, which vanishes when the
    console window closes — so an error triggered by a specific request would leave no
    trace. Routing it through the logger persists it to the log file. A request error does
    NOT take down the server; this is purely for diagnostics.
    """

    daemon_threads = True  # worker threads don't block process exit

    def handle_error(self, request, client_address):  # noqa: D401
        log.exception("Unhandled error servicing request from %s", client_address)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
