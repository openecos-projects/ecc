"""Current-output signoff checklist construction.

QoR owns the five chip-quality gate calculations.  This module only references
those gate results and owns the separate flow, artifact, and provenance checks
needed to assemble a signoff package.
"""

from __future__ import annotations

import re
from pathlib import Path

from chipcompiler.data import Checklist, StateEnum, StepEnum, Workspace, WorkspaceStep
from chipcompiler.utility import json_read

_STEP_DIRECTORIES = {
    StepEnum.SYNTHESIS.value: "Synthesis_yosys",
    StepEnum.FLOORPLAN.value: "Floorplan_ecc",
    StepEnum.NETLIST_OPT.value: "fixFanout_ecc",
    StepEnum.PLACEMENT.value: "place_dreamplace",
    StepEnum.CTS.value: "CTS_ecc",
    StepEnum.LEGALIZATION.value: "legalization_dreamplace",
    StepEnum.ROUTING.value: "route_ecc",
    StepEnum.DRC.value: "drc_ecc",
    StepEnum.FILLER.value: "filler_ecc",
    StepEnum.RCX.value: "RCX_ecc",
    StepEnum.STA.value: "sta_ecc",
    StepEnum.HARDEN.value: "Harden_ecc",
}

_QUALITY_GATES_BY_STEP = {
    StepEnum.DRC.value: ("qor.drc.clean",),
    StepEnum.RCX.value: (
        "qor.rcx.corner_coverage",
        "qor.rcx.spef_parse_health",
    ),
    StepEnum.STA.value: (
        "qor.sta.setup_closed",
        "qor.sta.hold_closed",
    ),
}

_REQUIRED_FLOW_STEPS = (
    StepEnum.ROUTING.value,
    StepEnum.DRC.value,
    StepEnum.FILLER.value,
    StepEnum.RCX.value,
    StepEnum.STA.value,
    StepEnum.HARDEN.value,
)

_CONFIG_FILENAMES = {
    "flow": "flow_config.json",
    "db": "db_default_config.json",
    StepEnum.RCX.value: "rcx.json",
    StepEnum.STA.value: "sta.json",
}


def _path_text(workspace: Workspace, path: Path | str | None) -> str:
    if not path:
        return ""
    value = Path(path)
    workspace_directory = getattr(workspace, "directory", None)
    if not workspace_directory:
        return str(value)
    try:
        return value.relative_to(Path(workspace_directory)).as_posix()
    except ValueError:
        return str(value)


def _step_directory(step: WorkspaceStep) -> Path:
    directory = getattr(step, "directory", None)
    if directory:
        return Path(directory)
    checklist_path = step.checklist.get("path") if isinstance(step.checklist, dict) else None
    if checklist_path:
        return Path(checklist_path).parent
    return Path(".")


def _file_state(path: Path | str | None) -> tuple[str, str]:
    if not path:
        return "unavailable", "No current output path is configured."
    value = Path(path)
    if not value.is_file():
        return "failed", "Required file is missing."
    if value.stat().st_size <= 0:
        return "failed", "Required file is empty."
    return "pass", "Current output is present and non-empty."


def _item(
    *,
    item_id: str,
    step: str,
    category: str,
    owner: str,
    policy: str,
    state: str,
    title: str,
    summary: str,
    source: dict | None = None,
    evidence: list[dict] | None = None,
) -> dict:
    return {
        "id": item_id,
        "step": step,
        "category": category,
        "owner": owner,
        "policy": policy,
        "state": state,
        "blocked": policy == "block" and state in {"failed", "unavailable"},
        "title": title,
        "summary": summary,
        "source": source or {},
        "evidence": evidence or [],
    }


def _prefixed_evidence(step_directory: str, evidence: list) -> list[dict]:
    result = []
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        path = item.get("path")
        if isinstance(path, str) and path and not path.startswith(step_directory + "/"):
            item["path"] = f"{step_directory}/{path}"
        result.append(item)
    return result


