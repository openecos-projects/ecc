"""Resolve and validate project run targets for execution, creation, and preview."""

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from chipcompiler.cli.core.inputs import RunInput
from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project.config import ProjectConfig
from chipcompiler.project.manifest import CONFIG_FILENAME

if TYPE_CHECKING:
    from chipcompiler.cli.project.flow_selection import FlowConfig


@dataclass(frozen=True)
class RunSetup:
    cfg: ProjectConfig
    flow_config: "FlowConfig | None"
    effective_preset: str
    cli_overrides: dict[str, object]
    run_dir: str
    run_name: str
    workspace_registered: bool
    warning_records: list[dict]
    fresh_target: bool


def resolve_run_setup(
    command_input: RunInput, ctx: CommandContext, *, execute_flow: bool
) -> RunSetup | CommandResult:
    def error(kind: str, **fields) -> CommandResult:
        return CommandResult.err([{"kind": "error", "error": kind, **fields}])

    if ctx.project_state == "legacy":
        from chipcompiler.cli.core.records import legacy_workspace_error_record

        return CommandResult.err([legacy_workspace_error_record()])
    if ctx.manifest_error:
        return error(ctx.manifest_error.split(":", 1)[0], reason=ctx.manifest_error)

    range_requested = command_input.from_step is not None or command_input.to_step is not None
    if command_input.to_step is not None and command_input.from_step is None:
        return error("flow_range_requires_pair")
    if (
        range_requested
        and command_input.from_step is not None
        and command_input.to_step is not None
    ):
        if any(
            (
                command_input.resume,
                command_input.only is not None,
                command_input.force,
                command_input.preset,
                command_input.overwrite,
            )
        ):
            return error("selector_conflict")
    elif (
        sum(
            (
                command_input.resume,
                command_input.from_step is not None,
                command_input.only is not None,
            )
        )
        > 1
    ):
        return error("selector_conflict")
    if command_input.force and command_input.only is None:
        return error("force_requires_only")

    from chipcompiler import rtl2gds as rtl2gds_api
    from chipcompiler.cli.project import effective_config, run_prepare

    project = ctx.project
    project_dir = ctx.project_dir

    cfg = ctx.config
    flow_config = None
    layer_warnings: list[dict] = []
    if cfg is None and ctx.project_state != "manifest":
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "missing_config",
                    "path": os.path.join(project_dir, CONFIG_FILENAME),
                }
            ]
        )

    if ctx.project_state == "manifest":
        resolved_cfg = effective_config.resolve_effective_config(ctx, ctx.run_id, cfg)
        if isinstance(resolved_cfg, CommandResult):
            return resolved_cfg
        cfg, flow_config, entry_warnings = resolved_cfg
        layer_warnings.extend(entry_warnings)
    else:
        if cfg is None:
            return CommandResult.err([error_record("missing_config")])
        from chipcompiler.cli.project.effective_config import (
            _attach_lec_engine,
            _attach_skip_steps,
        )
        from chipcompiler.cli.project.manifest_flow import (
            attach_insert_steps,
            declared_insert_steps,
        )

        skip_steps = (
            list(cfg.flow_skip_steps)
            if "flow.skip_steps" in cfg._explicit_keys and cfg.flow_skip_steps is not None
            else None
        )
        flow_config = _attach_skip_steps(flow_config, skip_steps)
        lec_engine = (
            cfg.flow_lec_engine
            if "flow.lec_engine" in cfg._explicit_keys and cfg.flow_lec_engine is not None
            else None
        )
        flow_config = _attach_lec_engine(flow_config, lec_engine)
        flow_config = attach_insert_steps(flow_config, declared_insert_steps(cfg))

    if cfg is None:
        return CommandResult.err([error_record("missing_config")])

    flow_builders = rtl2gds_api.get_flow_builders()
    effective_preset = command_input.preset or cfg.flow_preset
    if command_input.preset is not None and effective_preset not in flow_builders:
        return CommandResult.err(
            [
                error_record(
                    "unsupported_preset",
                    preset=command_input.preset,
                    presets=", ".join(sorted(flow_builders)),
                    inspect=disclosure_cmd("ecc config", project),
                )
            ]
        )
    from chipcompiler.data.workspace.config import FLOW_POLICY_KEYS

    policies = (
        {key: flow_config[key] for key in FLOW_POLICY_KEYS if key in flow_config}
        if isinstance(flow_config, dict)
        else {}
    )
    if command_input.preset is not None:
        cfg.flow_preset = effective_preset
        cfg.manifest_driven = False
        flow_config = dict(policies) or None

    if command_input.from_step is not None and command_input.to_step is not None:
        try:
            from chipcompiler.rtl2gds import build_flow_range, resolve_skip_steps

            build_flow_range(
                command_input.from_step,
                command_input.to_step,
                skip=resolve_skip_steps(policies or None),
            )
        except ValueError as exc:
            return error("flow_range_invalid", reason=str(exc))
        flow_config = {
            "start_step": command_input.from_step,
            "end_step": command_input.to_step,
            **policies,
        }

    cli_overrides: dict[str, object] = {}
    raw_sets = command_input.param_set
    if raw_sets:
        from chipcompiler.params import parse_cli_overrides

        cli_overrides, set_errors = parse_cli_overrides(
            list(raw_sets), (cfg.pdk_name if cfg is not None else "") or None
        )
        if set_errors:
            return CommandResult.err(
                [
                    {
                        "kind": "error",
                        "error": "invalid_parameter",
                        "reason": err,
                    }
                    for err in set_errors
                ]
            )
        set_warning = (
            effective_config.cli_divergence_warning(cfg, cli_overrides)
            if ctx.project_state == "manifest"
            else None
        )
        if set_warning is not None:
            layer_warnings.append(set_warning)

    warning_records: list[dict] = []
    run_dir = ctx.run_dir
    run_name = ctx.run_id or "default"
    workspace_registered = False

    if ctx.project_state in ("virgin", "manifest"):
        resolved = run_prepare.resolve_manifest_run_target(command_input, ctx)
        if isinstance(resolved, CommandResult):
            return resolved
        run_dir, run_name, workspace_registered, warning_records = resolved
    warning_records = layer_warnings + warning_records

    flow_json = os.path.join(run_dir, "home", "flow.json")
    fresh_target = not os.path.exists(flow_json) or command_input.overwrite
    if (
        (fresh_target or not execute_flow)
        and command_input.from_step is not None
        and command_input.to_step is None
    ):
        return error("flow_range_requires_pair")
    if fresh_target and (command_input.resume or command_input.only is not None):
        return error("selector_requires_workspace")

    return RunSetup(
        cfg=cfg,
        flow_config=flow_config,
        effective_preset=effective_preset,
        cli_overrides=cli_overrides,
        run_dir=run_dir,
        run_name=run_name,
        workspace_registered=workspace_registered,
        warning_records=warning_records,
        fresh_target=fresh_target,
    )


