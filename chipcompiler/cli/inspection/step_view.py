"""Read-only per-step view records for `ecc report step`.

Assembles overview and detail records from a workspace's current step
artifacts: ``home/flow.json`` states, ``feature/<Step>.step.json`` run facts,
``feature/<Step>.db.json`` design stats, ``analysis/qor_metrics.json`` and
``analysis/qor_summary.json`` (schema v3/v4 quality-gates payloads), and the
per-step ``checklist.json`` (schema v3 contract). Nothing is refreshed or
rewritten; missing artifacts render as unavailable sections.
"""

import json
import os
from dataclasses import dataclass

from chipcompiler.utility.json import json_read

SECTIONS = ("feature", "analysis", "checklist")

_HOME_CHECKLIST_PATH = ("home", "checklist.json")
_MAX_FLATTEN_DEPTH = 3


def _rel(path: str, workspace_dir: str) -> str:
    try:
        return os.path.relpath(path, workspace_dir)
    except ValueError:
        return path


@dataclass
class _StepEntry:
    token: str  # canonical CLI token (dir token when artifacts exist)
    display: str  # internal/flow step name for display
    tool: str
    directory: str | None
    flow: dict | None  # raw home/flow.json step record
    aliases: frozenset[str]

    def state(self) -> str:
        from chipcompiler.cli.core.output import normalize_state

        if self.flow is not None:
            return normalize_state(self.flow.get("state", ""))
        return "unknown"  # dir-discovered step with no flow record

    def runtime(self) -> str | None:
        runtime = (self.flow or {}).get("runtime", "")
        return str(runtime) if runtime else None

    def peak_memory_mb(self):
        return (self.flow or {}).get("peak memory (mb)")


def _step_entries(workspace_dir: str) -> list[_StepEntry]:
    """Flow steps in flow order plus dir-discovered extras, dir-associated.

    A flow step links to its step directory on token equality, the
    underscore alias of its token ("Timing optimization" -> "timing_optimization"),
    or a tool-suffixed dir token ("postroutelec" -> "postroutelec_yosys").
    """
    from chipcompiler.cli.core.output import normalize_step_name
    from chipcompiler.cli.inspection.discovery import (
        discover_step_dirs,
        read_flow_json,
    )

    flow_data = read_flow_json(workspace_dir)
    flow_steps = flow_data.get("steps", []) if isinstance(flow_data, dict) else []
    flow_steps = [s for s in flow_steps if isinstance(s, dict) and s.get("name")]
    dir_tokens = discover_step_dirs(workspace_dir)

    entries: list[_StepEntry] = []
    taken_dirs: set[str] = set()
    for flow_step in flow_steps:
        name = str(flow_step["name"])
        token = normalize_step_name(name)
        alias = token.replace(" ", "_")
        matched = None
        for dir_token in dir_tokens:
            if dir_token in taken_dirs:
                continue
            if dir_token in (token, alias) or dir_token.startswith(f"{alias}_"):
                matched = dir_token
                taken_dirs.add(dir_token)
                break
        entries.append(
            _StepEntry(
                token=matched or token,
                display=name,
                tool=str(flow_step.get("tool", "")),
                directory=dir_tokens.get(matched) if matched else None,
                flow=flow_step,
                aliases=frozenset(
                    {token.lower(), alias.lower(), name.lower(), *({matched} if matched else ())}
                ),
            )
        )
    for dir_token, dir_path in sorted(dir_tokens.items()):
        if dir_token not in taken_dirs:
            entries.append(
                _StepEntry(
                    token=dir_token,
                    display=dir_token,
                    tool=os.path.basename(dir_path).rpartition("_")[2],
                    directory=dir_path,
                    flow=None,
                    aliases=frozenset({dir_token.lower()}),
                )
            )
    return entries


def _resolve_entry(entries: list[_StepEntry], token: str) -> _StepEntry | None:
    wanted = token.strip().lower()
    return next((e for e in entries if wanted in e.aliases), None)


# --- feature ---------------------------------------------------------------


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 120 else text[:117] + "..."


def _flatten(prefix: str, value, depth: int = 0):
    """Yield (dotted key, scalar leaf) pairs for nested dict payloads."""
    if isinstance(value, dict) and depth < _MAX_FLATTEN_DEPTH:
        for key in sorted(value):
            yield from _flatten(f"{prefix}.{key}" if prefix else str(key), value[key], depth + 1)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        yield prefix, value
    else:
        yield prefix, _short(value)


