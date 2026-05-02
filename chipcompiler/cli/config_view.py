import os

from chipcompiler.cli.output import disclosure_cmd


def build_project_config_items(project_dir: str, run_dir: str,
                               project: str | None = None,
                               run_id: str | None = None) -> tuple[list[dict], int]:
    from chipcompiler.cli.config import (
        find_config_path,
        load_project_config,
        resolve_pdk_root,
        validate_project_config,
    )
    from chipcompiler.cli.output import format_line

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
    display_run = run_id or "default"

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
        items.append({
            "kind": "config",
            "scope": "project",
            "key": key,
            "value": value,
            "resolved": resolved,
            "source": source,
            "inspect_cmd": inspect,
        })

    # RTL entries
    for i, rtl in enumerate(cfg.design_rtl):
        rtl_resolved = os.path.normpath(os.path.join(project_dir, rtl))
        items.append({
            "kind": "config",
            "scope": "project",
            "key": f"design.rtl.{i}",
            "value": rtl,
            "resolved": rtl_resolved,
            "source": "ecc.toml",
            "inspect_cmd": inspect,
        })

    # PDK root with resolution
    pdk_source = "ecc.toml" if cfg.pdk_root else "env"
    items.append({
        "kind": "config",
        "scope": "project",
        "key": "pdk.root",
        "value": cfg.pdk_root or "",
        "resolved": pdk_root,
        "source": pdk_source,
        "inspect_cmd": inspect,
    })

    # Run directory
    try:
        run_dir_rel = os.path.relpath(run_dir, project_dir)
    except ValueError:
        run_dir_rel = run_dir
    if run_dir_rel.startswith(".."):
        run_dir_value = run_dir
    else:
        run_dir_value = run_dir_rel
    items.append({
        "kind": "config",
        "scope": "project",
        "key": "run_dir",
        "value": run_dir_value,
        "resolved": os.path.abspath(run_dir),
        "source": "resolved",
        "inspect_cmd": disclosure_cmd("ecc status", project, run_id),
    })

    return items, 0


def build_step_config_items(run_dir: str, step_token: str | None,
                            project: str | None = None,
                            run_id: str | None = None,
                            project_dir: str | None = None) -> tuple[list[dict], int]:
    from chipcompiler.cli.inspect import discover_step_dirs

    base_dir = project_dir or os.path.dirname(os.path.dirname(run_dir))
    step_dirs = discover_step_dirs(run_dir)

    if step_token not in step_dirs:
        return [{"kind": "error", "status": "unknown_step", "step": step_token}], 1

    config_dir = os.path.join(step_dirs[step_token], "config")
    items = []
    display_run = run_id or "default"

    if os.path.isdir(config_dir):
        for fname in sorted(os.listdir(config_dir)):
            fpath = os.path.join(config_dir, fname)
            if os.path.isfile(fpath):
                items.append({
                    "kind": "config",
                    "scope": "step",
                    "step": step_token,
                    "role": "config",
                    "run": display_run,
                    "path": os.path.relpath(fpath, base_dir),
                    "source": "step_config",
                    "inspect_cmd": disclosure_cmd(f"ecc artifacts {step_token} --json", project, run_id),
                })

    if not items:
        return [{"kind": "config", "scope": "step", "step": step_token,
                 "config_status": "none",
                 "artifacts": disclosure_cmd(f"ecc artifacts {step_token}", project, run_id)}], 0

    return items, 0


def build_config_lines(items: list[dict], project: str | None = None,
                       run_id: str | None = None) -> tuple[list[str], int]:
    from chipcompiler.cli.output import format_line

    if not items:
        return [], 0

    if items[0].get("config_status") == "none":
        s = items[0]
        return [format_line(
            step=s["step"],
            config_status="none",
            artifacts=s.get("artifacts"),
        )], 0

    if items[0].get("status") in ("unknown_step", "missing_config", "invalid_config"):
        if items[0].get("status") == "unknown_step":
            return [format_line(
                step=items[0].get("step", ""),
                status="unknown_step",
                inspect=disclosure_cmd("ecc status", project, run_id),
            )], 1
        if items[0].get("status") == "missing_config":
            return [format_line(
                status="missing_config",
                inspect=disclosure_cmd("ecc check", project),
            )], 1
        return [format_line(
            status="invalid_config",
            inspect=disclosure_cmd("ecc check", project),
        )], 1

    lines = []
    for item in items:
        if item.get("scope") == "project":
            line = format_line(
                config=item["key"],
                scope="project",
                value=item["value"],
                resolved=item.get("resolved"),
                source=item["source"],
                inspect=disclosure_cmd("ecc config --resolved --json", project, run_id),
            )
        else:
            line = format_line(
                config=os.path.basename(item["path"]),
                scope="step",
                step=item["step"],
                role=item["role"],
                run=item.get("run", "default"),
                path=item["path"],
                source=item["source"],
                inspect=item.get("inspect_cmd"),
            )
        lines.append(line)
    return lines, 0


def build_config_json(items: list[dict]) -> tuple[dict, int]:
    if items and items[0].get("status") in ("unknown_step", "missing_config", "invalid_config"):
        return items[0], 1

    if items and items[0].get("config_status") == "none":
        return items[0], 0

    if not items:
        return {"config_status": "none"}, 0

    return {"config": items}, 0


def build_config_jsonl(items: list[dict]) -> tuple[list[dict], int]:
    if items and items[0].get("status") in ("unknown_step", "missing_config", "invalid_config"):
        return items, 1

    if items and items[0].get("config_status") == "none":
        return items, 0

    if not items:
        return [{"config_status": "none"}], 0

    return items, 0