def validate_run_setup(
    setup: RunSetup, ctx: CommandContext, *, check_pdk_files: bool = True
) -> CommandResult | None:
    from chipcompiler.cli.project import effective_config

    errors = effective_config.validate_effective(
        ctx,
        setup.cfg,
        fresh=setup.fresh_target,
        flow_config=setup.flow_config,
        cli_overrides=setup.cli_overrides,
        check_pdk_files=check_pdk_files,
        validate_timing_input=setup.fresh_target,
    )
    if errors:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": config_error_code(err),
                    "reason": err,
                }
                for err in errors
            ]
        )

    protected = (ctx.project_dir, os.path.join(ctx.project_dir, "runs"))
    spelled = {os.path.normpath(p) for p in protected}
    canonical = {os.path.realpath(p) for p in protected}
    if os.path.normpath(setup.run_dir) in spelled or os.path.realpath(setup.run_dir) in canonical:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "invalid_workspace",
                    "workspace_id": setup.run_name,
                    "workspace": setup.run_dir,
                    "reason": (
                        "workspace name must not resolve to the project or legacy runs container"
                    ),
                }
            ]
        )
    return None


def preflight_fresh_setup(
    setup: RunSetup, project: str | None
) -> tuple[CommandResult | None, list[dict]]:
    from chipcompiler.cli.project.effective_config import flow_config_selects_steps
    from chipcompiler.cli.project.flow_selection import selection_warnings

    if flow_config_selects_steps(setup.flow_config):
        preflight = _preflight_flow_range(setup.flow_config, project, setup.cfg)
    elif setup.effective_preset:
        preflight = _preflight_environment(
            setup.effective_preset, project, setup.flow_config, setup.cfg
        )
    else:
        preflight = None
    if preflight is not None:
        return preflight, setup.warning_records
    return None, [*setup.warning_records, *selection_warnings(setup.cfg, setup.flow_config)]