def _feature_records(entry: _StepEntry, workspace_dir: str) -> list[dict]:
    records = []
    directory = entry.directory
    if directory is None:
        return records
    feature_dir = os.path.join(directory, "feature")
    if not os.path.isdir(feature_dir):
        return records

    def json_files(suffix: str) -> list[str]:
        return sorted(
            f
            for f in os.listdir(feature_dir)
            if f.endswith(suffix) and os.path.isfile(os.path.join(feature_dir, f))
        )

    # *.step.json: run facts + tool facts; *.db.json: grouped design stats.
    for suffix, default_kind in ((".step.json", "fact"), (".db.json", "stat")):
        for filename in json_files(suffix):
            path = os.path.join(feature_dir, filename)
            payload = json_read(path)
            if not isinstance(payload, dict) or not payload:
                continue
            source = _rel(path, workspace_dir)
            for key, value in payload.items():
                kind = {"run": "run", "constraints": "constraint"}.get(key, default_kind)
                for leaf, leaf_value in _flatten(str(key), value):
                    records.append(
                        {
                            "step": entry.token,
                            "section": "feature",
                            "kind": kind,
                            "key": leaf,
                            "value": leaf_value,
                            "source": source,
                        }
                    )
    return records


# --- analysis --------------------------------------------------------------


def _analysis_records(entry: _StepEntry, workspace_dir: str) -> list[dict]:
    records = []
    directory = entry.directory
    if directory is None:
        return records
    metrics_payload = json_read(os.path.join(directory, "analysis", "qor_metrics.json"))
    summary_payload = json_read(os.path.join(directory, "analysis", "qor_summary.json"))

    if not isinstance(metrics_payload, dict) or not isinstance(
        metrics_payload.get("metrics"), list
    ):
        return records

    if isinstance(summary_payload, dict) and summary_payload:
        summary = {
            "step": entry.token,
            "section": "analysis",
            "kind": "summary",
            "quality_status": summary_payload.get("quality_status"),
            "analysis_status": summary_payload.get("analysis_status"),
            "metric_count": summary_payload.get("metric_count"),
            "dimensions": summary_payload.get("dimensions", {}),
            "missing_metrics": summary_payload.get("missing_metrics", []),
        }
        if summary_payload.get("analysis_revision"):
            summary["analysis_revision"] = summary_payload["analysis_revision"]
        records.append(summary)

    for metric in metrics_payload["metrics"]:
        if not isinstance(metric, dict):
            continue
        source = metric.get("source") if isinstance(metric.get("source"), dict) else {}
        source_ref = ""
        if source.get("path"):
            source_ref = f"{os.path.basename(directory)}/{source['path']}"
            if source.get("selector"):
                source_ref = f"{source_ref}#{source['selector']}"
        rating = metric.get("rating") if isinstance(metric.get("rating"), dict) else {}
        records.append(
            {
                "step": entry.token,
                "section": "analysis",
                "kind": "metric",
                "metric": metric.get("id", ""),
                "label": metric.get("display_name") or metric.get("id", ""),
                "value": metric.get("value"),
                "unit": metric.get("unit"),
                "category": metric.get("category"),
                "direction": metric.get("direction"),
                "role": metric.get("project_role"),
                "gate": bool(rating.get("gate")),
                "score": bool(rating.get("score")),
                "source": source_ref,
            }
        )

    gates = summary_payload.get("gates") if isinstance(summary_payload, dict) else []
    for gate in gates if isinstance(gates, list) else []:
        if not isinstance(gate, dict):
            continue
        records.append(
            {
                "step": entry.token,
                "section": "analysis",
                "kind": "gate",
                "gate": gate.get("id", ""),
                "title": gate.get("title", ""),
                "state": gate.get("state", ""),
                "blocking": bool(gate.get("blocking")),
                "checks": [
                    {
                        "metric": check.get("id", ""),
                        "actual": check.get("actual"),
                        "operator": check.get("operator", ""),
                        "expected": check.get("expected"),
                    }
                    for check in gate.get("metrics", [])
                    if isinstance(check, dict)
                ],
            }
        )
    return records


# --- checklist -------------------------------------------------------------


