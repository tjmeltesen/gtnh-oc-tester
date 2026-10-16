"""Execution Trace to Causal DAG Builder with Loop Collapsing and Mermaid/DOT/HTML Exporters."""

from __future__ import annotations

from dataclasses import dataclass, field
import html
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import graphviz
import networkx as nx

from .tracer import ExecutionTracer, TraceEvent


@dataclass
class DAGNode:
    node_id: str
    kind: str  # "boot", "lua_call", "component_call", "state_mutation", "event_wait", "poll_loop"
    label: str
    sublabel: str = ""
    tick_start: int = 0
    tick_end: int = 0
    count: int = 1
    component_type: Optional[str] = None
    method: Optional[str] = None
    is_mutation: bool = False


class ExecutionDAG:
    """Collapses repetitive polling loops in an ExecutionTracer into a clean NetworkX DiGraph."""

    def __init__(
        self,
        nodes: List[DAGNode],
        edges: List[Tuple[str, str, str]],
        raw_events: List[TraceEvent],
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.raw_events = raw_events
        self.graph = nx.DiGraph()
        for n in self.nodes:
            self.graph.add_node(n.node_id, data=n)
        for u, v, lbl in self.edges:
            self.graph.add_edge(u, v, label=lbl)

    @classmethod
    def from_tracer(cls, tracer: ExecutionTracer, collapse_loops: bool = True) -> "ExecutionDAG":
        events = list(tracer.events)
        if not events:
            return cls(nodes=[], edges=[], raw_events=[])

        collapsed_groups: List[List[TraceEvent]] = []
        if collapse_loops:
            i = 0
            n = len(events)
            while i < n:
                matched_window = 0
                matched_repeats = 1
                for w in range(min(6, (n - i) // 2), 0, -1):
                    pattern = [ev.signature_key for ev in events[i : i + w]]
                    repeats = 1
                    while i + (repeats + 1) * w <= n:
                        cand = [ev.signature_key for ev in events[i + repeats * w : i + (repeats + 1) * w]]
                        if cand == pattern:
                            repeats += 1
                        else:
                            break
                    if repeats >= 2:
                        matched_window = w
                        matched_repeats = repeats
                        break
                if matched_window > 0:
                    total_span = matched_window * matched_repeats
                    collapsed_groups.append(events[i : i + total_span])
                    i += total_span
                else:
                    collapsed_groups.append([events[i]])
                    i += 1
        else:
            collapsed_groups = [[ev] for ev in events]

        dag_nodes: List[DAGNode] = []
        dag_edges: List[Tuple[str, str, str]] = []

        for idx, grp in enumerate(collapsed_groups, start=1):
            node_id = f"N{idx}"
            first = grp[0]
            last = grp[-1]
            if len(grp) > 1:
                unique_titles = []
                for e in grp:
                    if e.title not in unique_titles:
                        unique_titles.append(e.title)
                iterations = len(grp) // max(1, len(unique_titles))
                if len(unique_titles) > 1:
                    label = f"Poll Loop x{iterations}: {' -> '.join(unique_titles)}"
                else:
                    label = f"Loop x{len(grp)}: {first.title}"
                kind = "poll_loop"
            else:
                label = first.title
                kind = "state_mutation" if first.state_mutation else first.kind

            sublabel = last.detail
            node = DAGNode(
                node_id=node_id,
                kind=kind,
                label=label,
                sublabel=sublabel,
                tick_start=first.tick,
                tick_end=last.tick,
                count=len(grp),
                component_type=first.component_type,
                method=first.method,
                is_mutation=bool(first.state_mutation),
            )
            dag_nodes.append(node)
            if idx > 1:
                prev_node = dag_nodes[-2]
                edge_lbl = f"t={first.tick}" if first.tick != prev_node.tick_end else ""
                dag_edges.append((prev_node.node_id, node_id, edge_lbl))

        return cls(nodes=dag_nodes, edges=dag_edges, raw_events=events)

    def to_mermaid(self, direction: str = "TD") -> str:
        """Export the execution DAG as a Mermaid flowchart."""
        lines = [f"flowchart {direction}"]
        for n in self.nodes:
            safe_lbl = n.label.replace('"', "'")
            if n.sublabel:
                safe_sub = n.sublabel.replace('"', "'")
                full_lbl = f"{safe_lbl}\\n{safe_sub}"
            else:
                full_lbl = safe_lbl
            if n.kind == "boot":
                lines.append(f'    {n.node_id}(["{full_lbl}"])')
            elif n.kind == "poll_loop":
                lines.append(f'    {n.node_id}{{{{"{full_lbl}"}}}}')
            elif n.kind == "event_wait":
                lines.append(f'    {n.node_id}(("{full_lbl}"))')
            else:
                lines.append(f'    {n.node_id}["{full_lbl}"]')

        for u, v, lbl in self.edges:
            if lbl:
                lines.append(f"    {u} -->|{lbl}| {v}")
            else:
                lines.append(f"    {u} --> {v}")

        # Add styling classes
        lines.append("    classDef boot fill:#1e3a8a,stroke:#60a5fa,color:#fff;")
        lines.append("    classDef mutation fill:#065f46,stroke:#34d399,color:#fff;")
        lines.append("    classDef loop fill:#78350f,stroke:#fbbf24,color:#fff;")
        lines.append("    classDef event fill:#4c1d95,stroke:#a78bfa,color:#fff;")
        lines.append("    classDef call fill:#1f2937,stroke:#9ca3af,color:#f3f4f6;")
        for n in self.nodes:
            cls_name = {
                "boot": "boot",
                "state_mutation": "mutation",
                "poll_loop": "loop",
                "event_wait": "event",
            }.get(n.kind, "call")
            lines.append(f"    class {n.node_id} {cls_name};")
        return "\n".join(lines)

    def to_dot(self, title: str = "GTNH OpenComputers Execution DAG") -> str:
        """Export the execution DAG as Graphviz DOT source."""
        dot = graphviz.Digraph(name="OCExecutionDAG", comment=title)
        dot.attr(
            rankdir="TB",
            bgcolor="#0f172a",
            fontname="Helvetica",
            fontsize="12",
            fontcolor="#e2e8f0",
            label=title,
            labelloc="t",
            pad="0.4",
            nodesep="0.35",
            ranksep="0.45",
        )
        dot.attr("node", fontname="Courier", fontsize="10", style="filled,rounded", shape="box")
        dot.attr("edge", fontname="Helvetica", fontsize="9", color="#64748b", fontcolor="#94a3b8")

        palette = {
            "boot": ("#1e3a8a", "#60a5fa", "#ffffff", "oval"),
            "state_mutation": ("#064e3b", "#10b981", "#ecfdf5", "box"),
            "poll_loop": ("#78350f", "#f59e0b", "#fffbeb", "hexagon"),
            "event_wait": ("#4c1d95", "#a78bfa", "#f5f3ff", "Mrecord"),
            "lua_call": ("#1e293b", "#38bdf8", "#e0f2fe", "box"),
            "component_call": ("#1e293b", "#94a3b8", "#f1f5f9", "box"),
        }

        for n in self.nodes:
            fill, border, font_c, shape = palette.get(n.kind, palette["component_call"])
            tick_info = (
                f"[tick {n.tick_start}..{n.tick_end}]"
                if n.tick_end > n.tick_start
                else f"[tick {n.tick_start}]"
            )
            lbl = f"{n.label}\n{n.sublabel}\n{tick_info}".strip()
            dot.node(
                n.node_id,
                label=lbl,
                fillcolor=fill,
                color=border,
                fontcolor=font_c,
                shape=shape,
                penwidth="1.6",
            )

        for u, v, elbl in self.edges:
            dot.edge(u, v, label=elbl)

        return dot.source

    def render_image(self, output_path: str | Path, fmt: str = "png") -> Path:
        """Render the Graphviz DOT graph to a PNG or SVG file."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        src = graphviz.Source(self.to_dot(), format=fmt)
        rendered = src.render(
            filename=out.stem,
            directory=str(out.parent),
            cleanup=True,
        )
        return Path(rendered)

    def to_html(
        self,
        title: str = "GTNH OpenComputers Execution Trace & DAG",
        screen_emulator: Optional[Any] = None,
    ) -> str:
        """Render a self-contained Interactive HTML Trace & DAG Viewer."""
        svg_markup = ""
        try:
            svg_bytes = graphviz.Source(self.to_dot(title=title), format="svg").pipe()
            svg_markup = svg_bytes.decode("utf-8", errors="replace")
        except Exception:
            svg_markup = f"<pre>{html.escape(self.to_mermaid())}</pre>"

        screen_section = ""
        if screen_emulator is not None:
            screen_txt = html.escape(screen_emulator.to_text(strip_trailing=False))
            screen_section = f"""
            <div class="panel">
              <h2>GPU Screen Snapshot ({screen_emulator.width}x{screen_emulator.height})</h2>
              <pre class="screen-box">{screen_txt}</pre>
            </div>
            """

        rows_html: List[str] = []
        for ev in self.raw_events:
            badge_cls = "badge-mut" if ev.state_mutation else f"badge-{ev.kind}"
            rows_html.append(
                f"<tr>"
                f"<td>#{ev.seq}</td>"
                f"<td>{ev.tick}</td>"
                f'<td><span class="badge {badge_cls}">{html.escape(ev.kind)}</span></td>'
                f"<td><code>{html.escape(ev.title)}</code></td>"
                f"<td><code>{html.escape(ev.detail)}</code></td>"
                f"<td>{html.escape(ev.state_mutation or '-')}</td>"
                f"</tr>"
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{html.escape(title)}</title>
<style>
  body {{
    background: #0b0f19;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    margin: 0;
    padding: 24px;
  }}
  h1 {{ margin-top: 0; color: #f8fafc; font-size: 22px; }}
  h2 {{ color: #94a3b8; font-size: 16px; margin-top: 0; }}
  .grid {{
    display: grid;
    grid-template-columns: 1fr;
    gap: 20px;
  }}
  .panel {{
    background: #111827;
    border: 1px solid #1f2937;
    border-radius: 10px;
    padding: 18px;
    overflow-x: auto;
  }}
  .screen-box {{
    background: #000;
    color: #34d399;
    padding: 14px;
    border-radius: 6px;
    border: 2px solid #374151;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    line-height: 1.35;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th, td {{
    text-align: left;
    padding: 8px 10px;
    border-bottom: 1px solid #1f2937;
  }}
  th {{ color: #9ca3af; font-weight: 600; }}
  .badge {{
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
  }}
  .badge-boot {{ background: #1e3a8a; color: #93c5fd; }}
  .badge-mut {{ background: #064e3b; color: #6ee7b7; }}
  .badge-component_call {{ background: #1f2937; color: #cbd5e1; }}
  .badge-event_wait {{ background: #4c1d95; color: #ddd6fe; }}
  .badge-lua_call {{ background: #0c4a6e; color: #7dd3fc; }}
</style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <div class="grid">
    <div class="panel">
      <h2>Causal Execution DAG ({len(self.nodes)} nodes, {len(self.raw_events)} trace events)</h2>
      {svg_markup}
    </div>
    {screen_section}
    <div class="panel">
      <h2>Execution Timeline</h2>
      <table>
        <thead>
          <tr>
            <th>Seq</th>
            <th>Tick</th>
            <th>Kind</th>
            <th>Operation</th>
            <th>Return / Wakeup</th>
            <th>State Mutation</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows_html)}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""
