#!/usr/bin/env python

"""Existing-workspace run path: reconcile the persisted ledger against the
flow target, then resume or extend under the workspace lock.

Split out of ``run_prepare`` (the 700-line guideline): the fresh-run and
existing-run lifecycles are separate responsibilities, and the reconcile
wiring belongs next to the ledger it owns.
"""

import sys
from pathlib import Path

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.run_prepare import _write_back_status
from chipcompiler.data import is_finished_step_state


def _manifest_skip_target(run_dir: str, flow_config) -> dict | None:
    """Manifest-mode target: the workspace's own [flow] range plus the
    effective declared skip policy.

    None when no policy is declared (the workspace's persisted policy
    keeps governing) or when the workspace config carries no range (the
    persisted-ledger fallback stays in charge).
    """
    declared = (
        flow_config.get("skip_steps")
        if isinstance(flow_config, dict) and "skip_steps" in flow_config
        else None
    )
    if declared is None:
        return None
    from chipcompiler.data.workspace_config import (
        WorkspaceConfigError,
        WorkspaceFlowTargetError,
        load_workspace_config,
    )

    try:
        workspace_flow = load_workspace_config(run_dir)["_flow"]
    except (FileNotFoundError, OSError, WorkspaceConfigError, WorkspaceFlowTargetError):
        return None
    if "start" not in workspace_flow or "end" not in workspace_flow:
        return None
    return {**workspace_flow, "skip_steps": declared}


def _diverging_workspace_param_fixes(
    workspace, run_name: str, overrides: dict, project
) -> list[tuple[str, str]]:
    """Copy-pasteable `ecc param set --workspace` commands for the ecc.toml
    [params] keys whose value differs from the workspace's current value.

    Returns (param, fix command) pairs. Best-effort: keys without a
    resolvable workspace target (or whose config cannot be read) are skipped
    — the generic warning still applies.
    """
    import json as _json

    from chipcompiler.cli.project.params import lookup_schema
    from chipcompiler.data.workspace_parameters import workspace_param_value

    fixes = []
    for key, value in sorted(overrides.items()):
        schema = lookup_schema(key)
        if schema is None:
            continue
        try:
            current = workspace_param_value(workspace, schema)
        except (ValueError, OSError):
            continue
        if current == value:
            continue
        rendered = _json.dumps(value) if isinstance(value, (list, dict, bool)) else str(value)
        fixes.append(
            (
                key,
                disclosure_cmd(f"ecc param set {key} {rendered} --workspace {run_name}", project),
            )
        )
    return fixes