def _checklist_records(entry: _StepEntry, workspace_dir: str) -> list[dict]:
    directory = entry.directory
    if directory is None:
        return []
    step_data = json_read(os.path.join(directory, "checklist.json"))
    if isinstance(step_data, dict) and isinstance(step_data.get("checklist"), list):
        data, source = step_data, "step"
    else:
        home = json_read(os.path.join(workspace_dir, *_HOME_CHECKLIST_PATH))
        names = set(entry.aliases) | {entry.display.lower()}
        items = [
            item
            for item in (home.get("checklist", []) if isinstance(home, dict) else [])
            if isinstance(item, dict) and str(item.get("step", "")).lower() in names
        ]
        if not items:
            return []
        counts = {"passed": 0, "blocked": 0, "attention": 0, "unavailable": 0}
        for item in items:
            if item.get("blocked"):
                counts["blocked"] += 1
            else:
                state = item.get("state")
                counts[
                    "passed"
                    if state == "pass"
                    else "unavailable"
                    if state == "unavailable"
                    else "attention"
                ] += 1
        data = {
            "checklist": items,
            "status": "blocked"
            if counts["blocked"]
            else "attention"
            if counts["attention"]
            else "ready",
            "summary": counts,
        }
        source = "home"

    summary: dict = {}
    raw_summary = data.get("summary")
    if isinstance(raw_summary, dict):
        summary = raw_summary
    records = [
        {
            "step": entry.token,
            "section": "checklist",
            "kind": "summary",
            "checklist_status": data.get("status"),
            "source": source,
            "passed": summary.get("passed", 0),
            "blocked": summary.get("blocked", 0),
            "attention": summary.get("attention", 0),
            "unavailable": summary.get("unavailable", 0),
        }
    ]
    for item in data.get("checklist", []):
        if not isinstance(item, dict):
            continue
        evidence = [
            e.get("path", "")
            for e in item.get("evidence", [])
            if isinstance(e, dict) and e.get("path")
        ]
        records.append(
            {
                "step": entry.token,
                "section": "checklist",
                "kind": "item",
                "id": item.get("id", ""),
                "category": item.get("category", ""),
                "title": item.get("title", ""),
                "state": item.get("state", ""),
                "policy": item.get("policy", ""),
                "blocked": bool(item.get("blocked")),
                "summary": item.get("summary", ""),
                "evidence": evidence,
            }
        )
    return records


# --- public builders -------------------------------------------------------


def build_step_overview_records(workspace_dir: str, project=None, run_id=None) -> list[dict]:
    from chipcompiler.cli.core.output import disclosure_cmd

    entries = _step_entries(workspace_dir)
    records = [
        {
            "report": "step",
            "view": "overview",
            "workspace": workspace_dir,
            "steps": len(entries),
            "inspect": disclosure_cmd("ecc report step <step>", project, run_id),
        }
    ]
    if not entries:
        records[0]["step_status"] = "no_steps"
        records[0]["run"] = disclosure_cmd("ecc run", project, run_id)
        return records

    for entry in entries:
        metrics = quality = checklist_status = None
        blocked = 0
        if entry.directory is not None:
            summary = json_read(os.path.join(entry.directory, "analysis", "qor_summary.json"))
            metrics = summary.get("metric_count") if isinstance(summary, dict) else None
            quality = summary.get("quality_status") if isinstance(summary, dict) else None
            checklist = json_read(os.path.join(entry.directory, "checklist.json"))
            checklist_status = checklist.get("status") if isinstance(checklist, dict) else None
            blocked = (
                checklist.get("summary", {}).get("blocked", 0) if isinstance(checklist, dict) else 0
            )
        records.append(
            {
                "step": entry.token,
                "tool": entry.tool,
                "status": entry.state(),
                "runtime": entry.runtime(),
                "peak_memory_mb": entry.peak_memory_mb(),
                "metrics": metrics,
                "quality": quality,
                "checklist": checklist_status,
                "blocked": blocked,
                "inspect": disclosure_cmd(f"ecc report step {entry.token}", project, run_id),
            }
        )
    return records


