#!/usr/bin/env python
"""Read-only preflight facts for workspace step execution."""

from dataclasses import asdict, fields
from pathlib import Path

_PDK_MAPPING_STEPS = frozenset({"filler", "Harden"})
_PDK_SDC_STEPS = frozenset({"sta", "powerAnalysis", "Harden"})


def _issue(component: str, detail: str, remediation: str, *, required: bool = True) -> dict:
    return {
        "component": component,
        "status": "fail",
        "required": required,
        "detail": detail,
        "remediation": remediation,
    }


def pdk_issues_for_config(cfg, step_names) -> list[dict]:
    """Validate the project-selected PDK before a fresh workspace is created."""
    if cfg is None:
        return []

    from chipcompiler.cli.project.config import resolve_pdk_overrides, resolve_pdk_root
    from chipcompiler.data.pdk import get_pdk

    root = resolve_pdk_root(cfg)
    if not root:
        return [
            _issue(
                "pdk",
                f"pdk.name={cfg.pdk_name}",
                "Set pdk.root in ecc.toml, or export CHIPCOMPILER_ICS55_PDK_ROOT / "
                "ICS55_PDK_ROOT pointing at the icsprout55-pdk checkout.",
            )
        ]
    try:
        pdk = get_pdk(cfg.pdk_name, root, overrides=resolve_pdk_overrides(cfg))
    except (OSError, ValueError) as exc:
        return [_issue("pdk", root, str(exc))]
    # SDC is generated during workspace creation, so only the PDK contents
    # and target-specific mapping requirement can be checked here.
    return pdk_issues(pdk, step_names, check_sdc=False)


def pdk_issues(pdk, step_names, *, check_sdc: bool = True) -> list[dict]:
    """Validate PDK files and step-specific PDK resources without mutating state."""
    if pdk is None:
        return [_issue("pdk", "", "The workspace has no loaded PDK.")]

    issues: list[dict] = []
    root = str(getattr(pdk, "root", "") or "")
    try:
        pdk.validate()
    except (OSError, ValueError) as exc:
        issues.append(_issue("pdk", root, str(exc)))

    selected = set(step_names)
    mapping_steps = sorted(selected & _PDK_MAPPING_STEPS)
    if mapping_steps:
        mapping_file = getattr(pdk, "mapping_file", None)
        if not mapping_file:
            issues.append(
                _issue(
                    "pdk-layermap",
                    f"selected steps: {', '.join(mapping_steps)}",
                    "Set pdk.overrides.mapping_file to the PDK GDS layer map "
                    "(for example techfile/icsprout55.layermap).",
                )
            )
        elif not Path(mapping_file).is_file():
            issues.append(
                _issue(
                    "pdk-layermap",
                    str(mapping_file),
                    "Restore pdk.mapping_file or reinstall the PDK with its layer map.",
                )
            )

    sdc_steps = sorted(selected & _PDK_SDC_STEPS) if check_sdc else []
    if sdc_steps:
        sdc_path = getattr(pdk, "sdc", None)
        if not sdc_path:
            issues.append(
                _issue(
                    "pdk-sdc",
                    f"selected steps: {', '.join(sdc_steps)}",
                    "Provide design.sdc or regenerate the workspace constraints before running.",
                )
            )
        elif not Path(sdc_path).is_file():
            issues.append(
                _issue(
                    "pdk-sdc",
                    str(sdc_path),
                    "Restore the workspace SDC file before running timing or signoff steps.",
                )
            )
    return issues


def tool_issues(selected_steps) -> list[dict]:
    """Probe only the host tools required by the selected workspace steps."""
    probes = [(step.name, step.tool, "Unstart") for step in selected_steps if step.tool]
    if not probes:
        return []

    from chipcompiler.cli.inspection import env_probe

    results = env_probe.probe_environment(env_probe.probe_components_for_steps(probes))
    return [
        asdict(result) for result in results if result.status == env_probe.FAIL and result.required
    ]


