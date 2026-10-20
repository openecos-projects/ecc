#!/usr/bin/env python3
"""Emit a GitHub-flavored markdown **guide + kanban** for signoff metrics.

Homepage is a navigable tour (how to read → map → readiness → categories →
per-metric). CSV / FileCheck gates stay a util under test/lit/csv_gates.

Usage:
  PYTHONPATH=. python .github/scripts/generate-signoff-kanban.py \\
      [--assessment path.json] [--out signoff-kanban.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Category order + one-line tour copy for the homepage guide.
_CATEGORY_GUIDE: tuple[tuple[str, str, str], ...] = (
    (
        "quality_gate",
        "Quality gates",
        "Machine predicates (DRC/LVS/STA/RCX/area). Failures → ERROR readiness.",
    ),
    (
        "artifact",
        "Evidence artifacts",
        "Required files from Harden / LVS / RCX / STA / synthesis (and optional LEC).",
    ),
    (
        "report",
        "Reports",
        "Human-readable reports tied to steps (e.g. STA timing reports).",
    ),
    (
        "flow",
        "Flow completion",
        "Ledger steps that must have completed for a full package.",
    ),
    (
        "configuration",
        "Configuration snapshots",
        "Workspace config JSON (db / rcx / sta) frozen for the run.",
    ),
    (
        "provenance",
        "Provenance",
        "Initial RTL / SDC inputs that anchor the workspace.",
    ),
)

_CATEGORY_BLURB = {cid: (title, blurb) for cid, title, blurb in _CATEGORY_GUIDE}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_catalog():
    root = _repo_root()
    sys.path.insert(0, str(root))
    from chipcompiler.engine.signoff.catalog import SIGNOFF_ITEM_CATALOG

    return list(SIGNOFF_ITEM_CATALOG)


def _mermaid_id(item_id: str) -> str:
    return item_id.replace(".", "_").replace("-", "_")


def _anchor(item_id: str) -> str:
    # GitHub heading anchors for `### \`id\``
    return item_id.lower().replace(".", "")


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
                return "WARN"
            if st in {"pass", "passed", "ready"}:
                return "PASS"
            return st.upper() or "MISS"
    return str(assessment.get("readiness") or "MISS") or "MISS"


def _counts(items_by_state: dict[str, list]) -> dict[str, int]:
    keys = ("PASS", "WARN", "MISS", "ERROR", "catalog")
    return {k: len(items_by_state.get(k) or []) for k in keys}


def _map_diagram(by_cat: dict[str, list]) -> str:
    """Homepage map: categories as hubs → metric counts."""
    lines = [
        "```mermaid",
        "flowchart TB",
        '  hub["Signoff catalog"]',
    ]
    for cat, title, _blurb in _CATEGORY_GUIDE:
        items = by_cat.get(cat) or []
        if not items:
            continue
        cid = f"map_{_mermaid_id(cat)}"
        lines.append(f'  {cid}["{title}<br/>{len(items)} metrics"]')
        lines.append(f"  hub --> {cid}")
    # any categories not in the guide
    known = {c for c, _, _ in _CATEGORY_GUIDE}
    for cat in sorted(by_cat):
        if cat in known:
            continue
        items = by_cat[cat]
        cid = f"map_{_mermaid_id(cat)}"
        lines.append(f'  {cid}["{cat}<br/>{len(items)} metrics"]')
        lines.append(f"  hub --> {cid}")
    lines.append("```")
    return "\n".join(lines)


def _howto_diagram() -> str:
    return "\n".join(
        [
            "```mermaid",
            "flowchart LR",
            '  A["1. Read map"] --> B["2. Check readiness board"]',
            '  B --> C["3. Open a category"]',
            '  C --> D["4. Drill into one metric"]',
            '  D --> E["5. Fix evidence / re-inspect"]',
            "```",
        ]
    )


def _swimlane_board(items_by_state: dict[str, list], *, compact: bool = False) -> str:
    order = ["PASS", "WARN", "MISS", "ERROR", "catalog"]
    lines = ["```mermaid", "flowchart LR"]
    live = any(items_by_state.get(c) for c in ("PASS", "WARN", "MISS", "ERROR"))
    for col in order:
        cards = items_by_state.get(col) or []
        if col == "catalog" and live:
            continue
        if not cards and col == "catalog":
            continue
        if not cards:
            if live:
                lines.append(f'  subgraph col_{col}["{col}"]')
                lines.append(f'    empty_{col}["(none)"]')
                lines.append("  end")
            continue
        lines.append(f'  subgraph col_{col}["{col} ({len(cards)})"]')
        show = cards[:12] if compact and len(cards) > 12 else cards
        for item_id, title in show:
            nid = _mermaid_id(f"{col}_{item_id}")
            short = title if len(title) <= 28 else title[:26] + "…"
            lines.append(f'    {nid}["{item_id}<br/>{short}"]')
        if compact and len(cards) > 12:
            lines.append(
                f'    more_{col}["… +{len(cards) - 12} more — see TOC"]'
            )
        lines.append("  end")
    lines.append("```")
    return "\n".join(lines)


def _category_diagram(category: str, items: list) -> str:
    title, _ = _CATEGORY_BLURB.get(category, (category, ""))
    lines = [
        "```mermaid",
        "flowchart TB",
        f'  subgraph cat_{_mermaid_id(category)}["{title}"]',
    ]
    for it in items:
        nid = _mermaid_id(it.id)
        opt = " (optional)" if getattr(it, "optional", False) else ""
        lines.append(f'    {nid}["{it.id}<br/>{it.title}{opt}"]')
    lines.append("  end")
    by_step: dict[str, list] = defaultdict(list)
    for it in items:
        by_step[str(it.step)].append(it)
    step_ids = list(by_step)
    for a, b in zip(step_ids, step_ids[1:], strict=False):
        left = _mermaid_id(by_step[a][0].id)
        right = _mermaid_id(by_step[b][0].id)
        lines.append(f"  {left} -.-> {right}")
    lines.append("```")
    return "\n".join(lines)


def _per_metric_diagram(it, state: str) -> str:
    nid = _mermaid_id(it.id)
    return "\n".join(
        [
            "```mermaid",
            "flowchart LR",
            f'  step_{nid}["step: {it.step}"] --> metric_{nid}["{it.id}"]',
            f'  metric_{nid} --> state_{nid}["{state}"]',
            f'  cat_{nid}["{it.category}"] -.-> metric_{nid}',
            "```",
        ]
    )


def _toc(by_cat: dict[str, list], catalog: list) -> list[str]:
    lines = [
        "## Contents",
        "",
        "1. [How to read this board](#how-to-read-this-board)",
        "2. [Catalog map](#catalog-map)",
        "3. [Readiness board](#readiness-board)",
        "4. [Categories](#categories)",
    ]
    for cat, title, _ in _CATEGORY_GUIDE:
        if cat in by_cat:
            lines.append(f"   - [{title} (`{cat}`)](#category-{cat})")
    for cat in sorted(by_cat):
        if cat not in _CATEGORY_BLURB:
            lines.append(f"   - [`{cat}`](#category-{cat})")
    lines.append("5. [Per-metric index](#per-metric-index)")
    lines.append("")
    lines.append("<details>")
    lines.append("<summary>Jump to a metric (full list)</summary>")
    lines.append("")
    for it in catalog:
        lines.append(f"- [`{it.id}`](#{_anchor(it.id)}) — {it.title}")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return lines


def render_markdown(catalog: list, assessment: dict | None) -> str:
    by_cat: dict[str, list] = defaultdict(list)
    for it in catalog:
        by_cat[str(it.category)].append(it)

    items_by_state: dict[str, list] = defaultdict(list)
    for it in catalog:
        st = _state_for(it.id, assessment)
        items_by_state[st].append((it.id, it.title))
    counts = _counts(items_by_state)

    out: list[str] = []
    out.append("# Signoff release board")
    out.append("")
    out.append(
        "> **导览首页** — start here. This page is the human guide to signoff "
        "metrics; CSV/FileCheck under `test/lit/csv_gates` stays a util."
    )
    out.append("")
    if assessment:
        out.append(
            f"**Live snapshot:** readiness `{assessment.get('readiness', 'MISS')}` "
            f"· legacy `{assessment.get('status', '')}` · "
            f"{len(catalog)} catalog metrics"
        )
        out.append("")
        out.append(
            "| PASS | WARN | MISS | ERROR |\n| ---: | ---: | ---: | ---: |\n"
            f"| {counts['PASS']} | {counts['WARN']} | {counts['MISS']} | {counts['ERROR']} |"
        )
    else:
        out.append(
            f"**Catalog mode:** {len(catalog)} metrics · no assessment JSON "
            "(swimlanes show topology until you pass `--assessment`)."
        )
    out.append("")

    out.extend(_toc(by_cat, catalog))

    out.append("## How to read this board")
    out.append("")
    out.append(
        "Signoff readiness is `PASS | WARN | MISS | ERROR`. "
        "Quality-gate failures are **ERROR**; missing evidence is **MISS**; "
        "optional gaps are **WARN**."
    )
    out.append("")
    out.append(_howto_diagram())
    out.append("")
    out.append("| Step | What you do |")
    out.append("| --- | --- |")
    out.append("| Map | See which domains exist (quality / artifact / flow / …) |")
    out.append("| Readiness board | See where cards sit right now |")
    out.append("| Category | Open one domain diagram |")
    out.append("| Per metric | Drill one id → step → state |")
    out.append("")

    out.append("## Catalog map")
    out.append("")
    out.append("One hub per domain — click a category section below for detail.")
    out.append("")
    out.append(_map_diagram(by_cat))
    out.append("")
    out.append("| Domain | Metrics | Role |")
    out.append("| --- | ---: | --- |")
    for cat, title, blurb in _CATEGORY_GUIDE:
        n = len(by_cat.get(cat) or [])
        if not n:
            continue
        out.append(f"| [{title}](#category-{cat}) | {n} | {blurb} |")
    out.append("")

    out.append("## Readiness board")
    out.append("")
    if assessment:
        out.append(
            "Cards placed by live assessment "
            f"(PASS={counts['PASS']}, WARN={counts['WARN']}, "
            f"MISS={counts['MISS']}, ERROR={counts['ERROR']})."
        )
    else:
        out.append(
            "No assessment — all metrics listed under **catalog**. "
            "Re-run with `--assessment` to split swimlanes."
        )
    out.append("")
    out.append(_swimlane_board(items_by_state, compact=True))
    out.append("")

    out.append("## Categories")
    out.append("")
    ordered = [c for c, _, _ in _CATEGORY_GUIDE if c in by_cat]
    ordered += sorted(c for c in by_cat if c not in _CATEGORY_BLURB)
    for cat in ordered:
        title, blurb = _CATEGORY_BLURB.get(cat, (cat, ""))
        out.append(f"### Category: `{cat}`")
        out.append("")
        out.append(f"<a id=\"category-{cat}\"></a>")
        out.append("")
        if blurb:
            out.append(f"**{title}.** {blurb}")
            out.append("")
        out.append("| id | title | step | optional |")
        out.append("| --- | --- | --- | --- |")
        for it in by_cat[cat]:
            opt = "yes" if getattr(it, "optional", False) else ""
            out.append(
                f"| [`{it.id}`](#{_anchor(it.id)}) | {it.title} | `{it.step}` | {opt} |"
            )
        out.append("")
        out.append(_category_diagram(cat, by_cat[cat]))
        out.append("")
        out.append(
            "[↑ Contents](#contents) · [↑ Map](#catalog-map) · "
            "[↑ Readiness](#readiness-board)"
        )
        out.append("")

    out.append("## Per-metric index")
    out.append("")
    out.append("Each metric: step → id → board state.")
    out.append("")
    for it in catalog:
        st = _state_for(it.id, assessment)
        out.append(f"### `{it.id}`")
        out.append("")
        out.append(
            f"- **{it.title}** · category `{it.category}` · step `{it.step}` · "
            f"optional `{getattr(it, 'optional', False)}` · state **{st}**"
        )
        out.append("")
        out.append(_per_metric_diagram(it, st))
        out.append("")
        out.append(
            f"[↑ category `{it.category}`](#category-{it.category}) · "
            "[↑ Contents](#contents)"
        )
        out.append("")

    out.append("---")
    out.append("")
    out.append(
        "_Generated by `.github/scripts/generate-signoff-kanban.py` "
        "from `chipcompiler.engine.signoff.catalog`._"
    )
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assessment", default="", help="optional assessment JSON")
    parser.add_argument("--out", default="signoff-kanban.md", help="output markdown")
    args = parser.parse_args()

    assessment = None
    if args.assessment:
        assessment = json.loads(Path(args.assessment).read_text(encoding="utf-8"))

    text = render_markdown(_load_catalog(), assessment)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
