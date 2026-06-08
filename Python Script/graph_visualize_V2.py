"""
Interactive graph explorer for the V2 allocation graph.

Builds the same graph that ``graph_allocator_V2.build_graph`` produces and emits
a self-contained interactive HTML file (uses vis-network from a CDN, so the
only requirement to view it is a browser with internet access). Pick a
top-level released part from the dropdown to render its routing chain plus the
component branches that feed into it, recursively.

Run from the project root::

    venv/Scripts/python.exe "Python Script/graph_visualize_V2.py"

Output: ``Allocations/graph_explorer_V2.html`` (open in a browser).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_allocator_V2 import (  # noqa: E402
    build_graph,
    load_full_process_routing,
    load_releases_no_p6_elim,
)
from inventory_to_release_allocation import (  # noqa: E402
    BASE,
    add_prev_next_operation,
    clean_folder,
    do_nothing,
    load_inventory,
    path_bom_exploded,
)


def _node_id(part: str, op: str) -> str:
    return f"{part}␟{op}"  # unit-separator unlikely to appear in data


def build_graph_payload():
    inv_raw = load_inventory()
    rel_raw = load_releases_no_p6_elim()
    routing = load_full_process_routing()
    exploded = clean_folder(path_bom_exploded, do_nothing)
    inventory = add_prev_next_operation(inv_raw, routing)

    graph = build_graph(routing, exploded, inventory)

    # Visualizer shows every release as a possible root — no paint filtering here.

    nodes_json = []
    for key, node in graph.nodes.items():
        qty = sum(c.quantity for c in node.containers)
        is_painted_part = node.part in graph.painted_parts
        is_paint_op = ("EC" in str(node.operation)) or ("PC" in str(node.operation))
        nodes_json.append(
            {
                "id": _node_id(node.part, node.operation),
                "part": node.part,
                "op": node.operation,
                "ion": node.internal_op_no,
                "paintedPart": is_painted_part,
                "paintOp": is_paint_op,
                "containers": len(node.containers),
                "qty": int(qty),
                "isFinal": graph.final_op.get(node.part) is node,
            }
        )

    edges_json = []
    for key, node in graph.nodes.items():
        nid = _node_id(node.part, node.operation)
        if node.upstream is not None:
            edges_json.append(
                {
                    "from": nid,
                    "to": _node_id(node.upstream.part, node.upstream.operation),
                    "type": "routing",
                }
            )
        for edge in node.component_edges:
            tgt = edge.target
            edges_json.append(
                {
                    "from": nid,
                    "to": _node_id(tgt.part, tgt.operation),
                    "type": "component",
                    "mult": edge.multiplier,
                }
            )

    # part -> representative customer (most frequent release customer for the part)
    cust_by_part: dict[str, str] = {}
    if "Customer" in rel_raw.columns:
        for part, grp in rel_raw.groupby("Part Number"):
            top = grp["Customer"].astype(str).replace("", "Unknown").mode()
            cust_by_part[part] = (top.iloc[0] if not top.empty else "Unknown") or "Unknown"

    # roots = every TOP-LEVEL part (has a routing and is never consumed as a
    # sub-component), plus any released part (so no release drops off the list).
    consumed: set[str] = set()
    for node in graph.nodes.values():
        for edge in node.component_edges:
            consumed.add(edge.target.part)

    released = set(rel_raw["Part Number"]) & set(graph.final_op)
    top_level = (set(graph.final_op) - consumed) | released

    roots = {}
    for part in sorted(top_level):
        fn = graph.final_op[part]
        roots[part] = {
            "node": _node_id(fn.part, fn.operation),
            "customer": cust_by_part.get(part, "Unreleased"),
        }

    return nodes_json, edges_json, roots


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Allocation Graph Explorer</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0e0f13; --panel:#15171d; --panel-2:#1b1e26; --line:#262a35;
    --txt:#e8eaf0; --muted:#8b909e; --accent:#5b8cff;
    --paint:#ff5c7c; --painted:#3ddc97; --plain:#5a6072; --inv:#ffd166;
    --routing:#525a6b; --comp:#ff9f6b;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;font-family:Inter,Segoe UI,Arial,sans-serif;
    background:var(--bg);color:var(--txt);-webkit-font-smoothing:antialiased}
  #bar{padding:14px 20px;background:linear-gradient(180deg,var(--panel),var(--panel-2));
    border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:flex-end;flex-wrap:wrap}
  .field{display:flex;flex-direction:column;gap:5px}
  .field label{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
  #bar select,#bar input{background:var(--bg);color:var(--txt);border:1px solid var(--line);
    border-radius:8px;padding:8px 11px;font-size:13px;outline:none;transition:border-color .15s,box-shadow .15s}
  #bar select:focus,#bar input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(91,140,255,.18)}
  #bar select{min-width:360px}
  #bar optgroup{font-weight:600;color:var(--accent);background:var(--panel)}
  #bar option{color:var(--txt);background:var(--panel-2);font-family:JetBrains Mono,monospace}
  #title{font-size:15px;font-weight:600;letter-spacing:.02em;margin-right:auto;display:flex;align-items:center;gap:9px}
  #title .badge{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}
  #info{font-size:12px;color:var(--muted);font-family:JetBrains Mono,monospace;padding-bottom:9px}
  .legend{display:flex;gap:20px;font-size:12px;align-items:center;padding:9px 20px;
    background:var(--panel);border-bottom:1px solid var(--line);flex-wrap:wrap;color:var(--muted)}
  .dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px;vertical-align:middle}
  .swatch{display:inline-block;width:22px;height:0;border-top-width:3px;border-top-style:solid;margin-right:6px;vertical-align:middle}
  #net{width:100%;height:calc(100% - 112px)}
</style>
</head>
<body>
<div id="bar">
  <div id="title"><span class="badge"></span>Allocation Graph Explorer</div>
  <div class="field">
    <label>Customer</label>
    <select id="customer"></select>
  </div>
  <div class="field">
    <label>Top-level released part</label>
    <select id="root"></select>
  </div>
  <div class="field">
    <label>Filter parts</label>
    <input id="filter" type="text" placeholder="type to filter…"/>
  </div>
  <span id="info"></span>
</div>
<div class="legend">
  <span><span class="dot" style="background:#ff5c7c"></span>Paint op (EC/PC)</span>
  <span><span class="dot" style="background:#3ddc97"></span>Painted part</span>
  <span><span class="dot" style="background:#5a6072"></span>Non-painted part</span>
  <span><span class="dot" style="background:#ffd166;box-shadow:0 0 0 2px #fff3"></span>Has inventory</span>
  <span><span class="swatch" style="border-top-color:#525a6b"></span>Routing flow</span>
  <span><span class="swatch" style="border-top-color:#ff9f6b;border-top-style:dashed"></span>Component (BOM)</span>
</div>
<div id="net"></div>
<script>
const NODES = __NODES__;
const EDGES = __EDGES__;
const ROOTS = __ROOTS__;   // part -> {node, customer}

const nodeById = {};
NODES.forEach(n => nodeById[n.id] = n);
const outEdges = {};
EDGES.forEach(e => { (outEdges[e.from] = outEdges[e.from] || []).push(e); });

const custSel = document.getElementById('customer');
const sel = document.getElementById('root');
const filt = document.getElementById('filter');
const info = document.getElementById('info');

// group parts by customer
const byCustomer = {};
Object.keys(ROOTS).forEach(p => {
  const c = (ROOTS[p].customer || 'Unknown');
  (byCustomer[c] = byCustomer[c] || []).push(p);
});
const customers = Object.keys(byCustomer).sort((a,b)=>a.localeCompare(b));
Object.values(byCustomer).forEach(l => l.sort());

function populateCustomers(){
  custSel.innerHTML = '<option value="__ALL__">All customers</option>';
  customers.forEach(c => {
    const o = document.createElement('option');
    o.value = c; o.textContent = `${c}  (${byCustomer[c].length})`;
    custSel.appendChild(o);
  });
}

function currentParts(){
  const c = custSel.value;
  const q = filt.value.toLowerCase();
  let parts = (c === '__ALL__') ? Object.keys(ROOTS) : byCustomer[c].slice();
  if (q) parts = parts.filter(p => p.toLowerCase().includes(q));
  return parts;
}

function populateRoots(){
  sel.innerHTML = '';
  const c = custSel.value;
  const q = filt.value.toLowerCase();
  const groups = (c === '__ALL__') ? customers : [c];
  groups.forEach(cust => {
    let parts = byCustomer[cust] || [];
    if (q) parts = parts.filter(p => p.toLowerCase().includes(q));
    if (!parts.length) return;
    const og = document.createElement('optgroup');
    og.label = cust;
    parts.forEach(p => {
      const o = document.createElement('option');
      o.value = p; o.textContent = p;
      og.appendChild(o);
    });
    sel.appendChild(og);
  });
}

populateCustomers();
populateRoots();

custSel.addEventListener('change', () => { populateRoots(); if(sel.value) render(sel.value); });
filt.addEventListener('input', () => { populateRoots(); if(sel.value) render(sel.value); });

function subtree(rootId){
  const seen = new Set([rootId]);
  const q = [rootId];
  const nodes = [], edges = [];
  while(q.length){
    const cur = q.shift();
    (outEdges[cur]||[]).forEach(e => {
      edges.push(e);
      if(!seen.has(e.to)){ seen.add(e.to); q.push(e.to); }
    });
  }
  seen.forEach(id => { if(nodeById[id]) nodes.push(nodeById[id]); });
  return {nodes, edges};
}

let network = null;
function render(part){
  const meta = ROOTS[part]; if(!meta) return;
  const rootId = meta.node;
  const {nodes, edges} = subtree(rootId);
  info.textContent = `${meta.customer} · ${nodes.length} ops · ${edges.length} edges`;

  const visNodes = nodes.map(n => {
    let color = '#5a6072';
    if (n.paintOp) color = '#ff5c7c';
    else if (n.paintedPart) color = '#3ddc97';
    const hasInv = n.qty > 0;
    return {
      id: n.id,
      label: n.op + (hasInv ? `   ${n.qty}` : ''),
      title: `Part: ${n.part}\\nOp: ${n.op}\\nInternal Op No: ${n.ion}\\nContainers: ${n.containers}\\nQty on hand: ${n.qty}`,
      shape: n.id===rootId ? 'star' : (n.isFinal ? 'diamond' : 'box'),
      color: {
        background: color,
        border: hasInv ? '#ffd166' : color,
        highlight:{background:color, border:'#5b8cff'},
        hover:{background:color, border:'#5b8cff'},
      },
      borderWidth: hasInv ? 3 : 1,
      shadow: hasInv ? {enabled:true, color:'rgba(255,209,102,.35)', size:14, x:0, y:0} : false,
      font: {color:'#f3f4f8', size: 13, face:'Inter', multi:false},
      shapeProperties:{borderRadius:7},
    };
  });
  const visEdges = edges.map(e => e.type==='routing' ? {
      from:e.from, to:e.to, arrows:{to:{enabled:true,scaleFactor:.6}},
      color:{color:'#525a6b',highlight:'#5b8cff',hover:'#5b8cff'},
      width:1.4, smooth:{type:'cubicBezier',roundness:.4}
    } : {
      from:e.from, to:e.to, arrows:{to:{enabled:true,scaleFactor:.6}}, dashes:[6,5],
      color:{color:'#ff9f6b',highlight:'#ffbf95',hover:'#ffbf95'}, width:1.8,
      smooth:{type:'cubicBezier',roundness:.4},
      label: (e.mult!=null ? ('×'+ (Math.round(e.mult*1000)/1000)) : ''),
      font:{color:'#ffc7a3', size:11, strokeWidth:0, background:'#0e0f13', face:'JetBrains Mono'}
    });

  const container = document.getElementById('net');
  const data = {nodes:new vis.DataSet(visNodes), edges:new vis.DataSet(visEdges)};
  const options = {
    layout:{ hierarchical:{ enabled:true, direction:'RL', sortMethod:'directed',
              levelSeparation:185, nodeSpacing:95, treeSpacing:185, blockShifting:true } },
    physics:false,
    interaction:{hover:true, navigationButtons:false, keyboard:false, tooltipDelay:120},
    nodes:{margin:9, shadow:false},
    edges:{selectionWidth:1.6},
  };
  if(network){ network.setData(data); network.setOptions(options); }
  else { network = new vis.Network(container, data, options); }
}

sel.addEventListener('change', () => render(sel.value));
if(sel.value) render(sel.value);
</script>
</body>
</html>
"""


def main() -> None:
    nodes_json, edges_json, roots = build_graph_payload()
    html = (
        HTML_TEMPLATE
        .replace("__NODES__", json.dumps(nodes_json))
        .replace("__EDGES__", json.dumps(edges_json))
        .replace("__ROOTS__", json.dumps(roots))
    )
    out_dir = BASE / "Allocations"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "graph_explorer_V2.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote interactive graph to: {out}")
    print(f"Nodes: {len(nodes_json)}  Edges: {len(edges_json)}  Roots: {len(roots)}")


if __name__ == "__main__":
    main()