def config_issues(workspace, selected_steps) -> list[dict]:
    """Validate workspace config files and external paths they reference."""
    from chipcompiler.data.workspace import step_config_paths
    from chipcompiler.utility import json_read

    workspace_dir = getattr(workspace, "directory", None)
    config = getattr(workspace, "config", None)
    if workspace_dir is None or not isinstance(config, dict):
        return []

    issues: list[dict] = []
    for step in selected_steps:
        for path in step_config_paths(workspace_dir, step.name, step.tool):
            # macro_location.tcl is a handoff written by macro placement and
            # refreshed for postFloorplan; it is checked only when that step
            # actually consumes it.
            if path.name == "macro_location.tcl" and step.name != "postFloorplan":
                continue
            if not path.is_file():
                issues.append(
                    _issue(
                        "config",
                        str(path),
                        "Restore the workspace configuration file or recreate the workspace.",
                    )
                )

    if any(step.name == "emir" for step in selected_steps):
        emir_path = config.get("emir")
        emir = json_read(emir_path) if emir_path else {}
        technology_file = emir.get("technology_file_path") if isinstance(emir, dict) else ""
        if not technology_file:
            issues.append(
                _issue(
                    "config-emir",
                    str(emir_path or "emir_ecc.json"),
                    "Set technology_file_path in config/emir_ecc.json.",
                )
            )
        elif not Path(technology_file).is_file():
            issues.append(
                _issue(
                    "config-emir",
                    str(technology_file),
                    "Restore the EMIR technology file or update config/emir_ecc.json.",
                )
            )
    return issues


def preflight_failure(preflight: dict) -> dict | None:
    """Return the blocking failure for a preflight result, if any."""
    missing = preflight.get("missing_inputs", [])
    if missing:
        return {
            "error": "step_input_missing",
            "reason": str(missing),
            "missing_inputs": missing,
        }
    issues = preflight.get("issues", [])
    if not issues:
        return None
    reason = "; ".join(
        f"{issue['component']}: {issue.get('remediation') or issue.get('detail')}"
        for issue in issues
    )
    return {"error": "env_not_ready", "reason": reason}


def build_run_preflight(flow, selected: list[str], *, only: str | None, force: bool) -> dict:
    """Describe the selected steps without changing workspace state."""
    steps_by_name = {step.name: step for step in getattr(flow, "workspace_steps", ())}
    step_facts = []
    missing = []
    for name in selected:
        step = steps_by_name.get(name)
        inputs = {}
        if step is not None:
            for field in fields(step.input):
                value = getattr(step.input, field.name)
                if value is None:
                    continue
                path = Path(value)
                input_name = "def" if field.name == "def_" else field.name
                inputs[input_name] = {"path": str(path), "exists": path.exists()}
                if not path.exists():
                    missing.append({"step": name, "input": input_name, "path": str(path)})
        step_facts.append(
            {
                "step": name,
                "tool": getattr(step, "tool", None),
                "inputs": inputs,
            }
        )

    selected_steps = [steps_by_name[name] for name in selected if name in steps_by_name]
    workspace = getattr(flow, "workspace", None)
    tool_problems = tool_issues(selected_steps)
    pdk_problems = (
        pdk_issues(getattr(workspace, "pdk", None), selected) if workspace is not None else []
    )
    config_problems = config_issues(workspace, selected_steps) if workspace is not None else []
    issues = [*tool_problems, *pdk_problems, *config_problems]
    return {
        "selector": {"only": only, "force": force},
        "selected_steps": step_facts,
        "missing_inputs": missing,
        "tool_issues": tool_problems,
        "pdk_issues": pdk_problems,
        "config_issues": config_problems,
        "issues": issues,
        "ready": not missing and not issues,
    }


def output_paths(flow, executed: list[str]) -> dict[str, list[str]]:
    """Return existing and declared output paths for executed steps."""
    steps_by_name = {step.name: step for step in getattr(flow, "workspace_steps", ())}
    result = {}
    for name in executed:
        step = steps_by_name.get(name)
        paths = []
        if step is not None:
            for field in fields(step.output):
                value = getattr(step.output, field.name)
                values = value if isinstance(value, list) else [value]
                for path in values:
                    if path:
                        paths.append(str(path))
        result[name] = paths
    return result
