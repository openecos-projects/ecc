#!/usr/bin/env python3
"""Emit a GitHub-flavored markdown kanban of signoff metrics (mermaid diagrams).

CSV gates stay as a util; this board is the human-facing release / CI artifact
that diagramizes each catalog metric and optionally places live readiness.

Usage:
  PYTHONPATH=. python .github/scripts/generate-signoff-kanban.py \\
      [--assessment path.json] [--out signoff-kanban.md]

Env:
  ECC_REPO_ROOT  repo root (default: cwd)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def _repo_root() -> Path:
    env = Path(__file__).resolve().parents[2]
    return Path(__file__).resolve().parents[2] if env.exists() else Path.cwd()


def _load_catalog():
    root = _repo_root()
    sys.path.insert(0, str(root))
    from chipcompiler.engine.signoff.catalog import SIGNOFF_ITEM_CATALOG

    return list(SIGNOFF_ITEM_CATALOG)


def _mermaid_id(item_id: str) -> str:
    return item_id.replace(".", "_").replace("-", "_")


def _state_for(item_id: str, assessment: dict | None) -> str:
    if not assessment:
        return "catalog"
    for row in assessment.get("items") or []:
        if row.get("id") == item_id:
            st = str(row.get("state") or "").lower()
            if row.get("blocked") and st == "failed":
                owner = str(row.get("owner") or "")
                cat = str(row.get("category") or "")
                if owner == "qor" or cat in {"quality", "quality_gate"}:
                    return "ERROR"
                return "MISS"
            if st in {"unavailable", "missing"}:
                return "MISS"
            if st in {"failed", "warning", "warn"}:
                return "WARN" if st != "failed" else "WARN"
            if st in {"pass", "passed", "ready"}:
                return "PASS"
            return st.upper() or "MISS"
    readiness = str(assessment.get("readiness") or "")
    return readiness or "MISS"


def _swimlane_board(items_by_state: dict[str, list]) -> str:
    """One mermaid flowchart used as a kanban (columns = readiness)."""
    order = ["PASS", "WARN", "MISS", "ERROR", "catalog"]
    lines = ["```mermaid", "flowchart LR"]
    for col in order:
        cards = items_by_state.get(col) or []
        if not cards and col == "catalog":
            continue
        if not cards and col != "catalog":
            # keep empty columns visible when assessment present
            if any(items_by_state.get(c) for c in order if c != "catalog"):
                sid = f"col_{col}"
                lines.append(f"  subgraph {sid}[\"{col}\"]")
                lines.append(f"    empty_{col}[\"(none)\"]")
                lines.append("  end")
            continue
        sid = f"col_{col}"
        lines.append(f"  subgraph {sid}[\"{col}\"]")
        for item_id, title in cards:
            nid = _mermaid_id(item_id)
            label = f"{item_id}<br/>{title}"
            lines.append(f"    {nid}[\"{label}\"]")
        lines.append("  end")
    lines.append("```")
    return "\n".join(lines)


def _category_diagram(category: str, items: list) -> str:
    lines = [
        "```mermaid",
        "flowchart TB",
        f"  subgraph cat_{_mermaid_id(category)}[\"{category}\"]",
    ]
    for it in items:
        nid = _mermaid_id(it.id)
        opt = " (optional)" if getattr(it, "optional", False) else ""
        lines.append(f"    {nid}[\"{it.id}<br/>{it.title}{opt}\"]")
    lines.append("  end")
    # light chain by step name for readability
    by_step: dict[str, list] = defaultdict(list)
    for it in items:
        by_step[str(it.step)].append(it)
    step_ids = list(by_step)
    for a, b in zip(step_ids, step_ids[1:]):
        # link first item of adjacent steps
        left = _mermaid_id(by_step[a][0].id)
        right = _mermaid_id(by_step[b][0].id)
        lines.append(f"  {left} -.-> {right}")
    lines.append("```")
    return "\n".join(lines)


def _per_metric_diagram(it, state: str) -> str:
    """Small diagram: evidence → metric → readiness column."""
    nid = _mermaid_id(it.id)
    step = str(it.step)
    lines = [
        "```mermaid",
        "flowchart LR",
        f"  step_{nid}[\"step: {step}\"] --> metric_{nid}[\"{it.id}\"]",
        f"  metric_{nid} --> state_{nid}[\"{state}\"]",
        f"  catalog_{nid}[\"{it.category} / {it.title}\"] -.-> metric_{nid}",
        "```",
    ]
    return "\n".join(lines)


def render_markdown(catalog: list, assessment: dict | None) -> str:
    by_cat: dict[str, list] = defaultdict(list)
    for it in catalog:
        by_cat[str(it.category)].append(it)

    items_by_state: dict[str, list] = defaultdict(list)
    for it in catalog:
        st = _state_for(it.id, assessment)
        items_by_state[st].append((it.id, it.title))

    out: list[str] = []
    out.append("# Signoff release kanban")
    out.append("")
    out.append(
        "Generated from `engine.signoff.catalog`. "
        "CSV gates remain a util; this board diagramizes each metric for GitHub."
    )
    out.append("")
    if assessment:
        out.append(
            f"**Live readiness:** `{assessment.get('readiness', 'MISS')}` "
            f"(legacy status `{assessment.get('status', '')}`)"
        )
    else:
        out.append(
            "**Mode:** catalog topology (no assessment JSON — all cards in category views)."
        )
    out.append("")

    out.append("## Readiness board")
    out.append("")
    out.append(_swimlane_board(items_by_state))
    out.append("")

    out.append("## By category")
    out.append("")
    for cat in sorted(by_cat):
        out.append(f"### `{cat}`")
        out.append("")
        out.append(_category_diagram(cat, by_cat[cat]))
        out.append("")

    out.append("## Per metric")
    out.append("")
    for it in catalog:
        st = _state_for(it.id, assessment)
        out.append(f"### `{it.id}`")
        out.append("")
        out.append(f"- title: {it.title}")
        out.append(f"- step: `{it.step}`")
        out.append(f"- category: `{it.category}`")
        out.append(f"- optional: `{getattr(it, 'optional', False)}`")
        out.append(f"- board state: **{st}**")
        out.append("")
        out.append(_per_metric_diagram(it, st))
        out.append("")

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assessment",
        default="",
        help="optional signoff assessment JSON (from inspect / fixture)",
    )
    parser.add_argument(
        "--out",
        default="signoff-kanban.md",
        help="output markdown path",
    )
    args = parser.parse_args()

    assessment = None
    if args.assessment:
        assessment = json.loads(Path(args.assessment).read_text(encoding="utf-8"))

    catalog = _load_catalog()
    text = render_markdown(catalog, assessment)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(catalog)} metrics)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
