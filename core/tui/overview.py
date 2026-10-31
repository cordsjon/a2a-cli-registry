"""Read-only rich render of the catalog. The ONLY module importing rich."""
from collections import Counter

from rich.console import Console
from rich.table import Table

_WORK_STYLE = {"pass": "green", "fail": "red", "unknown": "dim"}

_HEALTH_STYLE = {"healthy": "green", "unhealthy": "red",
                 "stale": "yellow", "unknown": "dim", "not_standalone": "dim cyan",
                 "skipped-needs-env": "dim yellow"}


def render_overview(clis: list[dict], graph: list[dict], *, console=None) -> None:
    console = console or Console()
    if not clis:
        console.print("Registry is empty — run `populate` first.")
        return

    works = Counter(c.get("work_status", "unknown") for c in clis)
    console.print(f"works: pass {works['pass']} fail {works['fail']} unknown {works['unknown']}")

    cli_table = Table(title="CLIs")
    for col in ("slug", "lang", "health", "works", "description"):
        cli_table.add_column(col)
    for c in clis:
        hs = (c.get("health_status") or "unknown").lower()
        style = _HEALTH_STYLE.get(hs, "dim")
        ws = c.get("work_status", "unknown")
        ws_style = _WORK_STYLE.get(ws, "dim")
        cli_table.add_row(c["slug"], c.get("lang", ""), f"[{style}]{hs}[/{style}]",
                          f"[{ws_style}]{ws}[/{ws_style}]", c.get("description", ""))
    console.print(cli_table)

    cap_table = Table(title="Capabilities")
    for col in ("slug", "intent", "in -> out", "side_effect", "confidence"):
        cap_table.add_column(col)
    for c in clis:
        for cap in c.get("capabilities", []):
            conf = cap.get("confidence", "")
            conf_style = "cyan" if conf == "declared" else "magenta"
            cap_table.add_row(
                c["slug"],
                ", ".join(cap.get("intent_tags", [])),
                f"{', '.join(cap.get('input_types', []))} -> {', '.join(cap.get('output_types', []))}",
                cap.get("side_effect", ""),
                f"[{conf_style}]{conf}[/{conf_style}]",
            )
    console.print(cap_table)

    if graph:
        edge_table = Table(title="Call-graph edges")
        for col in ("from", "to", "via_type"):
            edge_table.add_column(col)
        for e in graph:
            edge_table.add_row(e["from"], e["to"], e["via_type"])
        console.print(edge_table)
    else:
        console.print("No edges.")
