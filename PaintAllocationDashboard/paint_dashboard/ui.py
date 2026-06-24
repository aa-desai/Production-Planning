"""
Embedded single-page UI (read-only)
===================================
The full dashboard front-end as one HTML string: Classic ship-date queue (day
dividers, filters/presets, draggable splitter) + Stack/Flow detail toggle, Bold
Slate theme. ``__PAYLOAD__`` is replaced with the live queue payload when served
from ``GET /``; the page fetches ``/detail`` and ``/snapshot`` for the rest.

Kept as an in-module string (not a separate file) so the frozen one-file .exe
needs no data-file bundling. Mirrors paint_dashboard_ui_refined.html.
"""

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paint Allocation Dashboard</title>
<style>
/* Theme: Bold Slate — slate canvas, deep navy header + accent, vivid coverage. */
:root{--bg:#e6e8ee;--panel:#ffffff;--panel-2:#eef1f6;--panel-3:#e2e6ee;--ink:#0b141f;
--muted:#33404f;--faint:#4a576b;--line:#d3d9e2;--line-soft:#e3e7ee;--accent:#27457e;--accent-soft:#e7edf7;
--navy:#27457e;--navy-2:#2f5191;
--c-past:#1f9d4d;--c-paint:#f2bf0b;--c-pipe:#f47b1f;--c-short:#df3b3b;
--t-good:#1f9d4d;--t-low:#f2bf0b;--t-med:#f47b1f;--t-high:#df3b3b;
--mono:'Consolas','SFMono-Regular',ui-monospace,monospace;--sans:'Segoe UI',system-ui,sans-serif}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{font-family:var(--sans);color:var(--ink);background:var(--bg);font-size:14px}
header.app{display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--navy);color:#fff;border-bottom:3px solid #1b3361;box-shadow:0 2px 8px rgba(20,30,55,.25)}
header.app .logo{font-weight:800;letter-spacing:.01em}header.app .logo small{font-weight:400;color:#aebfdc;margin-left:8px}
.spacer{flex:1}.btn{border:1px solid var(--line);background:#fff;border-radius:7px;padding:5px 11px;cursor:pointer;font-size:12px;font-weight:600}
.btn:hover{background:var(--panel-2)}
/* Refresh: bold/poppy white pill on the navy header; animates width on click. */
.btn.refresh{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;background:#fff;color:var(--accent);
 border:none;border-radius:9px;padding:7px 15px;font-size:13.5px;font-weight:800;letter-spacing:.02em;
 cursor:pointer;box-shadow:0 2px 8px rgba(11,20,31,.28);white-space:nowrap;overflow:hidden;
 transition:width .34s cubic-bezier(.34,.01,.2,1),background-color .3s ease,color .3s ease,transform .12s ease}
.btn.refresh:hover{background:#eaf0fa;transform:translateY(-1px);box-shadow:0 4px 12px rgba(11,20,31,.32)}
.btn.refresh:active{transform:translateY(0)}
.btn.refresh.done{background:var(--c-past);color:#fff}
.btn.refresh.fail{background:var(--c-short);color:#fff}
.btn.refresh .rlabel{display:inline-block}
.ricon{width:0;height:16px;overflow:hidden;display:inline-flex;align-items:center;justify-content:center;
 margin-right:0;flex:0 0 auto;transition:width .3s cubic-bezier(.34,.01,.2,1),margin-right .3s cubic-bezier(.34,.01,.2,1)}
.ricon.show{width:16px;margin-right:8px}
.ricon .spin{width:14px;height:14px;border-radius:50%;border:2px solid rgba(39,69,126,.28);border-top-color:var(--accent);animation:rspin .62s linear infinite}
@keyframes rspin{to{transform:rotate(360deg)}}
.twopane{display:grid;grid-template-columns:var(--leftw,46%) 10px minmax(0,1fr);gap:0;padding:12px;height:calc(100vh - 50px)}
/* Draggable splitter between the two panes (left pane resizes; right takes the rest). */
.gutter{align-self:stretch;display:flex;align-items:center;justify-content:center;cursor:col-resize;touch-action:none}
.gutter::before{content:"";width:4px;height:46px;max-height:60%;border-radius:3px;background:var(--line);transition:background .15s ease,width .15s ease}
.gutter:hover::before,.gutter.drag::before{background:var(--accent);width:5px}
body.resizing{cursor:col-resize!important;user-select:none}
.pane{background:var(--panel);border:1px solid var(--line);border-radius:10px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.pane-head{padding:9px 12px;background:var(--panel-2);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
/* Title bars in both panes share a fixed height so "Release Queue" and "Selected
   Release" line up even though the right one carries the taller Stack/Flow toggle. */
.pane-head.headbar{min-height:48px}
.pane-head h3{margin:0;font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:var(--accent);font-weight:700;line-height:1}
.pane-body{overflow:auto;padding:8px;flex:1}
.cov{display:flex;height:9px;width:100%;border-radius:5px;overflow:hidden;background:#dfe2e9;border:1px solid #cdd1da}
.cov.lg{height:12px}.cov span{display:block;height:100%}
.seg-past{background:var(--c-past)}
.seg-paint{background:var(--c-paint)}
.seg-pipe{background:var(--c-pipe)}
.seg-short{background:var(--c-short)}
.cov-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--muted)}
.cov-legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px;border:1px solid #bcc1cb}
.agewarn{width:17px;height:17px;flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center}
.agewarn svg{display:block}
.concern{width:17px;height:17px;border-radius:50%;flex:0 0 auto;display:inline-block;border:2px solid currentColor;position:relative}
.concern.good{color:var(--t-good);background:currentColor}
.concern.low{color:var(--t-low);background:linear-gradient(90deg,currentColor 50%,#fff 50%)}
.concern.medium{color:var(--t-med);background:conic-gradient(currentColor 0 75%,#fff 0)}
.concern.high{color:var(--t-high);background:#fff}
.concern.high::after{content:"";position:absolute;inset:3px;border-radius:50%;background:currentColor}
.hidegrp{display:inline-flex;align-items:center;gap:4px}
.hidegrp .hlbl{font-size:11px;color:var(--muted)}
/* Coverage condition chips (Any/OR sections): tri-state off -> require (.on) -> exclude (.neg). */
.chip.cond{gap:5px}
.chip.cond i{width:9px;height:9px;border-radius:50%;display:inline-block;flex:0 0 auto;border:1px solid rgba(0,0,0,.18)}
.chip.cond.on i,.chip.cond.neg i{border-color:rgba(255,255,255,.7)}
.pbadge{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600}
.pbadge .ec{background:#e7f0ff;color:#1554c0;border:1px solid #bcd2f7;border-radius:4px;padding:1px 5px}
.swatch{min-width:21px;width:auto;height:16px;padding:0 4px;border-radius:3px;border:1px solid rgba(0,0,0,.28);display:inline-flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;line-height:1;white-space:nowrap}
.pie{width:14px;height:14px;border-radius:50%;border:1.5px solid var(--c-past);display:inline-block;flex:0 0 auto}
.filters{display:flex;gap:6px;flex-wrap:wrap;align-items:center;width:100%}
.chip{border:1px solid var(--line);background:#fff;border-radius:16px;padding:3px 9px;font-size:11.5px;cursor:pointer;display:inline-flex;gap:5px;align-items:center}
.chip.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.chip.neg{background:var(--c-short);color:#fff;border-color:var(--c-short)}
/* Filter area: Presets (left) | divider | quick filters (right). */
.filterbar{display:flex;align-items:flex-start;gap:10px;width:100%}
.presets{display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex:0 0 auto;max-width:46%}
.presetchips{display:inline-flex;gap:6px;flex-wrap:wrap}
.fdivider{flex:0 0 auto;align-self:stretch;width:1px;background:var(--line);margin:0 2px}
.quickfilters{display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex:1 1 auto;min-width:0}
.seclbl{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);font-weight:700;white-space:nowrap}
.chip.preset{padding-right:5px}
.chip.preset .px{cursor:pointer;color:var(--faint);font-weight:800;margin-left:1px;padding:0 3px;border-radius:4px;line-height:1}
.chip.preset .px:hover{color:#fff;background:var(--c-short)}
.chip.psave{border-style:dashed;color:var(--accent);border-color:var(--accent);font-weight:700}
.pnone{font-size:11px;color:var(--faint);font-style:italic}
.drange{flex:1;min-width:70px;accent-color:var(--accent);height:14px}
input.search{border:1px solid var(--line);border-radius:7px;padding:5px 9px;font-size:12px;min-width:110px}
/* Shrinkable tracks (minmax(0,…)) so the row always fits the pane — otherwise,
   once the vertical scrollbar narrows the body, the fixed columns overflow and the
   selection highlight (which only paints to the row's box) stops short of the date/qty. */
.qrow{display:grid;grid-template-columns:26px 18px minmax(0,84px) 30px minmax(56px,1fr) minmax(38px,64px) 60px minmax(40px,auto);align-items:center;gap:7px;padding:8px 10px;border-radius:9px;cursor:pointer;border:1px solid transparent;min-width:0;overflow:hidden}
/* Queue multi-select: a checkbox + a selection-order badge per release row. */
.relselbox{position:relative;display:inline-flex;align-items:center;justify-content:center;width:26px;height:22px;flex:0 0 auto}
.relselbox .relbox{width:16px;height:16px;cursor:pointer;margin:0;accent-color:var(--accent)}
.relselbox .relnum{position:absolute;top:-5px;right:-3px;min-width:14px;height:14px;padding:0 3px;border-radius:8px;
 background:var(--accent);color:#fff;font-size:9px;font-weight:800;line-height:14px;text-align:center;pointer-events:none;
 box-shadow:0 1px 2px rgba(11,20,31,.3)}
.relselbox .relnum:empty{display:none}
.qrow.relsel{background:var(--accent-soft);box-shadow:inset 0 0 0 1px var(--accent)}
.qrow .plant{font-family:var(--mono);font-size:13px;color:var(--muted);text-align:center}
.qrow:hover{background:var(--accent-soft)}.qrow.sel{background:var(--accent-soft);border-color:var(--accent);border-left:4px solid var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.qrow.overdue{background:rgba(220,38,38,.07)}
.qrow.overdue:hover{background:rgba(220,38,38,.12)}
.qrow.overdue.relsel{background:rgba(220,38,38,.16);box-shadow:inset 0 0 0 1px rgba(220,38,38,.55)}
.qrow.overdue.sel{background:rgba(220,38,38,.22);border-color:rgba(220,38,38,.85);border-left:4px solid rgba(220,38,38,.95);box-shadow:inset 0 0 0 1px rgba(220,38,38,.6)}
.qrow.overdue.sel:hover{background:rgba(220,38,38,.28)}
.qrow .cust{color:var(--muted);font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qrow .pnwrap{display:flex;align-items:center;gap:6px;min-width:0}
.qrow .addr{font-family:var(--mono);font-size:10.5px;color:var(--muted);white-space:nowrap;flex:0 0 auto;letter-spacing:-.2px}
.qrow .pn{font-family:var(--mono);font-weight:700;font-size:15px;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qrow .date{font-family:var(--mono);color:var(--muted);font-size:13px;white-space:nowrap;text-align:right}.qrow .bal{font-weight:800;font-size:15px;text-align:right}
.copybtn{flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;width:24px;height:22px;padding:0;border:1px solid var(--line);background:#fff;color:var(--faint);border-radius:5px;cursor:pointer}
.copybtn:hover{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.copybtn.ok{background:var(--c-past);border-color:var(--c-past);color:#fff}
.daygroup{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint);margin:8px 8px 2px;display:flex;align-items:center;gap:8px}
.daygroup::after{content:"";flex:1;height:1px;background:var(--line-soft)}
/* Segmented Stack/Flow toggle with a sliding thumb (200ms). */
.seg{position:relative;display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff}
.seg .thumb{position:absolute;top:0;left:0;width:50%;height:100%;background:var(--accent);border-radius:7px;z-index:0;
 transition:transform .2s cubic-bezier(.4,0,.2,1)}
.seg.flow .thumb{transform:translateX(100%)}
.seg button{position:relative;z-index:1;width:74px;text-align:center;border:none;background:transparent;padding:6px 0;
 cursor:pointer;font-size:12px;font-weight:600;color:var(--muted);transition:color .2s ease}
.seg button.on{color:#fff}
@keyframes vfade{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}
.vfade{animation:vfade .2s cubic-bezier(.4,0,.2,1)}
.detailhead{display:flex;align-items:center;gap:10px;padding:8px 4px;flex-wrap:wrap}
.detailhead .pn{font-family:var(--mono);font-weight:700;font-size:14px}.detailhead .meta{color:var(--muted)}
.oprow{border:1px solid var(--line);border-radius:9px;margin:6px 0;background:#fff;overflow:hidden}
.oprow.up{background:var(--panel-3)}.oprow.collapsed .cardstrip,.oprow.collapsed .subroute{display:none}
.ophead{display:flex;align-items:center;gap:10px;padding:8px 10px;cursor:pointer}
.ophead .opname{font-weight:600;min-width:120px}.ophead .opnet{font-family:var(--mono);color:var(--accent);font-weight:700}
.ophead .opnet small{color:var(--muted);font-weight:400}.ophead .caret{color:var(--muted);width:12px;display:inline-block}
.oprow.collapsed .caret{transform:rotate(-90deg)}.ophead.paint{background:linear-gradient(0deg,#fff,#fff7e8)}
.tag-paint{font-size:9.5px;font-weight:700;color:#9a6b00;background:#ffedcc;border:1px solid #f0d18a;border-radius:4px;padding:1px 5px}
.cardstrip{display:flex;gap:6px;overflow-x:auto;padding:4px 8px 9px}
.ccard{flex:0 0 auto;min-width:120px;border:1px solid var(--line);border-radius:8px;padding:6px 8px;background:#fff;cursor:pointer;border-left:4px solid #c3c8d2;position:relative}
.ccard:hover{border-color:#aeb6c4}.ccard.past{border-left-color:var(--c-past)}
.ccard .sn{font-family:var(--mono);font-size:11px}.ccard .loc{font-size:10.5px;color:var(--muted)}
.ccard .qty{font-weight:700;font-size:13px;margin-top:2px}
.ccard .corner{position:absolute;top:6px;right:7px;width:7px;height:7px;border-radius:50%;background:var(--c-past)}
.ccard:not(.past) .corner{display:none}
.ccard.mrb{background:#e9eaee;color:#7b8090;border-left-color:#b7bcc7;font-style:italic;display:flex;align-items:center}
.subroute{margin:0 10px 9px 30px;border:1px dashed #b9c0cc;border-left:3px solid var(--accent);border-radius:9px;background:#f5f8ff}
.subhead{display:flex;align-items:center;gap:8px;padding:7px 10px;cursor:pointer;font-size:12px}
.subhead .lbl{font-weight:700;font-family:var(--mono)}.subhead .xq{font-family:var(--mono);color:var(--muted)}
.subroute .innerops{display:none;padding:0 8px 8px}.subroute.open .innerops{display:block}
.flowwrap{overflow:auto;padding:8px 4px;flex:1}.flowline{display:flex;align-items:flex-start;min-width:max-content;padding-bottom:8px}
.fstage{min-width:152px;max-width:152px;border:1px solid var(--line);border-radius:10px;background:#fff;padding:8px;position:relative;margin-right:32px}
.fstage.up{background:var(--panel-3)}
.fstage::after{content:"";position:absolute;right:-26px;top:34px;width:20px;height:2px;background:#b7bcc7}
.fstage:last-child::after{display:none}.fstage.paint{border-color:#ecc569;background:#fff7e8}
.fstage .fname{font-weight:700;font-size:12px}.fstage .fnet{font-family:var(--mono);color:var(--accent);font-size:11px;margin:1px 0 6px}
.fmini{border:1px solid var(--line);border-radius:6px;margin:3px 0;padding:3px 6px;font-size:10.5px;font-family:var(--mono);background:#fff;cursor:pointer}
.fmini.past{border-left:4px solid var(--c-past)}.fmini.mrb{background:#e9eaee;color:#7b8090;font-style:italic;cursor:default}
.fmini.elsewhere{opacity:.45}.fmini.elsewhere:hover{opacity:.7}
.fbranch{margin-top:8px;border-top:1px dashed #b9c0cc;padding-top:6px}.fbranch .bl{font-size:10px;color:var(--accent);font-weight:700;margin-bottom:4px;font-family:var(--mono)}
#pop{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:rgba(20,24,32,.4);z-index:100}
#pop.show{display:flex}#pop .box{background:#fff;border-radius:12px;padding:16px 18px;min-width:310px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
#pop h4{margin:0 0 10px}#pop .frow{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px}
#pop .frow b{font-family:var(--mono)}.note{font-size:11px;color:var(--muted);margin-top:8px}
.empty{color:var(--muted);padding:20px;text-align:center}.readonly{font-size:11px;color:#cdd8ee}
.pulled{font-size:11.5px;color:#dfe6f4;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.28);border-radius:6px;padding:2px 8px;font-family:var(--mono);transition:box-shadow .3s,background .3s}
.pulled.flash{background:rgba(31,157,77,.45);box-shadow:0 0 0 2px var(--c-past)}
/* --- Runlist authoring (planner) --- */
.runbar{display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--line);background:#f4f6fa;flex-wrap:wrap}
.runbar .rcount{font-size:11.5px;color:var(--muted);font-family:var(--mono)}
.runbar .rdiv{width:1px;align-self:stretch;background:var(--line);margin:0 2px}
.btn.rpush{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:700}
.btn.rpush.ec{background:#1554c0;border-color:#1554c0}
.btn.rpush:hover{filter:brightness(1.06)}
.btn.rpub{background:var(--c-past);color:#fff;border-color:var(--c-past);font-weight:700}
.btn.rpub:disabled{opacity:.5;cursor:default}
.runbar .rlock{font-size:11px;color:var(--faint);font-family:var(--mono)}
.ecnote{color:#9a6b00;background:#ffedcc;border:1px solid #f0d18a;border-radius:6px;padding:2px 8px;font-size:11.5px;font-weight:700}
/* --- Runlist reorder editor --- */
#editor{position:fixed;inset:0;display:none;background:rgba(20,24,32,.5);z-index:140}
#editor.show{display:flex}
#editor .ebox{background:var(--bg);margin:18px auto;border-radius:12px;width:calc(100% - 36px);max-width:1100px;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.4);overflow:hidden;max-height:calc(100vh - 36px)}
#editor .ehead{display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--navy);color:#fff}
#editor .ehead h3{margin:0;font-size:15px}
#editor .ebody{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px;overflow:auto;flex:1}
#editor .ecol{background:var(--panel);border:1px solid var(--line);border-radius:9px;display:flex;flex-direction:column;overflow:hidden;min-height:140px}
#editor .ecolhead{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--panel-2);border-bottom:1px solid var(--line);font-weight:700;color:var(--accent);font-size:13px}
#editor .ecolhead .edclear{margin-left:auto;font-weight:600;color:var(--c-short);border-color:var(--line)}
#editor .ecolhead .edclear:hover{background:var(--c-short);color:#fff;border-color:var(--c-short)}
#editor .elist{padding:8px;overflow:auto;flex:1}
.eitem{display:flex;align-items:center;gap:8px;padding:6px 8px;border:1px solid var(--line);border-radius:7px;margin:4px 0;background:#fff;cursor:grab;font-size:12.5px}
.eitem.drag{opacity:.4}.eitem.over{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-soft)}
.eitem .edsel{flex:0 0 auto;margin:0 2px 0 0;cursor:pointer}
.eitem.selrow{background:var(--accent-soft);border-color:var(--accent)}
.eitem .es{font-family:var(--mono);font-weight:700}.eitem .eq{margin-left:auto;font-family:var(--mono);font-weight:700;color:var(--accent)}
.eitem.auto{background:#ffedcc;border-color:#f0d18a}
.ecolour{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--faint);font-weight:700;margin:8px 4px 2px}
#editor .erev{background:#ffedcc;border:1px solid #f0d18a;color:#9a6b00;border-radius:6px;padding:3px 10px;font-size:12px;font-weight:700}
#editor .ehint{padding:6px 16px;font-size:11px;color:var(--muted);border-top:1px solid var(--line)}
.ccard .selbox{position:absolute;top:6px;left:6px;margin:0;width:15px;height:15px;cursor:pointer;z-index:2}
.ccard .cardmain{cursor:pointer;padding-left:14px}
.ccard.sel{outline:2px solid var(--accent);background:var(--accent-soft)}
.ccard.elsewhere{opacity:.45;background:#f4f5f8;border-left-color:#c3c8d2}
.ccard.elsewhere:hover{opacity:.7}.ccard.elsewhere .qty{color:var(--muted)}
#qtypop{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:rgba(20,24,32,.4);z-index:120}
#qtypop.show{display:flex}
#qtypop .box{background:#fff;border-radius:12px;padding:16px 18px;min-width:300px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
#qtypop h4{margin:0 0 10px}
#qtypop .qbtns{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.qrow2{display:flex;gap:6px;align-items:center;margin-top:4px}
.qrow2 input{width:90px;padding:5px 8px;border:1px solid var(--line);border-radius:6px}
/* --- (2.1) Universal click feedback: every button/chip dips on press --- */
.btn,.chip,.hchip,.copybtn,.eitem,.seg button{transition:background-color .15s ease,border-color .15s ease,color .15s ease,box-shadow .15s ease,transform .07s ease}
.btn:active{transform:translateY(1px) scale(.985)}
.chip:active,.hchip:active,#viewtoggle button:active{transform:scale(.93)}
.copybtn:active{transform:scale(.88)}
.btn:active,.chip:active{box-shadow:inset 0 1px 3px rgba(11,20,31,.18)}
/* --- (2.2) Generic loading buttons (match the Refresh button's feel) --- */
.btn.busy,.btn.bdone,.btn.bfail{display:inline-flex;align-items:center;justify-content:center;gap:6px}
.btn.busy{opacity:.96;cursor:default}
.btn.bdone{background:var(--c-past)!important;color:#fff!important;border-color:var(--c-past)!important}
.btn.bfail{background:var(--c-short)!important;color:#fff!important;border-color:var(--c-short)!important}
.bspin{width:12px;height:12px;border-radius:50%;border:2px solid rgba(39,69,126,.30);border-top-color:var(--accent);
 animation:rspin .62s linear infinite;display:inline-block;flex:0 0 auto}
.btn.rpush .bspin,.btn.rpub .bspin{border-color:rgba(255,255,255,.45);border-top-color:#fff}
/* --- (2.3/2.4) Reorder editor: group headers, drag ghost + make-space animation --- */
.ehdr{display:flex;align-items:center;gap:8px;padding:5px 9px;margin:8px 0 3px;border-radius:7px;cursor:grab;
 user-select:none;font-weight:700;transition:transform .18s ease,box-shadow .15s ease,opacity .2s ease}
.ehdr:active{cursor:grabbing}
.ehide{display:none}
/* Collapse pip: large glyph + a generous square hit target with a hover halo. */
.ehdr .caret{flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;margin:-3px 0 -3px -2px;
 font-size:17px;line-height:1;border-radius:6px;transition:transform .15s ease,background-color .15s ease;cursor:pointer}
.ehdr .caret:hover{background:rgba(11,20,31,.14)}
.ehdr.collapsed .caret{transform:rotate(-90deg)}
.ehdr .ghandle{color:var(--faint);font-size:15px;line-height:1;letter-spacing:-1px}
/* Keep both icons legible on the dark navy colour header. */
.ehdr.colhdr .caret{color:#fff}
.ehdr.colhdr .caret:hover{background:rgba(255,255,255,.24)}
.ehdr.colhdr .ghandle{color:rgba(255,255,255,.82)}
.ehdr.parthdr .caret,.ehdr.parthdr .ghandle{color:var(--accent)}
.ehdr .ecount{margin-left:auto;font-family:var(--mono);font-weight:700;font-size:11.5px;opacity:.85}
.ehdr.colhdr{background:var(--navy);color:#fff;font-size:12.5px;text-transform:uppercase;letter-spacing:.04em}
.ehdr.colhdr .gsw{width:12px;height:12px;border-radius:3px;border:1px solid rgba(255,255,255,.55);flex:0 0 auto}
.ehdr.parthdr{background:var(--panel-3);color:var(--accent);font-family:var(--mono);font-size:12px;margin-left:14px}
.ehdr.parthdr.econly{margin-left:0}
.elist .eitem{margin-left:26px;transition:transform .18s ease,opacity .22s ease,box-shadow .15s ease,background-color .15s ease}
.elist .eitem.econly{margin-left:14px}
.eitem.drag,.ehdr.drag{opacity:.45;box-shadow:0 6px 16px rgba(11,20,31,.22)}
.elist.dragging .eitem,.elist.dragging .ehdr{cursor:grabbing}
.eitem.removing,.ehdr.removing{opacity:0;transform:translateX(26px);background:#fde8e8;border-color:#f3b4b4}
.eitem .eack{flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;width:22px;height:20px;
 padding:0;margin-left:8px;border:1px solid var(--line);background:#fff;color:var(--faint);border-radius:5px;cursor:pointer}
.eitem .eack:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}
.eitem.auto .eack{border-color:#e0b651;color:#9a6b00}
.eitem.auto .eack:hover{background:#fff;border-color:var(--c-past);color:var(--c-past)}
#editor .ecolhead .edreset{font-weight:600;color:var(--accent);border-color:var(--line)}
#editor .ecolhead .edreset:hover{background:var(--accent);color:#fff;border-color:var(--accent)}
/* Toast notifications: transient overlay messages that auto-dismiss (no click needed). */
#toasts{position:fixed;top:60px;right:16px;z-index:200;display:flex;flex-direction:column;gap:8px;
 max-width:340px;pointer-events:none}
.toast{pointer-events:auto;background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--accent);
 border-radius:8px;padding:9px 12px 9px 11px;font-size:12.5px;line-height:1.35;color:var(--ink);
 box-shadow:0 6px 18px rgba(11,20,31,.22);opacity:0;transform:translateX(18px);
 transition:opacity .25s ease,transform .25s ease}
.toast.show{opacity:1;transform:none}
.toast.warn{border-left-color:var(--c-pipe)}
.toast.err{border-left-color:var(--c-short)}
.toast.ok{border-left-color:var(--c-past)}
/* Global top loading bar — smooth GPU transform; replaces sticky per-button animations. */
#loadbar{position:fixed;top:0;left:0;right:0;height:3px;z-index:9999;overflow:hidden;opacity:0;transition:opacity .12s;pointer-events:none}
#loadbar.on{opacity:1}
#loadbar::before{content:"";position:absolute;top:0;left:0;height:100%;width:35%;border-radius:0 3px 3px 0;background:linear-gradient(90deg,transparent,var(--accent),transparent);animation:lbslide 1s ease-in-out infinite;will-change:transform}
@keyframes lbslide{0%{transform:translateX(-120%)}100%{transform:translateX(400%)}}
</style></head><body>
<div id="loadbar" aria-hidden="true"></div>
<header class="app">
  <span class="logo">Paint Allocation Dashboard <small id="appver"></small></span>
  <span id="datapulled" class="pulled"></span>
  <span class="spacer"></span>
  <span class="readonly">read-only view</span>
  <button class="btn" id="openEditor" title="Reorder + publish the floor runlists">Runlist editor</button>
  <button class="btn" id="rebuildGraph" title="Reload routing/BOM and rebuild the graph — use after a mid-day routing/BOM change">Rebuild graph</button>
  <button class="btn refresh" id="refresh"><span class="ricon" aria-hidden="true"></span><span class="rlabel">Refresh</span></button>
</header>
<div class="twopane">
  <div class="pane">
    <div class="pane-head headbar"><h3>Release Queue</h3><span class="spacer"></span>
      <span style="font-size:11px;color:var(--muted)">sort: ship date &uarr;</span></div>
    <div class="pane-head" style="background:#fff">
      <div class="filterbar">
        <div class="presets">
          <span class="seclbl">Views</span>
          <span id="presetChips" class="presetchips"></span>
          <button class="chip psave" id="savePreset" title="Save the current filters as a preset view">+ Save view</button>
          <span class="chip" id="clearFilters" title="Reset all quick filters">Clear</span>
          <span class="seclbl" style="margin-left:6px">Shared</span>
          <span id="sharedChips" class="presetchips"></span>
          <button class="chip psave" id="shareView" title="Publish the current filters to the shared bank">+ Share</button>
        </div>
        <div class="fdivider"></div>
        <div class="quickfilters">
          <span class="seclbl">Quick&nbsp;filters</span>
          <span class="chip" id="custBtn">+ Customer</span>
          <span class="chip" id="ecChip" data-p="EC">EC</span>
          <span class="chip" id="pcChip" data-p="PC">PC</span>
          <span class="chip" id="colourBtn">Colour &#9662;</span>
          <span class="chip" id="invP10Chip" title="Hide P6 releases that have no inventory anywhere in their routing at P10">Inventory at P10</span>
          <span class="hidegrp" title="Any: matches if the release has SOME of every chip you set. Click = has some of this bucket; click again = has none; again = off.">
            <span class="hlbl">Any</span>
            <span class="chip cond" data-grp="any" data-k="pastPaint"><i style="background:var(--c-past)"></i><span class="cl">Past Paint</span></span>
            <span class="chip cond" data-grp="any" data-k="paintable"><i style="background:var(--c-paint)"></i><span class="cl">WIP</span></span>
            <span class="chip cond" data-grp="any" data-k="pipeline"><i style="background:var(--c-pipe)"></i><span class="cl">Pipeline</span></span>
            <span class="chip cond" data-grp="any" data-k="short"><i style="background:var(--c-short)"></i><span class="cl">Short</span></span>
          </span>
          <span class="hidegrp" title="All: matches only if the ENTIRE coverage bar is (or, when 'not', is not) that bucket. Click = entire bar is this; click again = entire bar is not this; again = off.">
            <span class="hlbl">All</span>
            <span class="chip cond" data-grp="all" data-k="pastPaint"><i style="background:var(--c-past)"></i><span class="cl">Past Paint</span></span>
            <span class="chip cond" data-grp="all" data-k="paintable"><i style="background:var(--c-paint)"></i><span class="cl">WIP</span></span>
            <span class="chip cond" data-grp="all" data-k="pipeline"><i style="background:var(--c-pipe)"></i><span class="cl">Pipeline</span></span>
            <span class="chip cond" data-grp="all" data-k="short"><i style="background:var(--c-short)"></i><span class="cl">Short</span></span>
          </span>
          <input class="search" id="search" placeholder="part #&hellip;">
          <span class="spacer"></span><span id="count" style="font-size:11px;color:var(--muted)"></span>
        </div>
      </div>
    </div>
    <div id="custPanel" class="pane-head" style="display:none;background:#fff"></div>
    <div id="colourPanel" class="pane-head" style="display:none;background:#fff"></div>
    <div class="pane-head" style="background:#fff">
      <div class="filters" style="align-items:center;flex-wrap:nowrap">
        <span style="font-size:11px;color:var(--muted)">Ship</span>
        <b id="dFrom" style="font-family:var(--mono);font-size:11px;min-width:74px"></b>
        <input type="range" id="dLo" class="drange">
        <input type="range" id="dHi" class="drange">
        <b id="dTo" style="font-family:var(--mono);font-size:11px;min-width:74px;text-align:right"></b>
        <span class="chip" id="dReset">all dates</span>
      </div>
    </div>
    <div class="pane-body" id="queue"></div>
    <div class="pane-head" style="border-top:1px solid var(--line);border-bottom:none">
      <div class="cov-legend">
        <span><i style="background:var(--c-past)"></i>past paint</span>
        <span><i class="seg-paint"></i>paintable</span>
        <span><i class="seg-pipe"></i>pipeline</span>
        <span><i class="seg-short"></i>short</span></div></div>
  </div>
  <div class="gutter" id="gutter" role="separator" aria-orientation="vertical" title="Drag to resize"></div>
  <div class="pane">
    <div class="pane-head headbar"><h3>Selected Release</h3><span class="spacer"></span>
      <div class="seg" id="viewtoggle"><span class="thumb"></span><button data-v="stack" class="on">&#9636; Stack</button><button data-v="flow">&#9655; Flow</button></div></div>
    <div class="runbar" id="runbar" style="display:none">
      <button class="btn" id="selAlloc" title="Select the viewed release's allocated containers">Select allocation</button>
      <span id="selCount" class="rcount">0 selected</span><span class="spacer"></span>
      <button class="btn rpush pc" id="pushPC" title="Push everything selected (checked releases + ticked containers) to PC, in selection order">Push &rarr; PC</button>
      <button class="btn rpush ec" id="pushEC" title="Push everything selected (checked releases + ticked containers) to EC, in selection order">Push &rarr; EC</button>
      <span class="rdiv"></span>
      <span id="draftCount" class="rcount" title="Draft runlist (not yet published)">draft: pc 0 &middot; ec 0</span>
      <button class="btn rpub" id="publishBtn" title="Publish the draft to the floor runlists">Publish</button>
      <span id="lockInfo" class="rlock"></span>
      <span id="ecNotice" class="ecnote" style="display:none"></span>
    </div>
    <div class="detailhead" id="detailhead"><span class="meta">Select a release&hellip;</span></div>
    <div class="pane-body" id="detailStack"></div>
    <div class="flowwrap" id="detailFlow" style="display:none"><div class="flowline" id="flowline"></div></div>
  </div>
</div>
<div id="pop"><div class="box"><h4>&#128230; Container detail</h4><div id="popbody"></div>
  <div class="note">Read-only &middot; Esc or click outside to close</div></div></div>
<div id="qtypop"><div class="box"><h4>Run quantity</h4><div id="qtybody"></div>
  <div class="qbtns" id="qtyChoices"></div>
  <div class="qrow2"><input type="number" id="qtyManual" min="0" placeholder="qty"><button class="btn" id="qtyManualBtn">Use qty</button></div>
  <div class="note">Required = allocated to this release &middot; Entire = whole container (surplus cascades to the next release) &middot; Esc to cancel</div>
</div></div>
<div id="editor"><div class="ebox">
  <div class="ehead"><h3>Runlist editor</h3><span id="edRev" class="erev" style="display:none"></span>
    <span class="spacer"></span>
    <button class="btn" id="edSave">Save order</button>
    <button class="btn rpub" id="edPublish">Confirm &amp; Publish</button>
    <button class="btn" id="edClose">Close</button></div>
  <div class="ebody">
    <div class="ecol"><div class="ecolhead"><span>PC runlist &mdash; drag to reorder</span><button class="btn edreset" id="resetPC" title="Discard unpublished edits — revert PC to the live floor list">Reset to live</button><button class="btn edclear" id="clearPC" title="Remove all PC items from the draft">Clear</button></div><div class="elist" id="edPC"></div></div>
    <div class="ecol"><div class="ecolhead"><span>EC runlist &mdash; drag to reorder</span><button class="btn edreset" id="resetEC" title="Discard unpublished edits — revert EC to the live floor list">Reset to live</button><button class="btn edclear" id="clearEC" title="Remove all EC items from the draft">Clear</button></div><div class="elist" id="edEC"></div></div>
  </div>
  <div class="ehint">Auto-added EC (amber) come from PC&rarr;EC deficit &mdash; review before publishing. Order drives the floor view. Auto-publishes every 10&nbsp;min while open.</div>
</div></div>
<div id="toasts" aria-live="polite"></div>
<script>
let PAYLOAD = __PAYLOAD__;
let SEL = null, VIEW = 'stack', custFilter = new Set(), colourFilter = new Set();
let RUNSEL = new Map();                   // serial -> {qty} selected for the runlist (current release)
let RELSEL = new Map();                   // releaseId -> release meta; whole releases ticked in the queue (ordered)
let condAny = {};                        // "Any" section: bucket -> 1 (has some) | -1 (has none); partial presence, all set chips AND
let condAll = {};                        // "All" section: bucket -> 1 (entire bar IS) | -1 (entire bar IS NOT); whole-bar, all set chips AND
let ecState = 0, pcState = 0;            // 0=off, 1=require, -1=exclude
let invP10 = false;                      // hide P6 releases with no P10 inventory in their routing
let DATES = [], dLo = 0, dHi = 0;        // ship-date range slider (indices into DATES)
const $ = s => document.querySelector(s);

function covBar(c,lg){const t=(c.pastPaint+c.paintable+c.pipeline+c.short)||1;
 return `<div class="cov ${lg?'lg':''}"><span class="seg-past" style="width:${c.pastPaint/t*100}%"></span>
 <span class="seg-paint" style="width:${c.paintable/t*100}%"></span>
 <span class="seg-pipe" style="width:${c.pipeline/t*100}%"></span>
 <span class="seg-short" style="width:${c.short/t*100}%"></span></div>`;}
function concernEl(t){return `<span class="concern ${t}" title="concern: ${t}"></span>`;}
// Yellow caution triangle (with "!") — flags a release whose oldest allocated stock is aging.
const CAUTION_ICON='<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path d="M8 1.4l6.7 11.6a.8.8 0 0 1-.7 1.2H2a.8.8 0 0 1-.7-1.2z" fill="#f2bf0b" stroke="#9a7a00" stroke-width=".8" stroke-linejoin="round"/><rect x="7.2" y="5.4" width="1.6" height="4.4" rx=".8" fill="#3a2e00"/><circle cx="8" cy="11.4" r="1" fill="#3a2e00"/></svg>';
// Queue stale-stock indicator: blank (<4 days old / no allocated stock) or a yellow caution
// sign (oldest allocated container >= 4 days old). The blank span still occupies the column.
function ageFlag(r){const a=r.oldestAddAgeDays;
 if(a==null||a<4)return '<span class="agewarn" aria-hidden="true"></span>';
 return `<span class="agewarn old" title="Oldest allocated stock ${a} days old">${CAUTION_ICON}</span>`;}
function paintBadge(p){if(!p)return '';if(p.type==='EC')return `<span class="pbadge"><span class="ec">EC</span></span>`;
 const sw=`<span class="swatch" style="background:${p.swatchHex};color:${p.glyphHex}" title="${p.colourName}">${p.colourInitials}</span>`;
 return p.type==='PC'?`<span class="pbadge">${sw}</span>`:`<span class="pbadge"><span class="ec">EC</span>${sw}</span>`;}
function pieStyle(s){if(s>=1)return 'background:var(--c-past)';if(s<=0)return 'background:#fff';
 return `background:conic-gradient(var(--c-past) 0 ${Math.round(s*100)}%,#fff 0)`;}

// Universal "content_copy" icon (two overlapping pages).
const COPY_ICON='<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path fill="currentColor" d="M15.5 1h-11A1.5 1.5 0 0 0 3 2.5V16h2V3h10.5V1zm3 4h-9A1.5 1.5 0 0 0 8 6.5v15A1.5 1.5 0 0 0 9.5 23h9A1.5 1.5 0 0 0 20 21.5v-15A1.5 1.5 0 0 0 18.5 5zM18 21H10V7h8v14z"/></svg>';
const CHECK_ICON='<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M3 8.4l3.2 3.2L13 4.4" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const X_ICON='<svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>';
// Refresh-button icons: spinner ring, and a check-in-a-circle for "Refreshed".
const SPINNER='<span class="spin"></span>';

// Transient notification overlay — appears, then auto-dismisses (no click needed).
// type: '' | 'ok' | 'warn' | 'err'.
function toast(msg,type,ms){
 const wrap=$('#toasts'); if(!wrap)return;
 const t=document.createElement('div'); t.className='toast '+(type||''); t.textContent=msg;
 wrap.appendChild(t); requestAnimationFrame(()=>t.classList.add('show'));
 setTimeout(()=>{t.classList.remove('show');setTimeout(()=>t.remove(),300);}, ms||4500);
}

// Global top loading bar (ref-counted) — replaces the per-button spinner / width
// animations, which felt sticky while a heavy render blocked the main thread.
let _loads=0;
function loadStart(){_loads++;const b=$('#loadbar');if(b)b.classList.add('on');}
function loadStop(){_loads=Math.max(0,_loads-1);if(!_loads){const b=$('#loadbar');if(b)b.classList.remove('on');}}

// Generic async action button: disable it + show the loading bar while *factory()* runs
// (no in-button animation). `label` / `opts.done` kept for call-site compatibility.
function btnRun(btn,label,factory,opts){
 opts=opts||{};
 if(!btn||btn._busy)return; btn._busy=true;
 btn.disabled=true; loadStart();
 // Yield two frames so the bar paints before any heavy synchronous work runs.
 requestAnimationFrame(()=>requestAnimationFrame(()=>{
   Promise.resolve().then(factory).catch(err=>{if(opts.onError)opts.onError(err);})
     .finally(()=>{loadStop();btn.disabled=false;btn._busy=false;});
 }));
}
const CHK_CIRCLE='<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="none" stroke="#fff" stroke-width="2"/><path d="M7 12.4l3.3 3.3L17 8.4" fill="none" stroke="#fff" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function fmtDate(iso){if(!iso)return '';const m=/^(\d{4})-(\d{2})-(\d{2})/.exec(iso);return m?m[2]+'-'+m[3]+'-'+m[1].slice(2):iso;}
// Oldest inventory add date among a release's allocated containers.
function addRange(lo,hi){if(!lo)return '';
 return `<span class="addr" title="Oldest inventory add date among allocated containers">Oldest Added: ${fmtDate(lo)}</span>`;}
function fallbackCopy(text,done){const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);done&&done();}
function copyPart(btn,part){
 const orig=btn.innerHTML, ttl=btn.title;
 const done=()=>{btn.classList.add('ok');btn.innerHTML=CHECK_ICON;btn.title='Copied '+part;
   setTimeout(()=>{btn.classList.remove('ok');btn.innerHTML=orig;btn.title=ttl;},900);};
 if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(part).then(done).catch(()=>fallbackCopy(part,done));
 else fallbackCopy(part,done);
}

function renderQueue(){
 const h=$('#queue');h.innerHTML='';
 const term=$('#search').value.trim().toLowerCase();
 let lastDay=null, shown=0;
 PAYLOAD.releases.forEach(r=>{
   if(custFilter.size && !custFilter.has(r.customer))return;
   if(invP10 && r.releasePlant==='P6' && !r.p10Inventory)return;
   if(DATES.length && r.shipDate && (r.shipDate < DATES[dLo] || r.shipDate > DATES[dHi]))return;
   const pt = r.paintBadge ? r.paintBadge.type : '';
   const isEC = pt==='EC'||pt==='EC+PC', isPC = pt==='PC'||pt==='EC+PC';
   if(ecState===1 && !isEC)return;
   if(ecState===-1 && isEC)return;
   if(pcState===1 && !isPC)return;
   if(pcState===-1 && isPC)return;
   if(colourFilter.size){
     const cn = r.paintBadge && r.paintBadge.colourName;
     if(!cn || !colourFilter.has(cn))return;
   }
   // "Any" (partial presence): every set chip must hold — 1 = has some qty, -1 = has none.
   for(const k in condAny){const has=(r.coverage[k]||0)>0;
     if(condAny[k]===1 && !has)return; if(condAny[k]===-1 && has)return;}
   // "All" (whole bar): the ENTIRE coverage bar IS (1) / IS NOT (-1) that bucket.
   {const tot=(r.coverage.pastPaint+r.coverage.paintable+r.coverage.pipeline+r.coverage.short)||0;
    for(const k in condAll){const isAll=tot>0 && (r.coverage[k]||0)===tot;
      if(condAll[k]===1 && !isAll)return; if(condAll[k]===-1 && isAll)return;}}
   if(term && !(r.part.toLowerCase().includes(term)||r.customer.toLowerCase().includes(term)))return;
   if(r.shipDate!==lastDay){const g=document.createElement('div');g.className='daygroup';g.textContent='Ship '+(fmtDate(r.shipDate)||'—');h.appendChild(g);lastDay=r.shipDate;}
   const d=document.createElement('div');d.className='qrow'+(SEL===r.naturalKey?' sel':'')+(RELSEL.has(r.releaseId)?' relsel':'')+(r.overdue?' overdue':'');
   d.dataset.rid=r.releaseId;
   d.innerHTML=`<label class="relselbox" title="Select this whole release for pushing"><input type="checkbox" class="relbox"${RELSEL.has(r.releaseId)?' checked':''}><span class="relnum"></span></label>${ageFlag(r)}<span class="cust" title="${r.customer}">${r.customer}</span>
     <span class="plant" title="Release Plant">${r.releasePlant||''}</span>
     <span class="pnwrap"><button class="copybtn" title="Copy part number" aria-label="Copy part number">${COPY_ICON}</button><span class="pn">${r.part}</span>${paintBadge(r.paintBadge)}${addRange(r.addDateLo,r.addDateHi)}</span>
     ${covBar(r.coverage)}<span class="date">${fmtDate(r.shipDate)}</span><span class="bal">${r.relBal}</span>`;
   d.onclick=()=>{SEL=r.naturalKey;document.querySelectorAll('.qrow').forEach(x=>x.classList.remove('sel'));d.classList.add('sel');loadDetail(r);};
   const cb=d.querySelector('.copybtn');if(cb)cb.addEventListener('click',e=>{e.stopPropagation();copyPart(cb,r.part);});
   const rb=d.querySelector('.relbox');if(rb){rb.addEventListener('click',e=>e.stopPropagation());
     rb.addEventListener('change',e=>{e.stopPropagation();toggleRel(r,rb.checked);});}
   h.appendChild(d);shown++;
 });
 paintRelNums();
 $('#count').textContent=shown+' / '+PAYLOAD.releaseCount;
 $('#datapulled').textContent='Data Pulled At: '+(PAYLOAD.dataPulledAt||'unknown');
 const _av=$('#appver');if(_av)_av.textContent=PAYLOAD.appVersion?('v'+PAYLOAD.appVersion):'';
 // Auto-select the first visible release so the detail pane is never empty.
 if(!SEL){const first=h.querySelector('.qrow');if(first)first.click();}
}

function renderCustPanel(){
 const p=$('#custPanel');
 p.innerHTML='<div class="filters">'+PAYLOAD.customers.map(c=>
   `<span class="chip ${custFilter.has(c)?'on':''}" data-c="${c}">${c}</span>`).join('')+'</div>';
 p.querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{
   const c=ch.dataset.c;custFilter.has(c)?custFilter.delete(c):custFilter.add(c);renderQueue();renderCustPanel();});
}
$('#custBtn').onclick=()=>{const p=$('#custPanel');p.style.display=p.style.display==='none'?'flex':'none';renderCustPanel();};
$('#search').oninput=renderQueue;
// Coverage condition chips — tri-state per bucket: off -> "is" (.on) -> "is not" (.neg "not …")
// -> off. Two sections, each AND-combining its set chips (and AND with each other): "Any" tests
// partial presence (has some / has none), "All" tests the whole bar (entire bar is / is not).
const COND_LABELS={pastPaint:'Past Paint',paintable:'WIP',pipeline:'Pipeline',short:'Short'};
function condMap(grp){return grp==='all'?condAll:condAny;}
function paintCondChip(ch){const m=condMap(ch.dataset.grp),s=m[ch.dataset.k]||0;
  ch.classList.toggle('on',s===1);ch.classList.toggle('neg',s===-1);
  const cl=ch.querySelector('.cl');if(cl)cl.textContent=(s===-1?'not ':'')+COND_LABELS[ch.dataset.k];}
function paintAllCondChips(){document.querySelectorAll('.chip.cond').forEach(paintCondChip);}
document.querySelectorAll('.chip.cond').forEach(ch=>ch.onclick=()=>{
  const m=condMap(ch.dataset.grp),k=ch.dataset.k,s=m[k]||0,n=(s===0?1:s===1?-1:0);
  if(n===0)delete m[k];else m[k]=n;
  paintCondChip(ch);renderQueue();});

// Paint-type (EC/PC) + colour filters.
function updateColourBtn(){
 // Colour filter is shown by default; hidden only when PC is set to *exclude* (R18).
 const showCol = pcState!==-1;
 $('#colourBtn').style.display = showCol ? 'inline-flex' : 'none';
 if(!showCol){colourFilter.clear();$('#colourPanel').style.display='none';}
}
// EC / PC are tri-state: click cycles off → require → exclude ("not …").
function paintChip(id,state,base){const el=$('#'+id);
 el.classList.toggle('on',state!==0);el.classList.toggle('neg',state===-1);
 el.textContent=state===-1?('not '+base):base;}
$('#ecChip').onclick=()=>{ecState=(ecState===0?1:ecState===1?-1:0);paintChip('ecChip',ecState,'EC');renderQueue();};
$('#pcChip').onclick=()=>{pcState=(pcState===0?1:pcState===1?-1:0);paintChip('pcChip',pcState,'PC');updateColourBtn();renderQueue();};
// "Inventory at P10": when on, hides P6 releases whose entire routing has no P10 inventory.
$('#invP10Chip').onclick=()=>{invP10=!invP10;$('#invP10Chip').classList.toggle('on',invP10);renderQueue();};

// Ship-date range slider (defaults to the full range = all releases visible).
function initDateSlider(){
 DATES=[...new Set(PAYLOAD.releases.map(r=>r.shipDate).filter(Boolean))].sort();
 const lo=$('#dLo'),hi=$('#dHi');
 if(DATES.length<2){lo.disabled=hi.disabled=true;dLo=0;dHi=Math.max(DATES.length-1,0);updateDateLabels();return;}
 lo.disabled=hi.disabled=false;
 lo.min=hi.min=0;lo.max=hi.max=DATES.length-1;lo.step=hi.step=1;
 dLo=0;dHi=DATES.length-1;lo.value=dLo;hi.value=dHi;updateDateLabels();
}
function updateDateLabels(){$('#dFrom').textContent=DATES[dLo]||'—';$('#dTo').textContent=DATES[dHi]||'—';}
$('#dLo').oninput=()=>{dLo=Math.min(+$('#dLo').value,dHi);$('#dLo').value=dLo;updateDateLabels();renderQueue();};
$('#dHi').oninput=()=>{dHi=Math.max(+$('#dHi').value,dLo);$('#dHi').value=dHi;updateDateLabels();renderQueue();};
$('#dReset').onclick=()=>{if(!DATES.length)return;dLo=0;dHi=DATES.length-1;$('#dLo').value=dLo;$('#dHi').value=dHi;updateDateLabels();renderQueue();};
function colourHexMap(){const m={};PAYLOAD.releases.forEach(r=>{const b=r.paintBadge;if(b&&b.colourName&&b.swatchHex)m[b.colourName]=b.swatchHex;});return m;}
function colourList(){return [...new Set(PAYLOAD.releases.filter(r=>r.paintBadge&&['PC','EC+PC'].includes(r.paintBadge.type)&&r.paintBadge.colourName&&r.paintBadge.colourName!=='Unknown').map(r=>r.paintBadge.colourName))].sort();}
function renderColourPanel(){
 const cols=colourList(), hex=colourHexMap();
 $('#colourPanel').innerHTML='<div class="filters">'+(cols.length?cols.map(c=>
   `<span class="chip ${colourFilter.has(c)?'on':''}" data-col="${c}"><span style="display:inline-block;width:12px;height:12px;border-radius:3px;border:1px solid rgba(0,0,0,.25);background:${hex[c]||'#9aa0a8'}"></span>${c}</span>`).join('')
   :'<span style="font-size:11px;color:var(--muted)">no powder colours in current data</span>')+'</div>';
 $('#colourPanel').querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{
   const c=ch.dataset.col;colourFilter.has(c)?colourFilter.delete(c):colourFilter.add(c);renderQueue();renderColourPanel();});
}
$('#colourBtn').onclick=()=>{const p=$('#colourPanel');p.style.display=p.style.display==='none'?'flex':'none';renderColourPanel();};

function cardHTML(c,o){
 if(c.isReworkMrb)return '';
 const sid=String(c.serial), sel=RUNSEL.has(sid);
 // Grey containers consumed by another release (not free for this one) — R20.
 const elsewhere = c.allocatedElsewhere && c.allocatedHere===0;
 return `<div class="ccard ${c.pastPaint?'past':''} ${sel?'sel':''} ${elsewhere?'elsewhere':''}" data-serial="${sid}"${elsewhere?' title="Allocated to another release"':''}>
   <input type="checkbox" class="selbox" data-serial="${sid}" ${sel?'checked':''} title="Select for runlist">
   <span class="corner"></span>
   <div class="cardmain" data-serial="${sid}"><div class="sn">${c.serial}</div><div class="loc">${c.location}</div>
   <div class="qty">${c.allocatedHere}/${c.qty}</div></div></div>`;
}
function mrbCardHTML(op){
 if(!op.reworkCards.length)return '';
 return `<div class="ccard mrb" onclick='showMrb(${JSON.stringify(op.reworkCards).replace(/'/g,"&#39;")})'>MRB Qty: ${op.reworkQty}</div>`;
}
function subHTML(sub){
 const inner=sub.ops.map(o=>`<div class="oprow"><div class="ophead"><span class="caret">&#9662;</span>
   <span class="opname">${o.op}</span><span class="opnet">${o.netQty}<small> net</small></span>
   <span class="pie" style="margin-left:8px;${pieStyle(o.pastPaintShare)}"></span></div></div>`).join('');
 return `<div class="subroute"><div class="subhead" onclick="this.parentNode.classList.toggle('open')">
   <span class="caret">&#9662;</span><span class="lbl">${sub.partNo}</span><span class="xq">net ${sub.bomScaledNet}</span>
   <span style="flex:1;max-width:150px">${covBar(sub.coverage)}</span>${concernEl(sub.concernAuto)}</div>
   <div class="innerops">${inner}</div></div>`;
}
function renderStack(detail){
 const h=$('#detailStack');
 window._cards={};
 detail.ops.forEach(o=>o.containers.forEach(c=>{if(!c.isReworkMrb)window._cards[String(c.serial)]={
   serial:String(c.serial),partNo:c.part,location:c.location,qty:c.qty,allocatedHere:c.allocatedHere,
   part:c.part,op:o.op,seq:o.seq,raw:c};}));
 h.innerHTML=detail.ops.map(o=>{
   const cards=o.containers.map(c=>cardHTML(c,o)).join('')+mrbCardHTML(o);
   const subs=o.subRoutings.map(subHTML).join('');
   return `<div class="oprow ${o.collapsed?'collapsed up':''}">
     <div class="ophead ${o.isPaintOp?'paint':''}" onclick="this.parentNode.classList.toggle('collapsed')">
       <span class="caret">&#9662;</span><span class="opname">${o.op}</span>
       <span class="opnet">${o.netQty}<small> net</small></span>
       <span class="pie" style="${pieStyle(o.pastPaintShare)}" title="past-paint share"></span>
       <span class="spacer"></span>${o.isPaintOp?'<span class="tag-paint">PAINT</span>':''}</div>
     <div class="cardstrip">${cards||'<span class="note">no containers</span>'}</div>${subs}</div>`;
 }).join('');
 h.querySelectorAll('.selbox').forEach(cb=>cb.onchange=()=>onSelToggle(cb.dataset.serial,cb));
 h.querySelectorAll('.cardmain').forEach(m=>m.onclick=()=>{const c=window._cards[m.dataset.serial];if(c)showPop(c.raw);});
 updateSelCount();
}
function renderFlow(detail){
 const stages=[...detail.ops].reverse();
 $('#flowline').innerHTML=stages.map(o=>{
   const minis=o.containers.map(c=>`<div class="fmini ${c.pastPaint?'past':''} ${(c.allocatedElsewhere&&c.allocatedHere===0)?'elsewhere':''}"${(c.allocatedElsewhere&&c.allocatedHere===0)?' title="Allocated to another release"':''} onclick='showPop(${JSON.stringify(c).replace(/'/g,"&#39;")})'>${c.serial} &middot; ${c.allocatedHere}/${c.qty}</div>`).join('')
     +(o.reworkCards.length?`<div class="fmini mrb">MRB ${o.reworkQty}</div>`:'');
   const branch=o.subRoutings.map(s=>`<div class="fbranch"><div class="bl">&#8627; ${s.partNo}</div><div style="font-size:9.5px;color:var(--muted)">net ${s.bomScaledNet}</div>${covBar(s.coverage)}</div>`).join('');
   return `<div class="fstage ${o.collapsed?'up':''} ${o.isPaintOp?'paint':''}">
     <div class="fname">${o.op}${o.isPaintOp?' <span class="tag-paint">P</span>':''}</div>
     <div class="fnet">net ${o.netQty}</div>${minis||'<div class="note" style="font-size:10px">—</div>'}${branch}</div>`;
 }).join('');
}
function loadDetail(r){
 window._rel=r;RUNSEL=new Map();
 $('#runbar').style.display='flex';
 $('#detailhead').innerHTML=`${concernEl(r.concernAuto)}<span class="pn">${r.part}</span>${paintBadge(r.paintBadge)}
   <span class="meta">${r.customer} &middot; ship ${r.shipDate} &middot; <b>Bal ${r.relBal}</b></span>
   <span class="spacer"></span><span style="min-width:140px">${covBar(r.coverage)}</span>`;
 $('#detailStack').innerHTML='<div class="empty">loading&hellip;</div>';
 fetch('/detail?rid='+encodeURIComponent(r.releaseId)).then(x=>x.json()).then(d=>{
   if(d.error){$('#detailStack').innerHTML='<div class="empty">'+d.error+'</div>';return;}
   window._detail=d;renderStack(d);renderFlow(d);updateRunbar();
 });
}

// ---- Runlist authoring (planner): select containers, set qty, push to draft, publish ----
function markCard(serial,on){const el=document.querySelector('.ccard[data-serial="'+CSS.escape(serial)+'"]');if(el)el.classList.toggle('sel',on);}
// Whole-release selection (queue checkboxes), ordered by tick order.
function toggleRel(r,on){
 if(on)RELSEL.set(r.releaseId,{releaseId:r.releaseId,naturalKey:r.naturalKey,part:r.part,customer:r.customer,shipDate:r.shipDate,paintBadge:r.paintBadge});
 else RELSEL.delete(r.releaseId);
 paintRelNums();updateSelCount();const rb=$('#runbar');if(rb)rb.style.display='flex';
}
// Repaint each visible queue row's checkbox + selection-order badge (1-based, tick order).
function paintRelNums(){const keys=[...RELSEL.keys()];
 document.querySelectorAll('#queue .qrow').forEach(row=>{const rid=row.dataset.rid?+row.dataset.rid:null;
   const box=row.querySelector('.relbox'),num=row.querySelector('.relnum'),on=RELSEL.has(rid);
   if(box)box.checked=on;row.classList.toggle('relsel',on);
   if(num)num.textContent=on?(keys.indexOf(rid)+1):'';});}
// Combined selection summary: N whole releases + M loose containers (current release only).
function updateSelCount(){const n=$('#selCount');if(!n)return;
 const rel=RELSEL.size, con=(window._rel&&!RELSEL.has(window._rel.releaseId))?RUNSEL.size:0;
 const p=[];if(rel)p.push(rel+' release'+(rel===1?'':'s'));if(con)p.push(con+' container'+(con===1?'':'s'));
 n.textContent=p.length?p.join(' · ')+' selected':'0 selected';}
function onSelToggle(serial,cb){
 const c=window._cards&&window._cards[serial]; if(!c){cb.checked=false;return;}
 if(!cb.checked){RUNSEL.delete(serial);markCard(serial,false);updateSelCount();return;}
 if(c.allocatedHere<c.qty){openQty(c,cb);}                      // engine-partial → ask qty (R8)
 else{RUNSEL.set(serial,{qty:c.allocatedHere});markCard(serial,true);updateSelCount();}
}
let _qtyCtx=null;
function openQty(c,cb){
 _qtyCtx={serial:c.serial,cb:cb};
 $('#qtybody').innerHTML='<div style="font-size:12.5px;color:var(--muted);margin-bottom:8px">Container <b style="font-family:var(--mono);color:var(--ink)">'+c.serial+'</b> &middot; allocated '+c.allocatedHere+' of '+c.qty+'</div>';
 $('#qtyChoices').innerHTML='<button class="btn" data-q="'+c.allocatedHere+'">Required ('+c.allocatedHere+')</button>'
   +'<button class="btn" data-q="'+c.qty+'">Entire ('+c.qty+')</button>';
 $('#qtyChoices').querySelectorAll('button').forEach(b=>b.onclick=()=>setQty(+b.dataset.q));
 $('#qtyManual').value='';$('#qtypop').classList.add('show');setTimeout(()=>$('#qtyManual').focus(),50);
}
function setQty(q){if(!_qtyCtx)return;q=Math.max(0,Math.floor(q||0));
 RUNSEL.set(_qtyCtx.serial,{qty:q});markCard(_qtyCtx.serial,true);if(_qtyCtx.cb)_qtyCtx.cb.checked=true;
 closeQty();updateSelCount();}
function cancelQty(){if(_qtyCtx&&_qtyCtx.cb)_qtyCtx.cb.checked=false;closeQty();}
function closeQty(){$('#qtypop').classList.remove('show');_qtyCtx=null;}
$('#qtyManualBtn').onclick=()=>setQty(+$('#qtyManual').value);
$('#qtyManual').addEventListener('keydown',e=>{if(e.key==='Enter')setQty(+$('#qtyManual').value);});
$('#qtypop').onclick=e=>{if(e.target.id==='qtypop')cancelQty();};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('#qtypop').classList.contains('show'))cancelQty();});
$('#selAlloc').onclick=()=>{if(!window._cards)return;RUNSEL=new Map();
 Object.values(window._cards).forEach(c=>{if(c.allocatedHere>0)RUNSEL.set(c.serial,{qty:c.allocatedHere});});
 renderStack(window._detail);};
function buildItems(target){
 const r=window._rel,d=window._detail; if(!r||!d)return [];
 const colour=(r.paintBadge&&r.paintBadge.colourName)||'';
 let qseq=null;
 d.ops.forEach(o=>{const up=String(o.op).toUpperCase();
   if(o.isPaintOp){if(target==='pc'&&up.includes('PC'))qseq=o.seq;if(target==='ec'&&up.includes('EC')&&qseq===null)qseq=o.seq;}});
 const items=[];
 RUNSEL.forEach((sel,serial)=>{const c=window._cards[serial];if(!c||!(sel.qty>0))return;
   items.push({partNo:c.partNo,serial:c.serial,location:c.location,allocQty:sel.qty,
     releaseId:r.releaseId,customer:r.customer,shipDate:r.shipDate,
     powderColour:target==='pc'?colour:'',part:c.part,queuedPaintSeq:qseq});});
 return items;
}
// Build the full-required-allocation items for one release from its detail tree (mirrors the
// "Select allocation" → push path: every allocated container at its allocatedHere qty).
function allocItemsFromDetail(d,r,target){
 const colour=(r.paintBadge&&r.paintBadge.colourName)||'';
 let qseq=null;
 d.ops.forEach(o=>{const up=String(o.op).toUpperCase();
   if(o.isPaintOp){if(target==='pc'&&up.includes('PC'))qseq=o.seq;if(target==='ec'&&up.includes('EC')&&qseq===null)qseq=o.seq;}});
 const cards={};
 d.ops.forEach(o=>o.containers.forEach(c=>{if(!c.isReworkMrb)cards[String(c.serial)]={serial:String(c.serial),part:c.part,location:c.location,allocatedHere:c.allocatedHere};}));
 const items=[];
 Object.values(cards).forEach(c=>{const aq=+c.allocatedHere||0;if(aq>0)items.push({partNo:c.part,serial:c.serial,location:c.location,
   allocQty:aq,releaseId:r.releaseId,customer:r.customer,shipDate:r.shipDate,
   powderColour:target==='pc'?colour:'',part:c.part,queuedPaintSeq:qseq});});
 return items;
}
function pushItems(target,items){
 if(!items.length)return Promise.resolve({added:0,skipped:0,ecAutoAdded:0});
 return fetch('/runlist/push',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:target,items:items})})
  .then(x=>x.json()).then(res=>{if(res.error)throw new Error(res.error);return res;});
}
function hasSelection(){const r=window._rel;
 return RELSEL.size>0 || (r&&RUNSEL.size>0&&!RELSEL.has(r.releaseId));}
// Push everything selected — checked whole releases (in tick order) + the viewed release's ticked
// containers — as sequential per-release pushes so the engine's cascade/PC→EC deficit stay correct.
async function pushSelection(target){
 let added=0,skipped=0,ecAuto=0;
 for(const rid of RELSEL.keys()){
   const rel=RELSEL.get(rid);
   const d=await fetch('/detail?rid='+encodeURIComponent(rid)).then(x=>x.json());
   if(d.error)continue;
   const res=await pushItems(target,allocItemsFromDetail(d,rel,target));
   added+=res.added||0;skipped+=res.skipped||0;ecAuto+=res.ecAutoAdded||0;
 }
 const r=window._rel;
 if(r&&RUNSEL.size&&!RELSEL.has(r.releaseId)){
   const res=await pushItems(target,buildItems(target));
   added+=res.added||0;skipped+=res.skipped||0;ecAuto+=res.ecAutoAdded||0;
 }
 const n=$('#ecNotice');
 if(n){if(target==='pc'&&ecAuto>0){n.style.display='inline-block';n.textContent='⚠ '+ecAuto+' EC auto-added — review';}else if(target==='pc'){n.style.display='none';n.textContent='';}}
 if(skipped>0)toast(skipped+' container'+(skipped===1?'':'s')+' skipped — already at/past the '+target.toUpperCase()+' op.','warn');
 toast('Pushed '+added+' container'+(added===1?'':'s')+' to '+target.toUpperCase()+'.','ok');
 RELSEL=new Map();RUNSEL=new Map();paintRelNums();
 if(window._detail)renderStack(window._detail);
 updateRunbar();
}
function onPush(e,target){
 if(!hasSelection()){toast('Nothing selected — tick releases in the queue or containers in the detail.','warn');return;}
 btnRun(e.currentTarget,'Pushing',()=>pushSelection(target),{done:'Pushed',onError:err=>alert('Push failed: '+err.message)});
}
$('#pushPC').onclick=e=>onPush(e,'pc');
$('#pushEC').onclick=e=>onPush(e,'ec');
$('#publishBtn').onclick=e=>btnRun(e.currentTarget,'Publishing',()=>
 fetch('/runlist/publish',{method:'POST'}).then(x=>x.json()).then(res=>{
   if(res.ok){updateRunbar();return;}
   const o=res.owner||{};throw new Error('owned by '+((o.user||'another planner'))+(o.machine?(' @'+o.machine):''));
 }),{done:'Published',onError:err=>alert('Cannot publish — runlist is '+err.message+'.')});
function updateRunbar(){
 updateSelCount();
 fetch('/runlist/draft.json').then(x=>x.json()).then(d=>{$('#draftCount').textContent='draft: pc '+((d.pc||[]).length)+' · ec '+((d.ec||[]).length);}).catch(()=>{});
 fetch('/runlist/lock').then(x=>x.json()).then(d=>{const o=d.owner;const txt=o?('lock: '+(d.mine?'you':((o.user||'?')+'@'+(o.machine||'?')))):'';$('#lockInfo').textContent=txt;}).catch(()=>{});
}

// ---- Runlist reorder editor: grouped drag-and-drop + publish + auto-publish ----
// EDIT holds the working order for each list (array of run-item dicts). Group headers
// (PC: colour → part; EC: part) are *derived* from this order on every render, so dragging
// freely re-groups on drop (§2.4). The flat item order is what we persist via /runlist/reorder.
const EDIT={pc:[],ec:[]};
const edSel=new Set();                     // runItemIds selected (checkboxes) for per-item delete
const LISTEL={pc:'edPC',ec:'edEC'};
const COLL={pc:new Set(),ec:new Set()};   // collapsed group keys per list (click a header to toggle)
let _edTimer=null,_edPoll=null,DRAG=null;

function openEditor(){window._colHex=colourHexMap();$('#editor').classList.add('show');loadEditor();
 if(_edTimer)clearInterval(_edTimer);_edTimer=setInterval(()=>edPublish(true),600000); // auto-publish every 10 min
 if(_edPoll)clearInterval(_edPoll);_edPoll=setInterval(pollEditorDraft,20000);}         // reflect reconcile removals
function closeEditor(){$('#editor').classList.remove('show');
 if(_edTimer){clearInterval(_edTimer);_edTimer=null;} if(_edPoll){clearInterval(_edPoll);_edPoll=null;}}
function loadEditor(){fetch('/runlist/draft.json').then(x=>x.json()).then(applyEditorData).catch(()=>{});}
function applyEditorData(d){
 EDIT.pc=(d.pc||[]).slice();EDIT.ec=(d.ec||[]).slice();
 // Drop selections for items no longer in the draft (deleted / reconciled away).
 const live=new Set([...EDIT.pc,...EDIT.ec].map(it=>it.runItemId));
 [...edSel].forEach(id=>{if(!live.has(id))edSel.delete(id);});
 renderEdList('pc');renderEdList('ec');updateReviewNote();
}
// Review banner counts auto-added EC that the planner has not yet acknowledged (§13).
function updateReviewNote(){const autos=EDIT.ec.filter(i=>i.source==='auto-ec-deficit'&&!i.acknowledged).length;
 const rev=$('#edRev');if(autos>0){rev.style.display='inline-block';rev.textContent='⚠ '+autos+' auto-added EC — review';}else{rev.style.display='none';}}
function swat(col){const h=(window._colHex||{})[col];return h?`<span class="gsw" style="background:${h}"></span>`:'';}
// Item row shows Serial · Location · Qty only — the part number lives in the group header.
// Auto-added EC carry a checkmark to acknowledge (clears the amber + the review banner).
function eitemHTML(it,isPC,hide){const isAuto=it.source==='auto-ec-deficit',amber=isAuto&&!it.acknowledged;
 // Checkmark only while it still needs review; once acknowledged it's gone (no residual indicator).
 const ack=amber?`<button class="eack" data-ack="${esc(it.runItemId)}" title="Acknowledge this auto-added EC">${CHECK_ICON}</button>`:'';
 const sel=edSel.has(it.runItemId);
 return `<div class="eitem ${amber?'auto':''} ${sel?'selrow':''} ${isPC?'':'econly'} ${hide?'ehide':''}" draggable="true" data-id="${esc(it.runItemId)}">
  <input type="checkbox" class="edsel" data-id="${esc(it.runItemId)}"${sel?' checked':''} title="Select for delete">
  <span class="es">${esc(it.serial)}</span><span style="color:var(--faint)">${esc(it.location||'')}</span>
  <span class="eq">${it.allocQty}</span>${ack}</div>`;}
function ackItem(listKey,id){const it=EDIT[listKey].find(x=>x.runItemId===id);if(!it)return;
 const next=!it.acknowledged;
 fetch('/runlist/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({runItemId:id,acknowledged:next})})
  .then(x=>x.json()).then(r=>{if(r&&r.ok===false)return;it.acknowledged=next;renderEdList(listKey);updateReviewNote();}).catch(()=>{});}
function chunkQty(items,start,grp,isPC){
 const col=items[start].powderColour||'Unknown',part=items[start].partNo||'—';let q=0;
 for(let j=start;j<items.length;j++){const c=items[j].powderColour||'Unknown',p=items[j].partNo||'—';
   if(grp==='colour'){if(isPC&&c!==col)break;}else{if((isPC&&c!==col)||p!==part)break;}
   q+=(+items[j].allocQty||0);}
 return q;}
function renderEdList(listKey){
 const el=$('#'+LISTEL[listKey]),items=EDIT[listKey]||[],isPC=listKey==='pc',coll=COLL[listKey];
 if(!items.length){el.innerHTML='<div class="empty" style="padding:18px">empty</div>';return;}
 // Collapsed groups keep their rows in the DOM (class `ehide`, display:none) so a header drag
 // still carries them and commitOrder still sees every item — they are only visually hidden.
 let html='',curCol=null,curPart=null,colDead=false,partDead=false;
 for(let i=0;i<items.length;i++){const it=items[i],col=it.powderColour||'Unknown',part=it.partNo||'—';
   if(isPC&&col!==curCol){curCol=col;curPart=null;
     const ck='c:'+col;colDead=coll.has(ck);
     html+=`<div class="ehdr colhdr ${colDead?'collapsed':''}" draggable="true" data-grp="colour" data-key="${esc(col)}" data-ckey="${esc(ck)}"><span class="caret">▾</span><span class="ghandle">⠿</span>${swat(col)}<span>${esc(col)}</span><span class="ecount">${chunkQty(items,i,'colour',isPC)}</span></div>`;}
   if(part!==curPart){curPart=part;
     const pk=isPC?('p:'+col+'/'+part):('p:'+part);partDead=coll.has(pk);
     html+=`<div class="ehdr parthdr ${isPC?'':'econly'} ${partDead?'collapsed':''} ${colDead?'ehide':''}" draggable="true" data-grp="part" data-key="${esc(part)}" data-ckey="${esc(pk)}"><span class="caret">▾</span><span class="ghandle">⠿</span><span>${esc(part)}</span><span class="ecount">${chunkQty(items,i,'part',isPC)}</span></div>`;}
   html+=eitemHTML(it,isPC,colDead||partDead);
 }
 el.innerHTML=html;
 updateDeleteBtns();
}
// Each pane's button deletes the selected items in that pane, or — with nothing selected —
// clears the whole pane. Label/title reflect which.
function updateDeleteBtns(){['pc','ec'].forEach(k=>{
  const b=document.getElementById('clear'+k.toUpperCase());if(!b)return;
  const n=(EDIT[k]||[]).filter(it=>edSel.has(it.runItemId)).length;
  b.textContent=n?('Delete ('+n+')'):'Clear';
  b.title=n?('Delete the '+n+' selected '+k.toUpperCase()+' item(s) from the draft')
           :('Remove all '+k.toUpperCase()+' items from the draft');});}
// A group header drags its whole chunk: a colour chunk runs to the next colour header; a
// part chunk runs to the next header of any kind.
function chunkNodes(hdr){const grp=hdr.dataset.grp,out=[hdr];let n=hdr.nextElementSibling;
 while(n){if(n.classList.contains('ehdr')){if(grp==='colour'){if(n.classList.contains('colhdr'))break;}else break;}
   out.push(n);n=n.nextElementSibling;}
 return out;}
// FLIP: animate every row from its pre-move position to its post-move position (make-space, §2.3).
function flip(list,mover){
 const f=new Map();[...list.children].forEach(k=>f.set(k,k.getBoundingClientRect().top));
 mover();
 [...list.children].forEach(k=>{const o=f.get(k);if(o==null)return;const dy=o-k.getBoundingClientRect().top;
   if(dy){k.style.transition='none';k.style.transform='translateY('+dy+'px)';
     requestAnimationFrame(()=>{k.style.transition='';k.style.transform='';});}});
}
function commitOrder(listKey){
 const ids=[...$('#'+LISTEL[listKey]).querySelectorAll('.eitem')].map(e=>e.dataset.id);
 const by={};EDIT[listKey].forEach(it=>by[it.runItemId]=it);
 EDIT[listKey]=ids.map(id=>by[id]).filter(Boolean);
 renderEdList(listKey);   // re-derive headers from the new order
 saveOrder(listKey);
}
function wireEditorDnD(listKey){
 const list=$('#'+LISTEL[listKey]);
 list.addEventListener('dragstart',e=>{if(e.target.classList&&e.target.classList.contains('edsel'))return; // checkbox, not a drag
   const row=e.target.closest('.eitem,.ehdr');if(!row||!list.contains(row))return;
   const nodes=row.classList.contains('ehdr')?chunkNodes(row):[row];
   DRAG={list:listKey,nodes};nodes.forEach(n=>n.classList.add('drag'));list.classList.add('dragging');
   e.dataTransfer.effectAllowed='move';try{e.dataTransfer.setData('text/plain',row.dataset.id||row.dataset.key||'');}catch(_){}});
 list.addEventListener('dragover',e=>{if(!DRAG||DRAG.list!==listKey)return;e.preventDefault();
   const over=e.target.closest('.eitem,.ehdr');if(!over||!list.contains(over)||DRAG.nodes.indexOf(over)>=0)return;
   const r=over.getBoundingClientRect(),after=(e.clientY-r.top)>r.height/2;
   let ref=after?over.nextElementSibling:over;
   if(ref&&DRAG.nodes.indexOf(ref)>=0)return;
   flip(list,()=>{DRAG.nodes.forEach(n=>list.insertBefore(n,ref));});});
 const finish=()=>{if(!DRAG||DRAG.list!==listKey)return;
   DRAG.nodes.forEach(n=>n.classList.remove('drag'));list.classList.remove('dragging');DRAG=null;
   list._noclick=true;setTimeout(()=>{list._noclick=false;},60);   // suppress the post-drag click
   commitOrder(listKey);};
 list.addEventListener('drop',e=>{e.preventDefault();finish();});
 list.addEventListener('dragend',finish);
 // Selection checkboxes (per-item delete). Toggle the row highlight + refresh button labels.
 list.addEventListener('change',e=>{const cb=e.target.closest('.edsel');if(!cb)return;
   const id=cb.dataset.id; if(cb.checked)edSel.add(id);else edSel.delete(id);
   const row=cb.closest('.eitem');if(row)row.classList.toggle('selrow',cb.checked);
   updateDeleteBtns();});
 // Acknowledge an auto-added EC (checkmark), or collapse/expand a group header (not a drag).
 list.addEventListener('click',e=>{if(list._noclick)return;
   const a=e.target.closest('.eack');if(a){e.stopPropagation();ackItem(listKey,a.dataset.ack);return;}
   const h=e.target.closest('.ehdr');if(!h||!list.contains(h))return;
   const k=h.dataset.ckey;if(!k)return;COLL[listKey].has(k)?COLL[listKey].delete(k):COLL[listKey].add(k);renderEdList(listKey);});
}
function saveOrder(listKey){return fetch('/runlist/reorder',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({target:listKey,order:EDIT[listKey].map(i=>i.runItemId)})}).then(()=>updateRunbar()).catch(()=>{});}
function saveAll(){return Promise.all([saveOrder('pc'),saveOrder('ec')]);}
function edPublish(auto){return saveAll().then(()=>fetch('/runlist/publish',{method:'POST'}).then(x=>x.json()).then(res=>{
  if(res.ok){updateRunbar();return;}
  if(!auto){const o=res.owner||{};throw new Error('owned by '+((o.user||'another planner'))+(o.machine?(' @'+o.machine):''));}
 }));}
// Reflect reconcile removals in the open editor: animate run containers out, then re-render.
function pollEditorDraft(){if(DRAG)return;fetch('/runlist/draft.json').then(x=>x.json()).then(d=>{
  if(DRAG)return;['pc','ec'].forEach(k=>reconcileEditorList(k,d[k]||[]));}).catch(()=>{});}
function reconcileEditorList(k,newItems){
  const newById={};newItems.forEach(it=>newById[it.runItemId]=it);
  const removed=EDIT[k].filter(it=>!newById[it.runItemId]);
  const qtyChanged=EDIT[k].some(it=>{const n=newById[it.runItemId];return n&&(+n.allocQty)!==(+it.allocQty);});
  if(!removed.length&&!qtyChanged&&newItems.length===EDIT[k].length)return;
  if(removed.length){removed.forEach(it=>{const el=$('#'+LISTEL[k]+' .eitem[data-id="'+CSS.escape(it.runItemId)+'"]');if(el)el.classList.add('removing');});
    setTimeout(()=>{EDIT[k]=newItems.slice();renderEdList(k);},420);}
  else{EDIT[k]=newItems.slice();renderEdList(k);}
}
function clearTarget(target){
 return fetch('/runlist/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:target})})
  .then(x=>x.json()).then(()=>{loadEditor();updateRunbar();});
}
function deleteItems(target,ids){
 return fetch('/runlist/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:target,ids:ids})})
  .then(x=>x.json()).then(()=>{ids.forEach(id=>edSel.delete(id));loadEditor();updateRunbar();});
}
function resetTarget(target){
 return fetch('/runlist/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:target})})
  .then(x=>x.json()).then(()=>{loadEditor();updateRunbar();});
}
function onClear(e,target){
 // With items selected in this pane, delete just those; otherwise clear the whole pane.
 const ids=(EDIT[target]||[]).filter(it=>edSel.has(it.runItemId)).map(it=>it.runItemId);
 if(ids.length){btnRun(e.currentTarget,'Deleting',()=>deleteItems(target,ids),{done:'Deleted'});return;}
 if(!confirm('Remove all '+target.toUpperCase()+' items from the draft? (does not affect the published floor view until you publish)'))return;
 btnRun(e.currentTarget,'Clearing',()=>clearTarget(target),{done:'Cleared'});}
function onReset(e,target){if(!confirm('Reset '+target.toUpperCase()+' to the live published list? Any unpublished edits to this list are discarded.'))return;
 btnRun(e.currentTarget,'Resetting',()=>resetTarget(target),{done:'Reset'});}
$('#clearPC').onclick=e=>onClear(e,'pc');
$('#clearEC').onclick=e=>onClear(e,'ec');
$('#resetPC').onclick=e=>onReset(e,'pc');
$('#resetEC').onclick=e=>onReset(e,'ec');
$('#edSave').onclick=e=>btnRun(e.currentTarget,'Saving',()=>saveAll(),{done:'Saved'});
$('#edPublish').onclick=e=>btnRun(e.currentTarget,'Publishing',()=>edPublish(false),{done:'Published',onError:err=>alert('Cannot publish — runlist '+err.message+'.')});
$('#edClose').onclick=closeEditor;
$('#openEditor').onclick=openEditor;
$('#editor').addEventListener('click',e=>{if(e.target.id==='editor')closeEditor();});
wireEditorDnD('pc');wireEditorDnD('ec');
document.querySelectorAll('#viewtoggle button').forEach(b=>b.onclick=()=>{
 if(b.classList.contains('on'))return;
 document.querySelectorAll('#viewtoggle button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
 VIEW=b.dataset.v;const flow=VIEW==='flow';
 $('#viewtoggle').classList.toggle('flow',flow);          // slide the thumb (200ms)
 const show=flow?$('#detailFlow'):$('#detailStack'), hide=flow?$('#detailStack'):$('#detailFlow');
 hide.style.display='none';show.style.display=flow?'flex':'block';
 show.classList.remove('vfade');void show.offsetWidth;show.classList.add('vfade');  // quick fade-in (200ms)
});

// --- Draggable splitter: resize the release (left) pane; right takes the rest. ---
(function(){
 const tp=document.querySelector('.twopane'), gut=$('#gutter');
 const MIN_LEFT=440, MIN_RIGHT=340, GUT=10;
 const clamp=w=>{const max=tp.clientWidth-24-GUT-MIN_RIGHT;return Math.max(MIN_LEFT,Math.min(Math.max(max,MIN_LEFT),w));};
 const setW=w=>tp.style.setProperty('--leftw',clamp(w)+'px');
 // init from saved width, else the current rendered left-pane width
 let init;try{init=parseFloat(localStorage.getItem('paintLeftW'));}catch(e){}
 if(!init)init=document.querySelector('.pane').getBoundingClientRect().width;
 setW(init);
 let dragging=false,startX=0,startW=0;
 gut.addEventListener('pointerdown',e=>{dragging=true;startX=e.clientX;
   startW=document.querySelector('.pane').getBoundingClientRect().width;
   gut.classList.add('drag');document.body.classList.add('resizing');
   gut.setPointerCapture(e.pointerId);e.preventDefault();});
 gut.addEventListener('pointermove',e=>{if(dragging)setW(startW+(e.clientX-startX));});
 const end=()=>{if(!dragging)return;dragging=false;gut.classList.remove('drag');document.body.classList.remove('resizing');
   try{localStorage.setItem('paintLeftW',parseFloat(tp.style.getPropertyValue('--leftw')));}catch(e){}};
 gut.addEventListener('pointerup',end);gut.addEventListener('pointercancel',end);
 window.addEventListener('resize',()=>{const cur=parseFloat(tp.style.getPropertyValue('--leftw'));if(cur)setW(cur);});
})();
function showPop(c){
 $('#popbody').innerHTML=[['Serial',c.serial],['Part',c.part],['Location',c.location],
  ['Alloc Qty',c.allocatedHere],['Container Qty',c.qty],['Add Date',c.addDate||'—'],
  ['Inventory Plant',c.containerPlant||'—'],['Next Op',c.nextOp||'—']]
  .map(([k,v])=>`<div class="frow"><span>${k}</span><b>${v}</b></div>`).join('');
 $('#pop').classList.add('show');
}
function showMrb(cards){
 $('#popbody').innerHTML='<div style="font-weight:600;margin-bottom:6px">Rework / MRB ('+cards.length+')</div>'+
  cards.map(c=>`<div class="frow"><span>${c.serial} &middot; ${c.location} <small>(${c.status||'MRB'})</small></span><b>0/${c.qty}</b></div>`).join('');
 $('#pop').classList.add('show');
}
$('#pop').onclick=e=>{if(e.target.id==='pop')e.currentTarget.classList.remove('show');};
document.addEventListener('keydown',e=>{if(e.key==='Escape')$('#pop').classList.remove('show');});
const RB=$('#refresh'), RIC=RB.querySelector('.ricon'), RLB=RB.querySelector('.rlabel');
// No width-morphing transition (the forced double-reflow felt sticky during heavy
// renders). Just a label/icon swap + the global loading bar; width changes follow
// naturally via the button's own CSS transition.
let refreshing=false;
function refreshIdle(){RB.classList.remove('done','fail','busy');RIC.classList.remove('show');RIC.innerHTML='';RLB.textContent='Refresh';refreshing=false;}
RB.onclick=()=>{
 if(refreshing)return;refreshing=true;
 RB.classList.remove('done','fail');RB.classList.add('busy');
 RIC.innerHTML=SPINNER;RIC.classList.add('show');RLB.textContent='Refreshing';
 loadStart();
 fetch('/refresh',{method:'POST'}).then(x=>x.json()).then(d=>{
   if(d.error)throw new Error(d.error);
   PAYLOAD=d;SEL=null;initDateSlider();renderQueue();
   $('#detailhead').innerHTML='<span class="meta">Select a release&hellip;</span>';
   $('#detailStack').innerHTML='';$('#flowline').innerHTML='';
   RB.classList.remove('busy');RB.classList.add('done');RIC.innerHTML=CHK_CIRCLE;RLB.textContent='Refreshed';
   setTimeout(refreshIdle,1200);
 }).catch(()=>{
   RB.classList.remove('busy');RB.classList.add('fail');RIC.innerHTML=CHECK_ICON;RLB.textContent='Failed';
   setTimeout(refreshIdle,2200);
 }).finally(()=>{loadStop();});
};

// Rebuild graph: force a daily-inputs rebuild (POST /rebuild-graph), then swap in the result.
const RGB=$('#rebuildGraph');
if(RGB)RGB.onclick=e=>btnRun(e.currentTarget,'Rebuilding',()=>
 fetch('/rebuild-graph',{method:'POST'}).then(x=>x.json()).then(d=>{
   if(d.error)throw new Error(d.error);
   PAYLOAD=d;SEL=null;initDateSlider();renderQueue();
   $('#detailhead').innerHTML='<span class="meta">Select a release&hellip;</span>';
   $('#detailStack').innerHTML='';$('#flowline').innerHTML='';
 }),{done:'Rebuilt'});

// Auto-update: poll the snapshot; when the server has rebuilt from a new ERP
// pull (dataPulledAt changed), swap in the new payload and re-render in place.
function applyPayload(d){
 PAYLOAD=d;initDateSlider();
 const still=SEL&&PAYLOAD.releases.some(x=>x.naturalKey===SEL);
 if(!still)SEL=null;
 renderQueue();
 if(still){const r=PAYLOAD.releases.find(x=>x.naturalKey===SEL);if(r)loadDetail(r);}
 const chip=$('#datapulled');if(chip){chip.classList.add('flash');setTimeout(()=>chip.classList.remove('flash'),2000);}
}
setInterval(()=>{fetch('/snapshot').then(x=>x.json()).then(d=>{
 if(d&&d.dataPulledAt&&d.dataPulledAt!==PAYLOAD.dataPulledAt)applyPayload(d);
}).catch(()=>{});},15000);
// Keep the runbar draft counts / lock in sync so the planner sees reconcile removals
// (5-min heartbeat) reflected even with the editor closed and no new ERP pull.
setInterval(()=>{if(window._rel)updateRunbar();},20000);

// --- Filter presets: save / apply / delete named filter sets (local only). ---
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function captureFilters(){return {cust:[...custFilter],ec:ecState,pc:pcState,colour:[...colourFilter],
 invP10:invP10,condAny:Object.assign({},condAny),condAll:Object.assign({},condAll),search:$('#search').value,
 dateLo:DATES[dLo]||null,dateHi:DATES[dHi]||null};}
function applyFilters(f){
 f=f||{};
 custFilter=new Set(f.cust||[]);ecState=f.ec||0;pcState=f.pc||0;
 colourFilter=new Set(f.colour||[]);invP10=!!f.invP10;
 // Back-compat: older saved views used hideAll/showAny sets; those buckets no longer apply — drop silently.
 condAny=Object.assign({},f.condAny||{});condAll=Object.assign({},f.condAll||{});
 $('#search').value=f.search||'';
 paintChip('ecChip',ecState,'EC');paintChip('pcChip',pcState,'PC');updateColourBtn();
 $('#invP10Chip').classList.toggle('on',invP10);
 paintAllCondChips();
 if(DATES.length){
   let lo=0,hi=DATES.length-1;
   if(f.dateLo){const i=DATES.findIndex(d=>d>=f.dateLo);if(i>=0)lo=i;}
   if(f.dateHi){for(let k=0;k<DATES.length;k++){if(DATES[k]<=f.dateHi)hi=k;}}
   if(lo>hi){lo=0;hi=DATES.length-1;}
   dLo=lo;dHi=hi;const el=$('#dLo'),eh=$('#dHi');if(el){el.value=dLo;eh.value=dHi;}updateDateLabels();
 }
 if($('#custPanel').style.display!=='none')renderCustPanel();
 if($('#colourPanel').style.display!=='none')renderColourPanel();
 renderQueue();
}
let PRESETS={};
function loadPresets(){try{PRESETS=JSON.parse(localStorage.getItem('paintPresets')||'{}')||{};}catch(e){PRESETS={};}}
function persistPresets(){try{localStorage.setItem('paintPresets',JSON.stringify(PRESETS));}catch(e){}}
function renderPresets(){
 const c=$('#presetChips');const names=Object.keys(PRESETS);
 if(!names.length){c.innerHTML='<span class="pnone">no saved views</span>';return;}
 c.innerHTML=names.map(n=>`<span class="chip preset" data-n="${esc(n)}" title="Apply view “${esc(n)}”">${esc(n)}<b class="px" title="Delete view">&times;</b></span>`).join('');
 c.querySelectorAll('.preset').forEach(ch=>ch.onclick=e=>{
   const n=ch.dataset.n;
   if(e.target.classList.contains('px')){e.stopPropagation();delete PRESETS[n];persistPresets();renderPresets();return;}
   applyFilters(PRESETS[n]);
 });
}
$('#savePreset').onclick=()=>{
 const name=(prompt('Save current filters as a view — name:')||'').trim();
 if(!name)return;
 if(PRESETS[name]&&!confirm('A view named “'+name+'” exists. Overwrite it?'))return;
 PRESETS[name]=captureFilters();persistPresets();renderPresets();
};
$('#clearFilters').onclick=()=>applyFilters({dateLo:DATES[0]||null,dateHi:DATES[DATES.length-1]||null});

// --- Shared views ("common bank"): publish/apply/delete via the server (R12). ---
let SHARED_ME='';
function renderSharedViews(){
 fetch('/views').then(x=>x.json()).then(d=>{
  SHARED_ME=d.me||'';const c=$('#sharedChips');const vs=d.views||[];
  if(!vs.length){c.innerHTML='<span class="pnone">no shared views</span>';return;}
  c.innerHTML=vs.map(v=>{const mine=v.creator===SHARED_ME;
    return `<span class="chip preset" data-n="${esc(v.name)}" title="Apply shared view “${esc(v.name)}” (by ${esc(v.creator||'?')})">${esc(v.name)}${mine?'<b class="px" title="Delete (yours)">&times;</b>':''}</span>`;}).join('');
  c.querySelectorAll('.preset').forEach(ch=>ch.onclick=e=>{
    const n=ch.dataset.n,v=vs.find(x=>x.name===n);
    if(e.target.classList.contains('px')){e.stopPropagation();
      fetch('/views/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})}).then(x=>x.json()).then(r=>{if(!r.ok)alert('Cannot delete — “'+n+'” is owned by '+(r.creator||'another user')+'.');renderSharedViews();});
      return;}
    if(v)applyFilters(v.filters);
  });
 }).catch(()=>{});
}
$('#shareView').onclick=()=>{
 const name=(prompt('Publish current filters to the shared bank — name:')||'').trim();
 if(!name)return;
 fetch('/views',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,filters:captureFilters()})})
  .then(x=>x.json()).then(r=>{if(!r.ok)alert('Cannot save — a shared view named “'+name+'” is owned by '+(r.creator||'another user')+'.');renderSharedViews();});
};

updateColourBtn();initDateSlider();renderQueue();loadPresets();renderPresets();renderSharedViews();
</script></body></html>"""