def build_step_detail_records(
    workspace_dir: str, token: str, sections, project=None, run_id=None
) -> list[dict] | None:
    """Detail records for one step, or None when the token is unknown."""
    entry = _resolve_entry(_step_entries(workspace_dir), token)
    if entry is None:
        return None

    records = [
        {
            "report": "step",
            "view": "detail",
            "step": entry.token,
            "step_name": entry.display,
            "tool": entry.tool,
            "status": entry.state(),
            "runtime": entry.runtime(),
            "peak_memory_mb": entry.peak_memory_mb(),
            "workspace": workspace_dir,
            "sections": list(sections),
        }
    ]
    for section in sections:
        if section == "feature":
            section_records = _feature_records(entry, workspace_dir) if entry.directory else []
        elif section == "analysis":
            section_records = _analysis_records(entry, workspace_dir) if entry.directory else []
        else:
            section_records = _checklist_records(entry, workspace_dir) if entry.directory else []
        if not section_records:
            records.append(
                {"step": entry.token, "section": section, "section_status": "unavailable"}
            )
        else:
            records.extend(section_records)
    return records


def available_step_tokens(workspace_dir: str) -> list[str]:
    return [entry.token for entry in _step_entries(workspace_dir)]


# --- TEXT rendering --------------------------------------------------------


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return "-" if value is None else str(value)


def render_step_overview_text(records) -> None:
    head = records[0]
    print("[report step]")
    print(f"  workspace : {head['workspace']}")
    if head.get("step_status") == "no_steps":
        print("  steps     : none")
        print(f"  start     : {head['run']}")
        return
    print(f"  steps     : {head['steps']}")
    print()
    print(
        f"  {'step':22s} {'tool':12s} {'status':9s} {'runtime':8s} "
        f"{'peak MB':8s} {'metrics':7s} {'quality':8s} checklist"
    )
    for record in records[1:]:
        checklist = record["checklist"] or "-"
        if record["blocked"]:
            checklist = f"{checklist} ({record['blocked']} blocked)"
        print(
            f"  {record['step']:22s} {record['tool']:12s} {record['status']:9s} "
            f"{record['runtime'] or '-':8s} {_fmt(record['peak_memory_mb']):8s} "
            f"{_fmt(record['metrics']):7s} "
            f"{record['quality'] or '-':8s} {checklist}"
        )
    print()
    print(f"  detail    : {head['inspect']}")


def _render_detail_section(records, section: str) -> None:
    print(f"  {section}:")
    section_records = [r for r in records if r.get("section") == section]
    if not section_records or "section_status" in section_records[0]:
        print("    unavailable")
        return
    for record in section_records:
        kind = record.get("kind")
        if section == "feature":
            print(f"    {record['key']:44s} {_fmt(record['value'])}")
        elif kind == "summary":
            if section == "analysis":
                quality = record.get("quality_status") or "-"
                print(
                    f"    quality: {quality}  ({record.get('metric_count', '-')} metrics,"
                    f" {len(record.get('missing_metrics', []))} missing)"
                )
            else:
                print(
                    f"    status: {record.get('checklist_status') or '-'} "
                    f"(passed {record['passed']}, blocked {record['blocked']}, "
                    f"attention {record['attention']}, unavailable {record['unavailable']})"
                )
        elif kind == "metric":
            flags = record["category"] or "-"
            if record["role"]:
                flags = f"{flags}/{record['role']}"
            unit = f" {record['unit']}" if record["unit"] else ""
            print(
                f"    {record['label']} ({record['metric']}): {_fmt(record['value'])}{unit}"
                f"  [{flags}]"
            )
        elif kind == "gate":
            checks = ", ".join(
                f"{c['metric']}={_fmt(c['actual'])} {c['operator']} {_fmt(c['expected'])}"
                for c in record["checks"]
            )
            mark = "BLOCK" if record["blocking"] else record["state"]
            print(f"    [{mark}] {record['gate']} — {checks}")
        elif kind == "item":
            print(f"    [{record['state']}] {record['title']} — {record['summary']}")
            for path in record["evidence"][:3]:
                print(f"        evidence: {path}")


def render_step_detail_text(records) -> None:
    head = records[0]
    print("[report step]")
    print(f"  step      : {head['step']} ({head.get('step_name') or head['step']})")
    print(f"  tool      : {head['tool']}")
    print(f"  status    : {head['status']}")
    if head.get("runtime"):
        peak = ""
        if head.get("peak_memory_mb") is not None:
            peak = f", peak {head['peak_memory_mb']:g} MB"
        print(f"  runtime   : {head['runtime']}{peak}")
    print(f"  workspace : {head['workspace']}")
    for section in head.get("sections", ()):
        print()
        _render_detail_section(records, section)