def _gate_summary(gate: dict) -> str:
    facts = []
    for metric in gate.get("metrics", []):
        if not isinstance(metric, dict):
            continue
        metric_id = metric.get("id")
        if not isinstance(metric_id, str):
            continue
        facts.append(
            f"{metric_id}={metric.get('actual')} "
            f"(required {metric.get('operator')} {metric.get('expected')})"
        )
    return "; ".join(facts) or "QoR gate has no current metric evidence."


def _quality_gate_items_from_summary(
    workspace: Workspace,
    step_name: str,
    step_directory: Path,
    summary_path: Path,
) -> list[dict]:
    expected_gate_ids = _QUALITY_GATES_BY_STEP.get(step_name, ())
    if not expected_gate_ids:
        return []
    step_directory_text = _path_text(workspace, step_directory)
    summary = json_read(summary_path)
    gates = (
        {
            gate.get("id"): gate
            for gate in summary.get("gates", [])
            if isinstance(gate, dict) and isinstance(gate.get("id"), str)
        }
        if isinstance(summary, dict) and summary.get("schema_version") == 4
        else {}
    )
    result = []
    for gate_id in expected_gate_ids:
        gate = gates.get(gate_id)
        if gate is None:
            result.append(
                _item(
                    item_id=f"quality.{gate_id.removeprefix('qor.')}",
                    step=step_name,
                    category="quality_gate",
                    owner="qor",
                    policy="block",
                    state="unavailable",
                    title=gate_id,
                    summary="Current QoR gate is unavailable; rerun analysis for this step.",
                    source={
                        "kind": "qor_gate",
                        "path": _path_text(workspace, summary_path),
                        "gate_id": gate_id,
                    },
                )
            )
            continue
        state = gate.get("state")
        state = state if state in {"pass", "failed", "unavailable"} else "unavailable"
        result.append(
            _item(
                item_id=f"quality.{gate_id.removeprefix('qor.')}",
                step=step_name,
                category="quality_gate",
                owner="qor",
                policy="block",
                state=state,
                title=str(gate.get("title") or gate_id),
                summary=_gate_summary(gate),
                source={
                    "kind": "qor_gate",
                    "path": _path_text(workspace, summary_path),
                    "gate_id": gate_id,
                },
                evidence=_prefixed_evidence(step_directory_text, gate.get("evidence", [])),
            )
        )
    return result


def _quality_gate_items(workspace: Workspace, step: WorkspaceStep) -> list[dict]:
    step_directory = _step_directory(step)
    summary_path = step.analysis.get("qor_summary") if isinstance(step.analysis, dict) else None
    return _quality_gate_items_from_summary(
        workspace,
        step.name,
        step_directory,
        Path(summary_path) if summary_path else step_directory / "analysis" / "qor_summary.json",
    )


