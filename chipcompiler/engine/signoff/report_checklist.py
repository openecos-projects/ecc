"""Checklist report rendering from the workspace signoff checklist.

Reads ``home/checklist.json`` (the schema-v3 ``signoff_checklist`` contract
maintained by tools/ecc/signoff_checklist.py and refreshed by the signoff
collector) and renders a human-readable status report. Read-only: unlike
``data.checklist.Checklist`` this module never rewrites an invalid file, it
reports the checklist as unavailable instead.
"""

import dataclasses
from pathlib import Path

from chipcompiler.utility.json import json_read

CHECKLIST_PATH = ("home", "checklist.json")

STATE_MARKS = {
    "pass": "[PASS]    ",
    "failed": "[BLOCK]   ",
    "warning": "[WARN]    ",
    "unavailable": "[N/A]     ",
}


@dataclasses.dataclass(frozen=True)
class ChecklistItemView:
    id: str
    step: str
    category: str
    title: str
    state: str
    policy: str
    blocked: bool
    summary: str
    evidence: tuple = ()


@dataclasses.dataclass
class ChecklistReport:
    available: bool = False
    workspace: str = ""
    status: str = "unavailable"
    generated_at: str = ""
    checker_revision: str = ""
    summary: dict = dataclasses.field(default_factory=dict)
    items: list = dataclasses.field(default_factory=list)

    @property
    def blocked_items(self) -> list:
        return [item for item in self.items if item.blocked]

    @property
    def attention_items(self) -> list:
        return [item for item in self.items if item.state == "warning"]


def build_checklist_report(workspace) -> ChecklistReport:
    workspace_root = Path(workspace.directory or "")
    data = json_read(workspace_root.joinpath(*CHECKLIST_PATH))
    report = ChecklistReport(workspace=str(workspace_root))
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 3
        or data.get("kind") != "signoff_checklist"
        or not isinstance(data.get("checklist"), list)
    ):
        return report

    items = []
    for raw in data["checklist"]:
        if not isinstance(raw, dict):
            continue
        state = raw.get("state") if raw.get("state") in STATE_MARKS else "unavailable"
        policy = raw.get("policy") if raw.get("policy") in ("block", "warn") else "warn"
        evidence = raw.get("evidence")
        items.append(
            ChecklistItemView(
                id=str(raw.get("id") or ""),
                step=str(raw.get("step") or "workspace"),
                category=str(raw.get("category") or "report"),
                title=str(raw.get("title") or raw.get("item") or "Checklist item"),
                state=state,
                policy=policy,
                blocked=bool(
                    raw.get("blocked", policy == "block" and state in ("failed", "unavailable"))
                ),
                summary=str(raw.get("summary") or raw.get("info") or ""),
                evidence=tuple(e for e in evidence if isinstance(e, str))
                if isinstance(evidence, list)
                else (),
            )
        )

    report.available = True
    report.status = data.get("status") if isinstance(data.get("status"), str) else "ready"
    report.generated_at = (
        data.get("generated_at") if isinstance(data.get("generated_at"), str) else ""
    )
    report.checker_revision = (
        data.get("checker_revision") if isinstance(data.get("checker_revision"), str) else ""
    )
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    report.summary = {
        key: summary.get(key, 0) for key in ("passed", "blocked", "attention", "unavailable")
    }
    report.items = items
    return report


WIDTH = 78


def _pad(text: str, width: int) -> str:
    return text if len(text) >= width else text + " " * (width - len(text))


def generate_checklist_report(workspace) -> str:
    """Render the signoff checklist as a text report."""
    report = build_checklist_report(workspace)
    lines: list[str] = []
    title = "  ECC SIGNOFF CHECKLIST REPORT  "
    side = max(0, (WIDTH - len(title)) // 2)
    lines.append("=" * side + title + "=" * (WIDTH - side - len(title)))
    if not report.available:
        lines.append("Checklist unavailable: no valid home/checklist.json found.")
        lines.append("Run the flow (or `ecc signoff inspect`) to build it.")
        lines.append("=" * WIDTH)
        return "\n".join(lines)

    summary = report.summary
    lines.append(f"Status        : {report.status.upper()}")
    lines.append(
        f"Summary       : {summary.get('passed', 0)} passed, {summary.get('blocked', 0)} blocked, "
        f"{summary.get('attention', 0)} attention, {summary.get('unavailable', 0)} unavailable"
    )
    lines.append(f"Items         : {len(report.items)}")
    if report.checker_revision:
        lines.append(f"Revision      : {report.checker_revision}")
    if report.generated_at:
        lines.append(f"Generated at  : {report.generated_at}")
    lines.append("=" * WIDTH)
    lines.append("")

    def detail_section(heading: str, items: list) -> None:
        if not items:
            return
        lines.append(f"[ {heading} ]")
        lines.append("-" * WIDTH)
        for item in items:
            lines.append(f"  {item.step} / {item.category} — {item.title}")
            if item.summary:
                lines.append(f"      {item.summary}")
            for path in item.evidence[:3]:
                lines.append(f"      evidence: {path}")
            if len(item.evidence) > 3:
                lines.append(f"      ... +{len(item.evidence) - 3} more evidence entries")
        lines.append("")

    detail_section("BLOCKED ITEMS (policy=block, failed/unavailable)", report.blocked_items)
    detail_section("ATTENTION ITEMS (warnings)", report.attention_items)

    lines.append("[ FULL CHECKLIST ]")
    lines.append("-" * WIDTH)
    lines.append(f"  {_pad('Step', 12)} {_pad('Category', 18)} {_pad('Item', 32)} State")
    lines.append("  " + "-" * (WIDTH - 4))
    for item in report.items:
        mark = STATE_MARKS[item.state]
        lines.append(
            f"  {_pad(item.step, 12)} {_pad(item.category, 18)}"
            f" {_pad(item.title, 32)} {mark.strip()}"
        )

    lines.append("")
    lines.append("=" * WIDTH)
    lines.append("END OF CHECKLIST REPORT")
    return "\n".join(lines)
