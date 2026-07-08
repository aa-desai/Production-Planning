r"""
Floor runlist pages (embedded HTML; stdlib-only) — design §17
=============================================================
Two read-only floor views that fetch ``/runlist.json`` from the viewer server and
re-render on a poll:

* :data:`PC_PAGE` — ``Current colour → Releases → containers`` (from ``group_pc``).
* :data:`EC_PAGE` — a flat container list.

Each container row shows the pushed fields: Part No · Serial · Location · Qty. Kept as
in-module strings (like the planner UI) so the floor viewer exes need no data files.
"""

from __future__ import annotations

_CSS = r"""<style>
:root{--bg:#e6e8ee;--panel:#fff;--ink:#0b141f;--muted:#33404f;--line:#d3d9e2;--navy:#27457e;
--mono:'Consolas','SFMono-Regular',ui-monospace,monospace;--sans:'Segoe UI',system-ui,sans-serif}
*{box-sizing:border-box}html,body{margin:0}
body{font-family:var(--sans);background:var(--bg);color:var(--ink);font-size:16px}
header.app{display:flex;align-items:center;gap:14px;padding:12px 18px;background:var(--navy);color:#fff;border-bottom:3px solid #1b3361}
header.app .logo{font-weight:800;font-size:19px;letter-spacing:.01em}
header.app .logo small{font-weight:400;color:#aebfdc;margin-left:8px;font-size:13px}
.pub{margin-left:auto;font-family:var(--mono);font-size:12.5px;color:#dfe6f4;background:rgba(255,255,255,.12);
 border:1px solid rgba(255,255,255,.28);border-radius:6px;padding:3px 9px;transition:background .3s,box-shadow .3s}
.pub.on{background:rgba(31,157,77,.5);box-shadow:0 0 0 2px #1f9d4d}
.ro{font-size:12px;color:#cdd8ee}
.wrap{padding:14px;max-width:1100px;margin:0 auto}
.empty{padding:48px;text-align:center;color:var(--muted);font-size:18px}
.colour{margin:0 0 18px}
.cband{display:flex;align-items:center;gap:12px;background:var(--navy);color:#fff;border-radius:9px;padding:9px 14px;font-weight:800}
.cband .cname{font-size:18px;letter-spacing:.02em}.cband .cqty{margin-left:auto;font-family:var(--mono);font-size:18px}
.rel{background:var(--panel);border:1px solid var(--line);border-radius:9px;margin:8px 0 0;overflow:hidden}
.rhead{display:flex;align-items:center;gap:12px;padding:8px 12px;background:#eef1f6;border-bottom:1px solid var(--line)}
.rhead .rpart{font-family:var(--mono);font-weight:800;font-size:16px}.rhead .rmeta{color:var(--muted);font-size:13.5px}
.rhead .rqty{margin-left:auto;font-family:var(--mono);font-weight:800;font-size:16px;color:var(--navy)}
table.ctab{width:100%;border-collapse:collapse;font-size:15px;background:var(--panel)}
.ctab th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);padding:6px 12px;border-bottom:1px solid var(--line)}
.ctab td{padding:7px 12px;border-bottom:1px solid #eef1f5}
.ctab tr:last-child td{border-bottom:none}
.ctab .num{text-align:right;font-family:var(--mono);font-weight:700}
.ctab .mono{font-family:var(--mono)}
.ectab{background:var(--panel);border:1px solid var(--line);border-radius:9px;overflow:hidden}
.total{font-weight:700;color:var(--navy);margin:0 0 10px;font-size:16px}
/* Minimal leave animation when a container drops off the runlist (was run). */
.ctab tr{transition:opacity .32s ease,transform .32s ease,background-color .32s ease}
.ctab tr.removing{opacity:0;transform:translateX(28px);background:#fde8e8}
/* Visual-only "ran" checkbox the operator ticks to track what they've run (per-browser). */
.ctab th.chk,.ctab td.chk{width:40px;text-align:center;padding-left:8px;padding-right:8px}
.ctab input.ranbox{width:20px;height:20px;cursor:pointer;accent-color:var(--navy);margin:0;vertical-align:middle}
.ctab tr.ran td:not(.chk){opacity:.42;text-decoration:line-through}
</style>"""

