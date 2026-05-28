import os

from chipcompiler.cli.core.output import disclosure_cmd


def build_project_config_items(
    project_dir: str, run_dir: str, project: str | None = None, run_id: str | None = None
) -> tuple[list[dict], int]:
    from chipcompiler.cli.project.config import (
        _resolve_path,
        find_config_path,
        load_project_config,
        resolve_pdk_root,
        validate_project_config,
    )

    config_path = find_config_path(project_dir)
    if config_path is None:
        return [{"kind": "error", "status": "missing_config"}], 1

    cfg = load_project_config(config_path)
    if getattr(cfg, "_toml_error", None):
        return [{"kind": "error", "status": "invalid_config"}], 1

    errors = validate_project_config(cfg)
    if errors:
        return [{"kind": "error", "status": "invalid_config"}], 1

    pdk_root = resolve_pdk_root(cfg)

    items = []
    entries = [
        ("design.name", cfg.design_name, cfg.design_name, "ecc.toml"),
        ("design.top", cfg.design_top, cfg.design_top, "ecc.toml"),
        ("design.clock_port", cfg.design_clock_port, cfg.design_clock_port, "ecc.toml"),
        ("design.frequency_mhz", cfg.design_frequency_mhz, cfg.design_frequency_mhz, "ecc.toml"),
        ("pdk.name", cfg.pdk_name, cfg.pdk_name, "ecc.toml"),
        ("flow.preset", cfg.flow_preset, cfg.flow_preset, "ecc.toml"),
        ("flow.run", cfg.flow_run, cfg.flow_run, "ecc.toml"),
    ]

    inspect = disclosure_cmd("ecc config --resolved --json", project, run_id)

    for key, value, resolved, source in entries:
        items.append(
            {
                "kind": "config",
                "scope": "project",
                "key": key,
                "value": value,
                "resolved": resolved,
                "source": source,
                "inspect_cmd": inspect,
            }
        )

    # RTL entries
    for i, rtl in enumerate(cfg.design_rtl):
        rtl_resolved = os.path.normpath(_resolve_path(project_dir, rtl))
        items.append(
            {
                "kind": "config",
                "scope": "project",
                "key": f"design.rtl.{i}",
                "value": rtl,
                "resolved": rtl_resolved,
                "source": "ecc.toml",
                "inspect_cmd": inspect,
            }
        )

    # PDK root with resolution
    pdk_source = "ecc.toml" if cfg.pdk_root else "env"
    items.append(
        {
            "kind": "config",
            "scope": "project",
            "key": "pdk.root",
            "value": cfg.pdk_root or "",
            "resolved": pdk_root,
            "source": pdk_source,
            "inspect_cmd": inspect,
        }
    )

    # Run directory
    try:
        run_dir_rel = os.path.relpath(run_dir, project_dir)
    except ValueError:
        run_dir_rel = run_dir
    run_dir_value = run_dir if run_dir_rel.startswith("..") else run_dir_rel
    items.append(
        {
            "kind": "config",
            "scope": "project",
            "key": "run_dir",
            "value": run_dir_value,
            "resolved": os.path.abspath(run_dir),
            "source": "resolved",
            "inspect_cmd": disclosure_cmd("ecc status", project, run_id),
        }
    )

    # Parameter records with source information
    from chipcompiler.cli.project.params import resolve_parameters

    cli_provenance, prov_error = _load_cli_provenance(run_dir)
    if prov_error:
        return [{"kind": "error", "status": "invalid_config", "reason": prov_error}], 1
    toml_overrides = dict(cfg.params_overrides)
    if "design.frequency_mhz" not in toml_overrides and cfg.design_frequency_mhz > 0:
        toml_overrides["design.frequency_mhz"] = cfg.design_frequency_mhz
    resolved_params, _ = resolve_parameters(
        toml_overrides=toml_overrides,
        cli_overrides=cli_provenance,
    )
    from chipcompiler.cli.handlers.param import _maps_to_str

    for rp in resolved_params:
        items.append(
            {
                "kind": "param",
                "scope": "project",
                "key": rp.param,
                "value": rp.value,
                "default": rp.default,
                "source": rp.source,
                "maps_to": _maps_to_str(rp.schema.maps_to),
                "inspect_cmd": disclosure_cmd(f"ecc param show {rp.param}", project),
            }
        )

    return items, 0


def _load_cli_provenance(run_dir: str) -> tuple[dict[str, object], str | None]:
    import json

    provenance_path = os.path.join(run_dir, "home", "cli-param-overrides.json")
    if not os.path.isfile(provenance_path):
        return {}, None
    try:
        with open(provenance_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return {}, f"invalid CLI parameter provenance: {exc}"
    if not isinstance(data, dict):
        return {}, "invalid CLI parameter provenance: expected object"
    from chipcompiler.cli.project.params import parse_cli_overrides

    items = [f"{k}={v}" for k, v in data.items()]
    validated, errors = parse_cli_overrides(items)
    if errors:
        return {}, f"invalid CLI parameter provenance: {errors[0]}"
    return validated, None


def build_step_config_items(
    run_dir: str,
    step_token: str | None,
    project: str | None = None,
    run_id: str | None = None,
    project_dir: str | None = None,
) -> tuple[list[dict], int]:
    from chipcompiler.cli.core.output import normalize_step_name
    from chipcompiler.cli.inspection.discovery import (
        CORRUPT_FLOW_JSON,
        _safe_steps,
        discover_step_dirs,
        read_flow_json,
        step_dir_tool,
    )
    from chipcompiler.cli.workspace.config_view import workspace_config_files

    base_dir = project_dir or os.path.dirname(os.path.dirname(run_dir))
    flow_data = read_flow_json(run_dir)
    if flow_data is None:
        return [{"kind": "error", "status": "unknown_step", "step": step_token}], 1
    if flow_data is CORRUPT_FLOW_JSON:
        return [{"kind": "error", "status": "invalid_flow_json"}], 1

    step_dirs = discover_step_dirs(run_dir)
    steps = _safe_steps(flow_data)
    flow_step_by_token = {normalize_step_name(s.get("name", "")): s for s in steps}

    if step_token not in flow_step_by_token and step_token not in step_dirs:
        return [{"kind": "error", "status": "unknown_step", "step": step_token}], 1

    step_info = flow_step_by_token.get(step_token, {})
    tool = step_info.get("tool")
    if tool is None and step_token in step_dirs:
        tool = step_dir_tool(step_dirs[step_token])

    items = []
    display_run = run_id or "default"

    for fpath in workspace_config_files(run_dir, step_token, tool):
        items.append(
            {
                "kind": "config",
                "scope": "step",
                "step": step_token,
                "role": "config",
                "run": display_run,
                "path": os.path.relpath(fpath, base_dir),
                "source": "workspace_config",
                "inspect_cmd": disclosure_cmd(
                    f"ecc config {step_token} --resolved --json", project, run_id
                ),
            }
        )

    if not items:
        return [
            {
                "kind": "config",
                "scope": "step",
                "step": step_token,
                "config_status": "none",
                "artifacts": disclosure_cmd(f"ecc artifacts {step_token}", project, run_id),
            }
        ], 0

    return items, 0
