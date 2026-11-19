import os
from typing import TYPE_CHECKING

from chipcompiler.cli.core.output import disclosure_cmd

if TYPE_CHECKING:
    from chipcompiler.cli.project.config import ProjectConfig
    from chipcompiler.data.parameter_schema import ResolvedParam


def build_project_config_items(
    project_dir: str,
    run_dir: str,
    project: str | None = None,
    run_id: str | None = None,
    *,
    resolved: tuple | None = None,
) -> tuple[list[dict], int]:
    from chipcompiler.cli.project.config import (
        _resolve_path,
        find_config_path,
        load_project_config,
        resolve_max_parallel_steps,
        resolve_pdk_root,
        validate_project_config,
    )

    flow_config = None
    if resolved is not None:
        # The effective (manifest-layered) config, resolved by the handler.
        cfg, flow_config = resolved
    else:
        config_path = find_config_path(project_dir)
        if config_path is None:
            return [{"kind": "error", "status": "missing_config"}], 1

        try:
            cfg = load_project_config(config_path)
        except (OSError, UnicodeDecodeError):
            return [{"kind": "error", "status": "invalid_config"}], 1
        if getattr(cfg, "_toml_error", None):
            return [{"kind": "error", "status": "invalid_config"}], 1

        errors = validate_project_config(cfg)
        if errors:
            return [{"kind": "error", "status": "invalid_config"}], 1

    pdk_root = resolve_pdk_root(cfg)

    # Source labels follow the effective layering: values the manifest
    # supplied (or filled beneath an ecc.toml that does not set them) read
    # "project.json"; explicit ecc.toml keys read "ecc.toml".
    explicit = getattr(cfg, "_explicit_keys", frozenset())

    def source_of(dotted: str) -> str:
        if resolved is not None and dotted not in explicit:
            return "project.json"
        return "ecc.toml"

    items = []
    entries = [
        ("design.name", cfg.design_name, cfg.design_name, source_of("design.name")),
        ("design.top", cfg.design_top, cfg.design_top, source_of("design.top")),
        (
            "design.clock_port",
            cfg.design_clock_port,
            cfg.design_clock_port,
            source_of("design.clock_port"),
        ),
        (
            "design.frequency_mhz",
            cfg.design_frequency_mhz,
            cfg.design_frequency_mhz,
            source_of("design.frequency_mhz"),
        ),
        ("pdk.name", cfg.pdk_name, cfg.pdk_name, source_of("pdk.name")),
    ]
    if flow_config is not None and "flow.preset" not in explicit:
        # The selected manifest entry's range is the flow target.
        entries.append(
            ("flow.start", flow_config["start_step"], flow_config["start_step"], "project.json")
        )
        entries.append(
            ("flow.end", flow_config["end_step"], flow_config["end_step"], "project.json")
        )
    else:
        entries.append(("flow.preset", cfg.flow_preset, cfg.flow_preset, source_of("flow.preset")))

    # Effective skip policy: the declared spelling with its winning layer,
    # or the code default when no surface declares the key.
    declared = None
    source = "project.json"
    winner = getattr(cfg, "_skip_steps_source", None)
    if resolved is not None and isinstance(flow_config, dict) and "skip_steps" in flow_config:
        declared = list(flow_config["skip_steps"])
        # The winner was resolved by effective-config: an explicit ecc.toml
        # key beats the manifest entry, like every other key; fall back to
        # layer presence for older call paths that did not record it.
        source = winner or ("ecc.toml" if "flow.skip_steps" in explicit else "project.json")
    elif "flow.skip_steps" in explicit:
        declared = list(cfg.flow_skip_steps or [])
    if declared is None:
        from chipcompiler.data import DEFAULT_SKIP_STEPS

        entries.append(("flow.skip_steps", None, list(DEFAULT_SKIP_STEPS), "default"))
    else:
        entries.append(("flow.skip_steps", declared, declared, source))

    # Effective no-clock: boolean and provenance come from the same resolver,
    # so an inferred empty-clock policy cannot report ``false``/``inferred``.
    from chipcompiler.rtl2gds import resolve_no_clock

    if isinstance(flow_config, dict):
        no_clock_decision = resolve_no_clock(
            flow_config,
            materials={"clock_port": getattr(cfg, "design_clock_port", "")},
        )
    else:
        # Standalone ecc.toml projects carry the declared flag on cfg, not on
        # an effective flow dictionary; surface it so inspection agrees with
        # validation/execution.
        from chipcompiler.cli.project.config import ProjectNoClockDecisionResolver

        no_clock_decision = ProjectNoClockDecisionResolver(cfg).resolve()

    no_clock_enabled = no_clock_decision.enabled
    no_clock_source = no_clock_decision.source
    no_clock_key_source = (
        source_of("flow.no_clock")
        if "flow.no_clock" in explicit
        else ("inferred" if no_clock_source == "inferred" else "default")
    )
    entries.append(("flow.no_clock", no_clock_enabled, no_clock_enabled, no_clock_key_source))
    entries.append(("flow.no_clock_source", no_clock_source, no_clock_source, no_clock_key_source))

    inspect = disclosure_cmd("ecc config", project, run_id)

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
                "source": source_of("design.rtl"),
                "inspect_cmd": inspect,
            }
        )

    # PDK root with resolution
    pdk_source = source_of("pdk.root") if cfg.pdk_root else "env"
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

    # PDK overrides
    if cfg.pdk_overrides:
        items.append(
            {
                "kind": "config",
                "scope": "project",
                "key": "pdk.overrides",
                "value": cfg.pdk_overrides,
                "resolved": cfg.pdk_overrides,
                "source": "ecc.toml",
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
    from chipcompiler.params import resolve_parameters

    pdk = cfg.pdk_name or None
    cli_provenance, prov_error = _load_cli_provenance(run_dir, pdk)
    if prov_error:
        return [{"kind": "error", "status": "invalid_config", "reason": prov_error}], 1
    toml_overrides = dict(cfg.params_overrides)
    if "design.frequency_mhz" not in toml_overrides and "design.frequency_mhz" in getattr(
        cfg, "_explicit_keys", frozenset()
    ):
        # Only an explicit ecc.toml [design] frequency is an ecc.toml-layer
        # value; a manifest-filled design_frequency_mhz (manifest-only and
        # filled hybrid configs) must present through the manifest overrides
        # beneath, or it masks the manifest layer's own type errors.
        toml_overrides["design.frequency_mhz"] = cfg.design_frequency_mhz
    resolved_params, resolve_errors = resolve_parameters(
        toml_overrides=toml_overrides,
        cli_overrides=cli_provenance,
        manifest_overrides=_manifest_parameter_overrides(cfg),
        pdk=pdk,
    )
    from chipcompiler.cli.command_handlers.param_step_values import maps_to_str, record_at_step
    from chipcompiler.data.step_parameters import is_step_scoped, step_key

    by_key = {rp.key: rp for rp in resolved_params}
    flow_steps = _flow_step_names(cfg, flow_config)
    shown_params: list[tuple[str, ResolvedParam]] = []
    for rp in resolved_params:
        if rp.step is not None:
            continue  # step values are shown through their parameter's step rows
        if not is_step_scoped(rp.schema):
            shown_params.append((rp.key, rp))
            continue
        # A step-scoped parameter has no project-wide value: show it at each
        # declared step in the flow (and at any step a layer sets explicitly),
        # keyed <step>:<param> so its inspect command resolves.
        for step in rp.schema.steps:
            shown = record_at_step(by_key, rp, step)
            if not flow_steps or step in flow_steps or shown.is_explicit:
                shown_params.append((step_key(step, rp.param), shown))

    for key, rp in shown_params:
        if rp.schema.has_direct_target and not rp.is_explicit:
            continue
        items.append(
            {
                "kind": "param",
                "scope": "project",
                "key": key,
                "value": rp.value,
                "default": rp.default,
                "source": rp.source,
                "maps_to": maps_to_str(rp.schema.maps_to),
                "inspect_cmd": disclosure_cmd(f"ecc param show {key}", project),
            }
        )

    # Parameter resolution errors (including ecc.toml [params] parse errors)
    # must not be swallowed: a view that silently shows defaults hides that
    # the effective values are not what is displayed. They lead the item list
    # so the handler's error dispatch sees them first.
    error_records = [
        {"kind": "error", "status": "invalid_config", "reason": err}
        for err in [*resolve_errors, *getattr(cfg, "_param_errors", [])]
    ]
    if error_records:
        return [*error_records, *items], 1

    return items, 0


def _flow_step_names(cfg: "ProjectConfig", flow_config: dict | None) -> set[str]:
    """Names of the steps of the project's flow; empty when it cannot be built."""
    from chipcompiler.rtl2gds import build_flow_range, get_flow_builders

    if isinstance(flow_config, dict) and "start_step" in flow_config:
        try:
            steps = build_flow_range(flow_config["start_step"], flow_config["end_step"])
        except (KeyError, ValueError):
            return set()
    else:
        builder = get_flow_builders().get(cfg.flow_preset)
        steps = builder() if builder is not None else []
    return {str(step) for step, _tool, _state in steps}


def _load_cli_provenance(run_dir: str, pdk: str | None) -> tuple[dict[str, object], str | None]:
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
    from chipcompiler.params import parse_cli_overrides

    items = [f"{k}={v}" for k, v in data.items()]
    validated, errors = parse_cli_overrides(items, pdk)
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
    from chipcompiler.cli.inspection.discovery import (
        _safe_steps,
        discover_step_dirs,
        read_flow_json,
    )
    from chipcompiler.data import step_config_paths
    from chipcompiler.data.step import STEP_TOOLS

    base_dir = project_dir or os.path.dirname(os.path.dirname(run_dir))
    requested_step_token = step_token or ""
    step_token = str(requested_step_token)
    flow_data = read_flow_json(run_dir)
    if flow_data is None:
        return [{"kind": "error", "status": "unknown_step", "step": requested_step_token}], 1
    if not isinstance(flow_data, dict):
        return [{"kind": "error", "status": "invalid_flow_json"}], 1

    step_dirs = discover_step_dirs(run_dir)
    steps = _safe_steps(flow_data)
    flow_step_by_token = {s.get("name", ""): s for s in steps}

    if step_token not in flow_step_by_token and step_token not in step_dirs:
        return [{"kind": "error", "status": "unknown_step", "step": requested_step_token}], 1

    step_info = flow_step_by_token.get(step_token, {})
    data_step = step_info.get("name")
    tool = step_info.get("tool")
    step_dir = step_dirs.get(step_token)
    if data_step is None and step_dir is not None:
        # A step the ledger does not record runs its canonical tool.
        data_step = step_token
        tool = STEP_TOOLS.get(step_token)

    items = []
    display_run = run_id or "default"

    config_paths: list[tuple[str, str]] = []
    if data_step is not None:
        config_paths = [
            ("workspace_config", str(path))
            for path in step_config_paths(run_dir, data_step, tool, existing_only=True)
        ]
    # A step that resolves its own config (DreamPlace) keeps it in <step dir>/config.
    step_config_dir = os.path.join(step_dir, "config") if step_dir is not None else ""
    if step_config_dir and os.path.isdir(step_config_dir):
        config_paths.extend(
            ("step_config", os.path.join(step_config_dir, name))
            for name in sorted(os.listdir(step_config_dir))
            if name.endswith(".json")
        )

    for source, fpath in config_paths:
        items.append(
            {
                "kind": "config",
                "scope": "step",
                "step": requested_step_token,
                "role": "config",
                "workspace_id": display_run,
                "path": os.path.relpath(fpath, base_dir),
                "source": source,
                "inspect_cmd": disclosure_cmd(
                    f"ecc config {requested_step_token}", project, run_id
                ),
            }
        )

    if not items:
        return [
            {
                "kind": "config",
                "scope": "step",
                "step": requested_step_token,
                "config_status": "none",
            }
        ], 0

    return items, 0


def _manifest_parameter_overrides(cfg: "ProjectConfig") -> dict[str, float]:
    """The manifest layer's one registry value: the declared clock frequency.

    The manifest carries design identity only, but its ``frequency_mhz``
    fills the config when ecc.toml declares none; the resolved view must
    present it as the ``project.json`` layer instead of a registry default.
    """
    if (
        "design.frequency_mhz" in getattr(cfg, "_explicit_keys", frozenset())
        or "design.frequency_mhz" in cfg.params_overrides
        or not cfg.design_frequency_mhz
    ):
        return {}
    return {"design.frequency_mhz": cfg.design_frequency_mhz}