_COMMON_JS = r"""
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function fmtDate(iso){if(!iso)return '';const m=/^(\d{4})-(\d{2})-(\d{2})/.exec(iso);return m?m[2]+'-'+m[3]+'-'+m[1].slice(2):iso;}
function meta(d){
 const v=document.getElementById('ver'); if(v)v.textContent=d.appVersion?('v'+d.appVersion):'';
 const p=document.getElementById('pub'); if(p)p.textContent=d.publishedAt?('Published '+String(d.publishedAt).replace('T',' ')):'not published yet';
}
let lastPub; // undefined → first poll always renders
// If containers dropped off since the last render (reconciled — they were run), fade those
// rows out first, then re-render. `collectSerials` is provided per page (PC vs EC shape).
function animateThenRender(d){
 let ns=null; try{ns=collectSerials(d);}catch(_){}
 if(ns){const gone=[].slice.call(document.querySelectorAll('#root tr[data-serial]')).filter(r=>!ns.has(r.dataset.serial));
   if(gone.length){gone.forEach(r=>r.classList.add('removing'));setTimeout(()=>render(d),420);return;}}
 render(d);
}
function poll(){fetch('/runlist.json').then(x=>x.json()).then(d=>{
 if(d.publishedAt!==lastPub){const first=lastPub===undefined;lastPub=d.publishedAt;
   first?render(d):animateThenRender(d);
   const f=document.getElementById('pub'); if(f&&d.publishedAt){f.classList.add('on');setTimeout(()=>f.classList.remove('on'),1500);}}
}).catch(()=>{});}

// --- Visual-only "ran" tracking (per-browser; keyed by runItemId so ticks survive polls) ---
// `RAN_TARGET` ('pc'|'ec') is declared by each page's script. Nothing is sent to the server —
// the floor pages are read-only; this only helps the operator remember what they've run.
function ranKey(){return 'runlistRan:'+RAN_TARGET;}
function ranGet(){try{return new Set(JSON.parse(localStorage.getItem(ranKey())||'[]'));}catch(_){return new Set();}}
function ranSave(s){try{localStorage.setItem(ranKey(),JSON.stringify([].slice.call(s)));}catch(_){}}
// Restore checkbox state after a render, and prune stored ids no longer on the list (an item
// reconciled off the runlist drops its tick, so a reused id can't resurrect an old check).
function applyRan(){
 const s=ranGet();const present=new Set();let changed=false;
 [].slice.call(document.querySelectorAll('#root input.ranbox[data-run-id]')).forEach(b=>{
   const id=b.dataset.runId;present.add(id);const on=s.has(id);b.checked=on;
   const tr=b.closest('tr');if(tr)tr.classList.toggle('ran',on);});
 s.forEach(id=>{if(!present.has(id)){s.delete(id);changed=true;}});
 if(changed)ranSave(s);
}
document.addEventListener('change',function(e){
 const b=e.target;if(!b||!b.classList||!b.classList.contains('ranbox'))return;
 const s=ranGet();b.checked?s.add(b.dataset.runId):s.delete(b.dataset.runId);ranSave(s);
 const tr=b.closest('tr');if(tr)tr.classList.toggle('ran',b.checked);
});
"""

_PC_JS = r"""
var RAN_TARGET='pc';
function collectSerials(d){const s=new Set();(d.groups||[]).forEach(g=>(g.releases||[]).forEach(r=>(r.items||[]).forEach(it=>s.add(String(it.serial)))));return s;}
function render(d){meta(d);const root=document.getElementById('root');const groups=d.groups||[];
 if(!groups.length){root.innerHTML='<div class="empty">No PC runlist published yet.</div>';return;}
 root.innerHTML=groups.map(g=>`
  <section class="colour">
    <div class="cband"><span class="cname">${esc(g.colour)}</span><span class="cqty">${g.qty}</span></div>
    ${g.releases.map(r=>`
      <div class="rel">
        <div class="rhead"><span class="rpart">${esc(r.part)}</span>
          <span class="rmeta">${esc(r.customer)} &middot; ship ${fmtDate(r.shipDate)}</span>
          <span class="rqty">${r.qty}</span></div>
        <table class="ctab"><thead><tr><th class="chk">Ran</th><th>Part No</th><th>Serial</th><th>Location</th><th class="num">Qty</th></tr></thead>
        <tbody>${r.items.map(it=>`<tr data-serial="${esc(it.serial)}"><td class="chk"><input type="checkbox" class="ranbox" data-run-id="${esc(it.runItemId)}"></td><td class="mono">${esc(it.partNo)}</td><td class="mono">${esc(it.serial)}</td><td>${esc(it.location)}</td><td class="num">${it.allocQty}</td></tr>`).join('')}</tbody></table>
      </div>`).join('')}
  </section>`).join('');
 applyRan();
}
poll();setInterval(poll,15000);
"""

_EC_JS = r"""
var RAN_TARGET='ec';
function collectSerials(d){const s=new Set();(d.items||[]).forEach(it=>s.add(String(it.serial)));return s;}
function render(d){meta(d);const root=document.getElementById('root');const items=d.items||[];
 if(!items.length){root.innerHTML='<div class="empty">No EC runlist published yet.</div>';return;}
 const total=items.reduce((s,it)=>s+(+it.allocQty||0),0);
 root.innerHTML=`<div class="total">Containers: ${items.length} &middot; Total Qty: ${total}</div>
  <div class="ectab"><table class="ctab"><thead><tr><th class="chk">Ran</th><th>Part No</th><th>Serial</th><th>Location</th><th class="num">Qty</th></tr></thead>
  <tbody>${items.map(it=>`<tr data-serial="${esc(it.serial)}"><td class="chk"><input type="checkbox" class="ranbox" data-run-id="${esc(it.runItemId)}"></td><td class="mono">${esc(it.partNo)}</td><td class="mono">${esc(it.serial)}</td><td>${esc(it.location)}</td><td class="num">${it.allocQty}</td></tr>`).join('')}</tbody></table></div>`;
 applyRan();
}
poll();setInterval(poll,15000);
"""


def _page(title: str, header_label: str, js: str) -> str:
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title>" + _CSS + "</head><body>"
        "<header class=\"app\"><span class=\"logo\">" + header_label +
        " <small id=\"ver\"></small></span><span id=\"pub\" class=\"pub\"></span>"
        "<span class=\"ro\">read-only floor view</span></header>"
        "<main id=\"root\" class=\"wrap\"></main>"
        "<script>" + _COMMON_JS + js + "</script></body></html>"
    )


PC_PAGE = _page("PC Runlist", "PC Runlist", _PC_JS)
EC_PAGE = _page("EC Runlist", "EC Runlist", _EC_JS)