def run_existing_workspace(
    command_input,
    ctx,
    cfg,
    run_dir: str,
    run_name: str,
    cli_overrides: dict,
    warning_records: list[dict],
    *,
    flow_config=None,
    workspace_registered: bool,
) -> CommandResult:
    """Run against an existing workspace: reconcile target vs persisted flow.

    Extends a proper-prefix target, resumes from the first non-Success step,
    no-ops when everything already succeeded, and fails divergent flows with
    flow_mismatch before any mutation.
    """
    from chipcompiler.cli.core.records import error_record, warning_record

    project = ctx.project
    project_dir = ctx.project_dir

    if cli_overrides:
        return CommandResult.err(
            [
                error_record(
                    "set_requires_fresh_run",
                    workspace_id=run_name,
                    workspace=run_dir,
                    reason=(
                        "--set applies only to fresh workspaces; use --overwrite "
                        "or a new --workspace"
                    ),
                )
            ]
        )

    warnings = list(warning_records)
    if cfg.params_overrides:
        warnings.append(
            warning_record(
                "params_ignored_on_existing_run",
                reason="[params] in ecc.toml apply only to fresh runs; "
                "the workspace reuses its persisted home/params.toml",
            )
        )
    from chipcompiler.cli.project.pdk_root_fallback import pdk_root_env_fallback_warning
    from chipcompiler.cli.project.spec_drift import workspace_spec_drift_warning

    pdk_root_warning = pdk_root_env_fallback_warning(run_dir)
    if pdk_root_warning is not None:
        warnings.append(pdk_root_warning)
    spec_drift = workspace_spec_drift_warning(run_dir)
    if spec_drift is not None:
        warnings.append(spec_drift)

    from chipcompiler.data import load_workspace
    from chipcompiler.data.schema_migrations import UnsupportedSchemaVersionError
    from chipcompiler.data.workspace_config import (
        WorkspaceConfigError,
        WorkspaceFlowTargetError,
    )
    from chipcompiler.engine.reconcile import classify_workspace

    def mismatch_error(reason: str) -> CommandResult:
        if reason.startswith("unsupported_schema_version"):
            return CommandResult.err(
                [
                    error_record(
                        "unsupported_schema_version",
                        workspace_id=run_name,
                        workspace=run_dir,
                        reason=reason,
                    )
                ]
            )
        if reason.startswith("workspace_config_invalid"):
            return CommandResult.err(
                [
                    error_record(
                        "workspace_config_invalid",
                        workspace_id=run_name,
                        workspace=run_dir,
                        reason=reason,
                    )
                ]
            )
        if reason.startswith("flow_adopt_failed"):
            return CommandResult.err(
                [
                    error_record(
                        "flow_adopt_failed",
                        workspace_id=run_name,
                        workspace=run_dir,
                        reason=reason,
                    )
                ]
            )
        return CommandResult.err(
            [
                error_record(
                    "flow_mismatch",
                    workspace_id=run_name,
                    workspace=run_dir,
                    reason="the configured flow diverges from the persisted one",
                    overwrite=disclosure_cmd("ecc run --overwrite", project, ctx.run_id),
                    hint="use --overwrite to rebuild the workspace, or choose a new --workspace",
                )
            ]
        )

    if cfg.manifest_driven:
        # Manifest mode: the workspace's own [flow] governs the range (the
        # seeded start/end is not re-consulted), but the effective declared
        # skip policy (ecc.toml over the project.json entry, carried on the
        # flow config) is applied over it so classification and any extension
        # use the same policy a fresh creation would.
        target_section = _manifest_skip_target(run_dir, flow_config)
    else:
        # The target carries the preset plus the effective declared skip
        # policy (already resolved through the shared ecc.toml-over-manifest
        # precedence onto the flow config), so an existing workspace
        # classifies against the same policy a fresh creation would use.
        target_section = {"preset": cfg.flow_preset} if cfg.flow_preset else None
        if target_section is not None:
            if isinstance(flow_config, dict) and "skip_steps" in flow_config:
                target_section["skip_steps"] = flow_config["skip_steps"]
            elif "flow.skip_steps" in cfg._explicit_keys:
                target_section["skip_steps"] = cfg.flow_skip_steps

    # Pure-read preflight: a divergent flow is rejected BEFORE load_workspace
    # can migrate configs, create home.json/checklist, or take the lock.
    probe = classify_workspace(run_dir, target_section)
    if probe.outcome == "mismatch":
        return mismatch_error(probe.error or "flow_mismatch")

    # Execution ownership: the ledger revalidation, migration, reconcile,
    # and the engine run all hold the workspace lock, so two `ecc run`
    # processes can never execute the same workspace concurrently.
    from chipcompiler.engine.reconcile import _workspace_lock, reconcile_workspace_locked

    with _workspace_lock(Path(run_dir)):
        probe = classify_workspace(run_dir, target_section)
        if probe.outcome == "mismatch":
            return mismatch_error(probe.error or "flow_mismatch")

        try:
            workspace = load_workspace(run_dir)
        except UnsupportedSchemaVersionError as exc:
            return CommandResult.err(
                [
                    error_record(
                        "unsupported_schema_version",
                        workspace_id=run_name,
                        workspace=run_dir,
                        reason=str(exc),
                    )
                ]
            )
        except (WorkspaceConfigError, WorkspaceFlowTargetError) as exc:
            return CommandResult.err(
                [
                    error_record(
                        "workspace_config_invalid",
                        workspace_id=run_name,
                        workspace=run_dir,
                        reason=str(exc),
                    )
                ]
            )
        except Exception as exc:
            # Mirrors run_workspace.py: an unloadable workspace (e.g. PDK
            # validation failing inside load_workspace) is a clean error
            # record, never a traceback.
            return CommandResult.err(
                [
                    error_record(
                        "invalid_workspace",
                        workspace_id=run_name,
                        workspace=run_dir,
                        reason=str(exc),
                    )
                ]
            )
        if workspace is None:
            return CommandResult.err(
                [
                    error_record(
                        "invalid_workspace",
                        workspace_id=run_name,
                        workspace=run_dir,
                    )
                ]
            )

        if cfg.params_overrides:
            # The warning was raised before the load; now that the persisted
            # parameters are available, attach the concrete divergence fixes.
            # The ecc.toml values stay ignored (semantics unchanged) — the
            # commands disclose how to apply them to this workspace.
            fixes = _diverging_workspace_param_fixes(
                workspace, run_name, cfg.params_overrides, project
            )
            if fixes:
                for warning in warnings:
                    if warning.get("warning") == "params_ignored_on_existing_run":
                        warning["diverging_params"] = ", ".join(key for key, _cmd in fixes)
                        warning["fix"] = "; ".join(cmd for _key, cmd in fixes)

        result = reconcile_workspace_locked(run_dir, target_section)
        if result.outcome == "mismatch":
            return mismatch_error(result.error or "flow_mismatch")

        if not result.persisted:
            # An existing run directory whose flow ledger has no steps cannot be
            # resumed or extended — nothing valid was persisted.
            return CommandResult.err(
                [
                    error_record(
                        "invalid_flow_json",
                        workspace_id=run_name,
                        workspace=run_dir,
                        reason="the persisted flow has no steps",
                        overwrite=disclosure_cmd("ecc run --overwrite", project, ctx.run_id),
                    )
                ]
            )

        from chipcompiler.engine import EngineFlow

        try:
            engine_flow = EngineFlow(workspace=workspace)
            flow_ok = True
            if result.outcome != "no_op":
                # Re-read the ledger: reconcile may have appended suffix steps
                # after load_workspace populated the in-memory copy.
                from chipcompiler.utility import json_read

                flow_data = json_read(workspace.flow.path or Path(run_dir) / "home" / "flow.json")
                target_names = set(result.target)
                executable = {
                    step["name"]
                    for step in flow_data.get("steps", [])
                    if isinstance(step, dict)
                    and isinstance(step.get("name"), str)
                    and not is_finished_step_state(step.get("state"))
                    and step["name"] in target_names
                }
                engine_flow.create_step_workspaces(executable_steps=executable)
                # executable_steps only gates dependency verification; the
                # actual runner iterates every workspace step. Bind execution
                # to the reconciled target so a wider persisted ledger (e.g.
                # RCX/sta beyond the requested end) never runs on resume.
                engine_flow.workspace_steps = [
                    step
                    for step in getattr(engine_flow, "workspace_steps", None) or []
                    if step.name in target_names
                ]

                from chipcompiler.cli.rendering.progress import (
                    run_flow_with_progress,
                    should_enable_run_progress,
                )

                if should_enable_run_progress(ctx, sys.stderr):
                    flow_ok = run_flow_with_progress(engine_flow, ctx, project, sys.stderr)
                else:
                    # The persisted ledger may be wider than the reconciled
                    # target by design (workspace_steps is bound above), so
                    # the full-ledger completeness check does not apply.
                    from chipcompiler.engine import ExecutionPlan, execute

                    flow_ok = execute(
                        engine_flow,
                        ExecutionPlan(
                            intent="run",
                            step_ids=tuple(step.name for step in engine_flow.workspace_steps),
                        ),
                    ).succeeded
        except Exception as exc:
            if workspace_registered:
                _write_back_status(
                    project_dir,
                    run_name,
                    "failed",
                    warnings,
                    repair=disclosure_cmd("ecc run", project, run_name),
                )
            return CommandResult.err(
                warnings
                + [
                    error_record(
                        "flow_failed",
                        workspace_id=run_name,
                        workspace=run_dir,
                        reason=str(exc),
                    )
                ]
            )

        if workspace_registered:
            _write_back_status(
                project_dir,
                run_name,
                "success" if flow_ok else "failed",
                warnings,
                repair=disclosure_cmd("ecc run", project, run_name),
            )

        record: dict = {
            "workspace_id": run_name,
            "status": "success" if flow_ok else "failed",
            "workspace": run_dir,
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
            "log_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
        }
        if result.outcome == "no_op":
            record["no_op"] = True
        if result.appended:
            record["appended_steps"] = list(result.appended)
        records = warnings + [record]
        if not flow_ok:
            return CommandResult.err(records)
        return CommandResult.ok(records)