def _step_artifact_items(workspace: Workspace, step: WorkspaceStep) -> list[dict]:
    if step.name == StepEnum.HARDEN.value:
        artifacts = (
            ("gds", "Harden GDS", step.output.get("gds")),
            ("lef", "Harden LEF", step.output.get("lef")),
            ("lib", "Harden LIB", step.output.get("lib")),
        )
    elif step.name == StepEnum.RCX.value:
        spefs = step.output.get("spef", [])
        files = [Path(path) for path in spefs] if isinstance(spefs, list) else []
        if not files:
            output_dir = step.output.get("dir")
            files = sorted(Path(output_dir).glob("*.spef")) if output_dir else []
        state = (
            "pass" if files and all(_file_state(path)[0] == "pass" for path in files) else "failed"
        )
        return [
            _item(
                item_id="artifact.rcx.spef_outputs",
                step=step.name,
                category="artifact",
                owner="checklist",
                policy="block",
                state=state,
                title="RCX SPEF outputs",
                summary=(
                    f"{len(files)} current SPEF output files are present."
                    if state == "pass"
                    else "Current RCX SPEF output files are missing or empty."
                ),
                source={"kind": "output", "path": _path_text(workspace, step.output.get("dir"))},
                evidence=[
                    {"kind": "output", "path": _path_text(workspace, path)} for path in files
                ],
            )
        ]
    elif step.name == StepEnum.STA.value:
        report_dir = step.report.get("dir")
        feature_dir = step.feature.get("dir")
        reports = (
            list(Path(report_dir).rglob("*.rpt"))
            if report_dir and Path(report_dir).is_dir()
            else []
        )
        summaries = (
            list(Path(feature_dir).rglob("qor_summary.json"))
            if feature_dir and Path(feature_dir).is_dir()
            else []
        )
        return [
            _item(
                item_id="report.sta.timing_reports",
                step=step.name,
                category="report",
                owner="checklist",
                policy="block",
                state="pass" if reports else "failed",
                title="STA timing reports",
                summary=(
                    f"{len(reports)} current STA report files are present."
                    if reports
                    else "No STA report files are present."
                ),
                source={"kind": "report", "path": _path_text(workspace, report_dir)},
                evidence=[
                    {"kind": "report", "path": _path_text(workspace, path)} for path in reports
                ],
            ),
            _item(
                item_id="artifact.sta.corner_summaries",
                step=step.name,
                category="artifact",
                owner="checklist",
                policy="block",
                state="pass" if summaries else "failed",
                title="STA structured corner summaries",
                summary=(
                    f"{len(summaries)} current STA corner summaries are present."
                    if summaries
                    else "No structured STA corner summaries are present."
                ),
                source={"kind": "feature", "path": _path_text(workspace, feature_dir)},
                evidence=[
                    {"kind": "feature", "path": _path_text(workspace, path)} for path in summaries
                ],
            ),
        ]
    elif step.name == StepEnum.SYNTHESIS.value:
        artifacts = (("netlist", "Mapped synthesis netlist", step.output.get("verilog")),)
    else:
        return []

    items = []
    for key, title, path in artifacts:
        state, summary = _file_state(path)
        items.append(
            _item(
                item_id=f"artifact.{step.name.lower()}.{key}",
                step=step.name,
                category="artifact",
                owner="checklist",
                policy="block",
                state=state,
                title=title,
                summary=summary,
                source={"kind": "output", "path": _path_text(workspace, path)},
                evidence=[{"kind": "output", "path": _path_text(workspace, path)}] if path else [],
            )
        )
    return items


def refresh_step_checklist(workspace: Workspace, step: WorkspaceStep) -> bool:
    """Replace one step checklist with its current signoff-relevant evidence."""
    checklist_path = Path(step.checklist.get("path", _step_directory(step) / "checklist.json"))
    checklist_path.parent.mkdir(parents=True, exist_ok=True)
    checklist = Checklist(checklist_path)
    items = [*_quality_gate_items(workspace, step), *_step_artifact_items(workspace, step)]
    step.checklist["checklist"] = checklist.replace(items)
    if getattr(workspace, "directory", None):
        rebuild_home_checklist(workspace)
    return not any(item["blocked"] for item in step.checklist["checklist"])