def _preflight_environment(
    preset: str | None,
    project: str | None,
    flow_config: "FlowConfig | None" = None,
    cfg=None,
) -> CommandResult | None:
    """Fail fast when the tools a fresh flow target needs are missing.

    The probe set comes from the preset's builder output filtered by the
    effective skip policy, so a skipped step's tool is never probed.

    None means ready.
    """
    from chipcompiler.cli.inspection import env_probe
    from chipcompiler.cli.project import run_preflight
    from chipcompiler.rtl2gds import resolve_insert_steps, resolve_lec_engine, resolve_skip_steps

    if preset is None:
        return None
    skip = resolve_skip_steps(flow_config)
    lec_engine = resolve_lec_engine(flow_config)
    insert = resolve_insert_steps(flow_config)
    probes = env_probe.probe_environment(
        env_probe.probe_components_for_preset(
            preset, skip=skip, lec_engine=lec_engine, insert=insert
        )
    )
    from chipcompiler import rtl2gds as rtl2gds_api

    builder = rtl2gds_api.get_flow_builders().get(preset)
    steps = [] if builder is None else builder()
    steps = rtl2gds_api.insert_flow_steps(
        rtl2gds_api.filter_flow_steps(rtl2gds_api.substitute_lec_engine(steps, lec_engine), skip),
        insert,
        lec_engine,
    )
    step_names = [getattr(step, "value", str(step)) for step, _tool, _state in steps]
    resource_issues = run_preflight.pdk_issues_for_config(cfg, step_names)
    return _preflight_failures(probes, project, preset, resource_issues)


def _preflight_flow_range(flow_config: dict, project: str | None, cfg=None) -> CommandResult | None:
    """Fail fast when the tools a fresh flow range needs are missing.

    The selected range already names its tools, so a missing tool is a
    preflight failure before any manifest registration or workspace
    creation — not a discovery made mid-creation. The range is sliced
    from the policy-filtered chain, matching ledger creation.
    """
    from chipcompiler.cli.inspection import env_probe
    from chipcompiler.cli.project import run_preflight
    from chipcompiler.rtl2gds import (
        build_flow_range,
        resolve_insert_steps,
        resolve_lec_engine,
        resolve_skip_steps,
    )

    try:
        steps = build_flow_range(
            flow_config["start_step"],
            flow_config["end_step"],
            skip=resolve_skip_steps(flow_config),
            lec_engine=resolve_lec_engine(flow_config),
            insert=resolve_insert_steps(flow_config),
        )
    except ValueError:
        # Range spellings are validated where they are declared (CLI ranges
        # during argument handling, manifest ranges at load time); an
        # unresolvable range here degrades to no preflight, never a new
        # failure mode in front of the run.
        return None
    probes = env_probe.probe_environment(env_probe.probe_components_for_steps(steps))
    step_names = [getattr(step, "value", str(step)) for step, _tool, _state in steps]
    resource_issues = run_preflight.pdk_issues_for_config(cfg, step_names)
    return _preflight_failures(probes, project, None, resource_issues)


def _preflight_failures(
    probes, project: str | None, preset: str | None, extra_issues=()
) -> CommandResult | None:
    """Map failed probes to env_not_ready; None means ready."""
    from chipcompiler.cli.inspection import env_probe

    failures = [p for p in probes if p.status == env_probe.FAIL]
    failures.extend(extra_issues)
    if not failures:
        return None

    def field(item, name, default: object = ""):
        return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)

    records = [
        error_record(
            "env_not_ready",
            reason="; ".join(
                f"{field(item, 'component')}: {field(item, 'remediation') or field(item, 'detail')}"
                for item in failures
            ),
            preset=preset,
            doctor=disclosure_cmd("ecc doctor", project),
        )
    ]
    records.extend(
        {
            "component": field(item, "component"),
            "status": field(item, "status", "fail"),
            "required": field(item, "required", default=True),
            "detail": field(item, "detail"),
            "remediation": field(item, "remediation"),
        }
        for item in failures
    )
    return CommandResult.err(records)


def config_error_code(reason: str) -> str:
    for code in ("step_input_missing", "unsupported_flow_run"):
        if reason.startswith(f"{code}:"):
            return code
    return "config_error"