def _flow_items(workspace: Workspace) -> list[dict]:
    flow_data = getattr(getattr(workspace, "flow", None), "data", {})
    if not isinstance(flow_data, dict) or not flow_data.get("steps"):
        workspace_directory = getattr(workspace, "directory", None)
        flow_data = (
            json_read(Path(workspace_directory) / "home" / "flow.json")
            if workspace_directory
            else {}
        )
    flow_steps = flow_data.get("steps", []) if isinstance(flow_data, dict) else []
    states = {
        item.get("name"): item.get("state")
        for item in flow_steps
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    items = []
    for step in _REQUIRED_FLOW_STEPS:
        state = "pass" if states.get(step) == StateEnum.Success.value else "failed"
        items.append(
            _item(
                item_id=f"flow.{step.lower()}.completed",
                step=step,
                category="flow",
                owner="checklist",
                policy="block",
                state=state,
                title=f"{step} flow completed",
                summary=(
                    "Required flow stage completed successfully."
                    if state == "pass"
                    else f"Current flow state is {states.get(step) or 'missing'}."
                ),
                source={"kind": "flow", "path": "home/flow.json", "step": step},
                evidence=[{"kind": "flow", "path": "home/flow.json", "selector": f"/steps/{step}"}],
            )
        )
    return items


def _workspace_items(workspace: Workspace) -> list[dict]:
    workspace_directory = Path(workspace.directory)
    origin_directory = workspace_directory / "origin"
    design = getattr(workspace, "design", None)
    pdk = getattr(workspace, "pdk", None)
    config = getattr(workspace, "config", {})
    config = config if isinstance(config, dict) else {}
    origin_verilog = getattr(design, "origin_verilog", None)
    if not origin_verilog:
        origin_verilog = next(iter(sorted(origin_directory.glob("*.v*"))), None)
    origin_sdc = getattr(pdk, "sdc", None)
    if not origin_sdc:
        origin_sdc = next(iter(sorted(origin_directory.glob("*.sdc"))), None)
    config_keys = ("flow", "db", StepEnum.RCX.value, StepEnum.STA.value)
    inputs = (
        ("provenance.initial.rtl", "Initial RTL", origin_verilog),
        ("provenance.initial.sdc", "Initial SDC", origin_sdc),
        *(
            (
                f"configuration.{key.lower()}",
                f"Configuration {key}",
                config.get(key, workspace_directory / "config" / _CONFIG_FILENAMES[key]),
            )
            for key in config_keys
        ),
    )
    items = []
    for item_id, title, path in inputs:
        state, summary = _file_state(path)
        category = "configuration" if item_id.startswith("configuration.") else "provenance"
        items.append(
            _item(
                item_id=item_id,
                step="workspace",
                category=category,
                owner="checklist",
                policy="block",
                state=state,
                title=title,
                summary=summary,
                source={"kind": category, "path": _path_text(workspace, path)},
                evidence=[{"kind": category, "path": _path_text(workspace, path)}] if path else [],
            )
        )
    return items


def _package_items(resource_issues) -> list[dict]:
    items = []
    for issue in resource_issues or []:
        if getattr(issue, "kind", "") == "flow":
            continue
        required = bool(getattr(issue, "required", False))
        destination = str(getattr(issue, "destination", "resource"))
        label = str(getattr(issue, "label", "Signoff package resource"))
        location = str(getattr(issue, "location", destination))
        reason = str(getattr(issue, "reason", "Package resource requires attention."))
        item_id = re.sub(r"[^a-z0-9]+", ".", f"package.{destination}".lower()).strip(".")
        items.append(
            _item(
                item_id=item_id,
                step="workspace",
                category=(
                    "report"
                    if getattr(issue, "kind", "") in {"analysis", "freshness"}
                    else "artifact"
                ),
                owner="checklist",
                policy="block" if required else "warn",
                state="failed" if required else "warning",
                title=label,
                summary=reason,
                source={"kind": "package", "path": location, "destination": destination},
                evidence=[{"kind": "package", "path": location, "destination": destination}],
            )
        )
    return items


def rebuild_home_checklist(workspace: Workspace, resource_issues=None) -> dict:
    """Replace the aggregate workspace checklist from current step snapshots."""
    workspace_directory = getattr(workspace, "directory", None)
    if not workspace_directory:
        return {}
    workspace_dir = Path(workspace_directory)
    items = []
    for directory in _STEP_DIRECTORIES.values():
        data = json_read(workspace_dir / directory / "checklist.json")
        if data.get("schema_version") == 3 and data.get("kind") == "signoff_checklist":
            items.extend(item for item in data.get("checklist", []) if isinstance(item, dict))
    for step_name in _QUALITY_GATES_BY_STEP:
        step_directory = workspace_dir / _STEP_DIRECTORIES[step_name]
        items.extend(
            _quality_gate_items_from_summary(
                workspace,
                step_name,
                step_directory,
                step_directory / "analysis" / "qor_summary.json",
            )
        )
    items.extend(_flow_items(workspace))
    items.extend(_workspace_items(workspace))
    items.extend(_package_items(resource_issues))

    # Package errors are refreshed as a group.  Deduplicate by requirement id
    # so resource collection cannot leave stale copies behind.
    deduplicated = {}
    for item in items:
        if isinstance(item, dict):
            deduplicated[item.get("id")] = item
    checklist_path = workspace.home.data.get("checklist", workspace_dir / "home" / "checklist.json")
    checklist = Checklist(checklist_path)
    checklist.replace(list(deduplicated.values()))
    return checklist.data
