import contextlib
import os

from typing_extensions import deprecated

from chipcompiler.cli.core.inputs import (
    CheckInput,
    InitInput,
    MigrateInput,
    RunInput,
    RtlImportInput,
    WorkspaceImportInput,
)
from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult


def init(command_input: InitInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.project_init import ProjectInitError, create_project

    try:
        project_dir = create_project(command_input)
    except ProjectInitError as exc:
        return CommandResult.err([error_record(exc.code, reason=str(exc), path=exc.path)])

    project_arg = ctx.project or command_input.name
    return CommandResult.ok(
        [
            {
                "project": command_input.name,
                "status": "created",
                "path": str(project_dir),
                "check": disclosure_cmd("ecc check", project_arg),
                "run": disclosure_cmd("ecc run", project_arg),
            }
        ]
    )


def import_rtl(command_input: RtlImportInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.rtl_import import RtlImportError, import_project_rtl

    try:
        result = import_project_rtl(
            ctx.project_dir,
            filelist=command_input.filelist,
            verilog=command_input.verilog,
            force=command_input.force,
        )
    except RtlImportError as exc:
        return CommandResult.err([error_record(exc.code, reason=str(exc), path=exc.path)])
    return CommandResult.ok([result])


def check(command_input: CheckInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project import effective_config

    project = ctx.project

    if ctx.manifest_error:
        # Hybrid projects also resolve the run selector through the
        # manifest; an unresolvable selection is an error, not a warning.
        from chipcompiler.cli.core.records import manifest_error_record

        return CommandResult.err(
            [
                manifest_error_record(
                    ctx.manifest_error,
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )

    # Both manifest-only and hybrid projects validate the effective config:
    # manifest fallback applied, entry layer resolved, manifest relaxations
    # honored, every declared RTL source checked.
    cfg = ctx.config
    entry_warnings: list[dict] = []
    if ctx.project_state == "manifest":
        resolved_cfg = effective_config.resolve_effective_config(ctx, ctx.run_id, cfg)
        if isinstance(resolved_cfg, CommandResult):
            return resolved_cfg
        cfg, _entry_flow_config, entry_warnings = resolved_cfg
    elif cfg is None:
        return CommandResult.err(
            [
                error_record(
                    "missing_config",
                    path=os.path.join(ctx.project_dir, "ecc.toml"),
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )

    errors = effective_config.validate_effective(ctx, cfg, fresh=False, flow_config=None)

    if errors:
        return CommandResult.err(
            [
                {
                    "check": "config",
                    "status": "fail",
                    "reason": err,
                    "source": "ecc.toml" if ctx.config is not None else "project.json",
                    "inspect": disclosure_cmd("ecc check", project),
                }
                for err in errors
            ]
        )

    workspace_display = "default"
    if ctx.run_id is not None:
        workspace_display = ctx.run_dir
        if _canonically_inside(ctx.run_dir, ctx.project_dir):
            with contextlib.suppress(ValueError):
                workspace_display = os.path.relpath(
                    os.path.realpath(ctx.run_dir), os.path.realpath(ctx.project_dir)
                )

    records = [
        {
            "project": cfg.design_name,
            "status": "checked",
            "config": "ecc.toml" if ctx.config is not None else "project.json",
            "workspace": workspace_display,
            "run": disclosure_cmd("ecc run", project),
            "inspect_cmd": disclosure_cmd("ecc status", project),
        }
    ]

    if cfg.design_rtl:
        # Every declared RTL source must exist and have a usable shape —
        # the same rules `ecc run` enforces on entry inputs, so `ecc check`
        # never passes a project the next run would reject.
        from chipcompiler.cli.project.effective_config import _validate_rtl_source

        rtl_failures: list[dict] = []
        for entry in cfg.design_rtl:
            reasons = _validate_rtl_source(cfg.project_dir, entry)
            if reasons:
                rtl_failures.extend(
                    {
                        "check": "rtl",
                        "status": "fail",
                        "path": entry,
                        "reason": reason,
                        "inspect": disclosure_cmd("ecc check", project),
                    }
                    for reason in reasons
                )
        if rtl_failures:
            return CommandResult.err(rtl_failures)
        records.append(
            {
                "check": "rtl",
                "status": "pass",
                "path": cfg.design_rtl[0],
                "inspect": disclosure_cmd("ecc check", project),
            }
        )

    records.extend(entry_warnings)

    return CommandResult.ok(records)


def _preflight_environment(
    preset: str | None, project: str | None, flow_config: dict | None = None
) -> CommandResult | None:
    """Fail fast when the tools a fresh flow target needs are missing.

    The probe set comes from the preset's builder output filtered by the
    effective skip policy, so a skipped step's tool is never probed.

    None means ready.
    """
    from chipcompiler.cli.inspection import env_probe
    from chipcompiler.rtl2gds import resolve_lec_engine, resolve_skip_steps

    if preset is None:
        return None
    skip = resolve_skip_steps(flow_config)
    lec_engine = resolve_lec_engine(flow_config)
    probes = env_probe.probe_environment(
        env_probe.probe_components_for_preset(preset, skip=skip, lec_engine=lec_engine)
    )
    return _preflight_failures(probes, project, preset)


def _preflight_flow_range(flow_config: dict, project: str | None) -> CommandResult | None:
    """Fail fast when the tools a fresh flow range needs are missing.

    The selected range already names its tools, so a missing tool is a
    preflight failure before any manifest registration or workspace
    creation — not a discovery made mid-creation. The range is sliced
    from the policy-filtered chain, matching ledger creation.
    """
    from chipcompiler.cli.inspection import env_probe
    from chipcompiler.rtl2gds import build_flow_range, resolve_lec_engine, resolve_skip_steps

    try:
        steps = build_flow_range(
            flow_config["start_step"],
            flow_config["end_step"],
            skip=resolve_skip_steps(flow_config),
            lec_engine=resolve_lec_engine(flow_config),
        )
    except ValueError:
        # Range spellings are validated where they are declared (CLI ranges
        # during argument handling, manifest ranges at load time); an
        # unresolvable range here degrades to no preflight, never a new
        # failure mode in front of the run.
        return None
    probes = env_probe.probe_environment(env_probe.probe_components_for_steps(steps))
    return _preflight_failures(probes, project, None)


def _preflight_failures(probes, project: str | None, preset: str | None) -> CommandResult | None:
    """Map failed probes to env_not_ready; None means ready."""
    from chipcompiler.cli.inspection import env_probe

    failures = [p for p in probes if p.status == env_probe.FAIL]
    if not failures:
        return None
    records = [
        error_record(
            "env_not_ready",
            reason="; ".join(f"{p.component}: {p.remediation or p.detail}" for p in failures),
            preset=preset,
            doctor=disclosure_cmd("ecc doctor", project),
        )
    ]
    records.extend(
        {
            "component": p.component,
            "status": p.status,
            "required": p.required,
            "remediation": p.remediation,
        }
        for p in failures
    )
    return CommandResult.err(records)


def _canonically_inside(path: str, anchor: str) -> bool:
    """Return True when path's canonical resolution is anchor or below it."""
    real_base = os.path.realpath(anchor)
    real = os.path.realpath(path)
    return real == real_base or real.startswith(real_base.rstrip(os.sep) + os.sep)


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
def migrate(command_input: MigrateInput, ctx: CommandContext) -> CommandResult:
    """Upgrade a legacy runs/ project to the manifest layout."""
    from chipcompiler.cli.project.migrate import migrate_project

    return migrate_project(command_input, ctx)


def run(command_input: RunInput, ctx: CommandContext) -> CommandResult:
    try:
        return _run_project(command_input, ctx, execute_flow=True)
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)


def create_workspace(command_input, ctx: CommandContext) -> CommandResult:
    """Create and register a Workspace without executing its flow."""
    import uuid
    from pathlib import Path

    target = Path(ctx.run_dir).expanduser().absolute()
    project = Path(ctx.project_dir).expanduser().resolve()
    if target.parent.resolve() != project:
        return CommandResult.err(
            [
                error_record(
                    "workspace_path_outside_standard_parent",
                    path=str(target),
                    reason="new Workspaces must be direct children of the Project root",
                )
            ]
        )
    run_input = RunInput(
        output=command_input.output,
        project=command_input.project,
        workspace=command_input.workspace,
        from_step=command_input.from_step,
        to_step=command_input.to_step,
        param_set=command_input.param_set,
        command_id=command_input.command_id or str(uuid.uuid4()),
        no_wait=command_input.no_wait,
    )
    try:
        return _run_project(run_input, ctx, execute_flow=False)
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)


def refresh_workspace(command_input, ctx: CommandContext) -> CommandResult:
    """Recreate one managed workspace from current project configuration."""
    if ctx.project_state != "manifest":
        return CommandResult.err(
            [
                error_record(
                    "workspace_refresh_requires_managed_workspace",
                    reason="refresh requires a workspace declared in project.json",
                )
            ]
        )
    from chipcompiler.data.workspace.config_manifest import modified_derived_configs

    modified = modified_derived_configs(ctx.run_dir)
    if modified and not command_input.force:
        return CommandResult.err(
            [
                error_record(
                    "derived_configs_modified",
                    workspace=ctx.run_dir,
                    files=", ".join(modified),
                    reason="config/*.json changed since the last derivation; "
                    "refresh would overwrite those edits",
                    hint="rerun with --force to overwrite, or carry the edits "
                    "through 'ecc param set --workspace' / ecc.toml instead",
                )
            ]
        )
    cfg = ctx.config
    from chipcompiler.cli.project import effective_config

    resolved = effective_config.resolve_effective_config(ctx, ctx.run_id, cfg)
    if isinstance(resolved, CommandResult):
        return resolved
    cfg, flow_config, warnings = resolved
    errors = effective_config.validate_effective(
        ctx,
        cfg,
        fresh=True,
        flow_config=flow_config,
    )
    if errors:
        return CommandResult.err(
            [error_record(_config_error_code(problem), reason=problem) for problem in errors]
        )
    from chipcompiler.cli.project.workspace_spec import workspace_update_spec
    from chipcompiler.engine import update_workspace_from_spec
    from chipcompiler.engine.snapshot import (
        read_engineering_snapshot,
        read_engineering_snapshot_from_directory,
    )
    from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError

    backup_directory = None
    fallback_backup = None
    try:
        current = read_engineering_snapshot_from_directory(ctx.run_dir)
        expected = command_input.expected_revision or current["workspaceRevision"]
        spec, bindings = workspace_update_spec(ctx.run_dir, cfg, flow_config)
        # Keep compatibility with older embedders that provide the lifecycle
        # callable without the optional backup keyword. The in-tree engine
        # supports it; this fallback only preserves the previous generation
        # when an older callable is injected.
        import inspect
        from pathlib import Path

        supports_backup = (
            "retain_backup" in inspect.signature(update_workspace_from_spec).parameters
        )
        if command_input.keep_backup and not supports_backup:
            from shutil import copytree

            from chipcompiler.engine.workspace_backup import _free_backup_path

            fallback_backup = _free_backup_path(Path(ctx.run_dir))
            copytree(ctx.run_dir, fallback_backup)
        update_kwargs = {
            "blocking": not command_input.no_wait,
            **({"retain_backup": command_input.keep_backup} if supports_backup else {}),
        }
        workspace = update_workspace_from_spec(
            ctx.run_dir,
            expected,
            spec,
            bindings,
            command_input.command_id,
            **update_kwargs,
        )
        backup_directory = getattr(workspace, "backup_directory", None) or fallback_backup
        workspace = getattr(workspace, "workspace", workspace)
        snapshot = read_engineering_snapshot(workspace)
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except WorkspaceLifecycleError as exc:
        return CommandResult.err(
            [error_record(exc.code, reason=str(exc), **exc.details)],
            exit_code=21 if exc.code == "revision_conflict" else 1,
        )
    except Exception as exc:
        if fallback_backup is not None:
            import shutil

            shutil.rmtree(fallback_backup, ignore_errors=True)
        return CommandResult.err([error_record("workspace_refresh_failed", reason=str(exc))])

    backup_id = None
    if backup_directory is not None:
        from chipcompiler.project import register_workspace_backup

        try:
            register_workspace_backup(
                ctx.project_dir,
                backup_directory,
                source_workspace_id=ctx.run_id,
            )
            backup_id = backup_directory.name
        except (OSError, ValueError) as exc:
            warnings.append(
                error_record(
                    "manifest_write_back_failed",
                    workspace_id=ctx.run_id,
                    reason=f"replace backup could not be registered in project.json: {exc}",
                )
            )
    from chipcompiler.project import repoint_generation_pointers

    try:
        repoint_generation_pointers(ctx.project_dir, ctx.run_id, backup_id)
    except (OSError, ValueError) as exc:
        warnings.append(
            error_record(
                "manifest_write_back_failed",
                workspace_id=ctx.run_id,
                reason=f"baseline/best pointers could not be updated in project.json: {exc}",
            )
        )
    return CommandResult.ok(
        warnings
        + [
            {
                "workspace_id": ctx.run_id,
                "status": "refreshed",
                "workspace": ctx.run_dir,
                "workspace_revision": snapshot["workspaceRevision"],
                **({"backup": str(backup_directory)} if backup_directory else {}),
            }
        ]
    )


def import_workspace(command_input: WorkspaceImportInput, ctx: CommandContext) -> CommandResult:
    """Register an existing workspace without opening or changing it."""
    if ctx.project_state == "legacy":
        return CommandResult.err([error_record("legacy_workspace_migration_required")])
    if ctx.manifest_error:
        return CommandResult.err(
            [
                error_record(
                    ctx.manifest_error.split(":", 1)[0],
                    reason=ctx.manifest_error,
                )
            ]
        )
    cfg = ctx.config
    if cfg is None and ctx.project_state != "manifest":
        return CommandResult.err(
            [
                error_record(
                    "missing_config",
                    path=os.path.join(ctx.project_dir, "ecc.toml"),
                )
            ]
        )

    if ctx.project_state == "manifest":
        from chipcompiler.cli.project import effective_config

        resolved = effective_config.resolve_effective_config(ctx, command_input.workspace, cfg)
        if isinstance(resolved, CommandResult):
            return resolved
        cfg, _flow_config, warnings = resolved
    else:
        warnings = []
    assert cfg is not None

    from chipcompiler.cli.project.config import resolve_pdk_root
    from chipcompiler.cli.project.workspace_registration import (
        WorkspaceRegistrationError,
        register_existing_workspace,
    )

    try:
        outcome, metadata = register_existing_workspace(
            ctx.project_dir,
            cfg=cfg,
            pdk_root=resolve_pdk_root(cfg),
            workspace_id=command_input.workspace,
            workspace_path=ctx.run_dir,
            blocking=not command_input.no_wait,
        )
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except WorkspaceRegistrationError as exc:
        return CommandResult.err(
            [
                error_record(
                    exc.code,
                    workspace_id=command_input.workspace,
                    workspace=ctx.run_dir,
                    reason=str(exc),
                )
            ]
        )

    if outcome.startswith("conflict"):
        return CommandResult.err(
            [
                error_record(
                    "workspace_conflict",
                    workspace_id=command_input.workspace,
                    workspace=ctx.run_dir,
                )
            ]
        )
    if outcome not in ("registered", "existing"):
        return CommandResult.err(
            [
                error_record(
                    "workspace_registration_failed",
                    workspace_id=command_input.workspace,
                    workspace=ctx.run_dir,
                )
            ]
        )

    return CommandResult.ok(
        warnings
        + [
            {
                "workspace_id": command_input.workspace,
                "registration": "imported" if outcome == "registered" else "already_registered",
                "status": metadata.status,
                "workspace": ctx.run_dir,
                "run_cmd": disclosure_cmd("ecc run", ctx.project, command_input.workspace),
            }
        ]
    )


def derive_workspace(command_input, ctx: CommandContext) -> CommandResult:
    import shutil
    import uuid
    from pathlib import Path

    from chipcompiler.cli.project.run_prepare import invalid_workspace_name
    from chipcompiler.engine.workspace_derive import derive_workspace as derive
    from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError
    from chipcompiler.project.api import _project_manifest_mutator
    from chipcompiler.project.manifest import load_manifest
    from chipcompiler.project.manifest_write import manifest_lock, update_manifest_locked

    if ctx.project_state != "manifest" or ctx.manifest_error or ctx.run_id is None:
        return CommandResult.err(
            [error_record("workspace_derive_requires_managed_source", reason=ctx.manifest_error)]
        )
    target_id = command_input.target_workspace
    if invalid_workspace_name(target_id):
        return CommandResult.err([error_record("invalid_workspace", workspace_id=target_id)])
    project = Path(ctx.project_dir).resolve()
    target = project / target_id
    target_existed = target.exists()
    command_id = command_input.command_id or str(uuid.uuid4())
    try:
        project_manifest = load_manifest(str(project))
        derived = derive(
            ctx.run_dir,
            target,
            reset_from_step=command_input.from_step or "",
            command_id=command_id,
            blocking=not command_input.no_wait,
            project_id=project_manifest.project_id,
            source_workspace_id=ctx.run_id,
            target_workspace_id=target_id,
        )
        with manifest_lock(project, blocking=not command_input.no_wait):
            load_manifest(str(project))
            mutation = {
                "type": "register_workspace",
                "workspace_id": target_id,
                "workspace_path": str(target),
                "source_workspace_id": ctx.run_id,
                "branch_from": {
                    "source_workspace_id": ctx.run_id,
                    **({"source_step": command_input.from_step} if command_input.from_step else {}),
                },
            }
            if not update_manifest_locked(project, _project_manifest_mutator(project, mutation)):
                raise OSError("Project Manifest update failed")
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except (WorkspaceLifecycleError, OSError, ValueError) as exc:
        if not target_existed and target.is_dir() and target != Path(ctx.run_dir):
            shutil.rmtree(target, ignore_errors=True)
        code = exc.code if isinstance(exc, WorkspaceLifecycleError) else "workspace_derive_failed"
        return CommandResult.err([error_record(code, reason=str(exc))])
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    snapshot = read_engineering_snapshot(derived)
    return CommandResult.ok(
        [
            {
                "workspace_id": target_id,
                "status": "derived",
                "workspace": str(target),
                "workspace_revision": snapshot["workspaceRevision"],
            }
        ]
    )


def archive_workspace(command_input, ctx: CommandContext) -> CommandResult:
    return _manage_workspace_lifecycle(command_input, ctx, "archive")


def delete_workspace(command_input, ctx: CommandContext) -> CommandResult:
    return _manage_workspace_lifecycle(command_input, ctx, "delete")


def _manage_workspace_lifecycle(
    command_input, ctx: CommandContext, operation: str
) -> CommandResult:
    import uuid

    from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory
    from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError
    from chipcompiler.engine.workspace_management import (
        archive_managed_workspace,
        delete_managed_workspace,
    )

    if ctx.project_state != "manifest" or ctx.manifest_error or ctx.run_id is None:
        return CommandResult.err(
            [error_record("workspace_not_declared", reason=ctx.manifest_error)]
        )
    try:
        current = read_engineering_snapshot_from_directory(ctx.run_dir)
        expected = command_input.expected_revision or current["workspaceRevision"]
        command_id = command_input.command_id or str(uuid.uuid4())
        if operation == "archive":
            workspace = archive_managed_workspace(
                ctx.project_dir,
                ctx.run_id,
                expected,
                command_id=command_id,
                blocking=not command_input.no_wait,
            )
        else:
            workspace = delete_managed_workspace(
                ctx.project_dir,
                ctx.run_id,
                expected,
                command_id=command_id,
                delete_directory=command_input.delete_directory,
                blocking=not command_input.no_wait,
            )
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except WorkspaceLifecycleError as exc:
        return CommandResult.err(
            [error_record(exc.code, reason=str(exc), **exc.details)],
            exit_code=21 if exc.code == "revision_conflict" else 1,
        )
    except Exception as exc:
        return CommandResult.err([error_record(f"workspace_{operation}_failed", reason=str(exc))])
    return CommandResult.ok(
        [{"workspace_id": ctx.run_id, "status": f"{operation}d", "workspace": str(workspace)}]
    )


def reconcile_workspace_deletes(command_input, ctx: CommandContext) -> CommandResult:
    from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError
    from chipcompiler.engine.workspace_management import reconcile_workspace_deletes as reconcile

    if ctx.project_state != "manifest" or ctx.manifest_error:
        return CommandResult.err([error_record("manifest_invalid", reason=ctx.manifest_error)])
    try:
        recovered = reconcile(ctx.project_dir, blocking=not command_input.no_wait)
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except WorkspaceLifecycleError as exc:
        return CommandResult.err([error_record(exc.code, reason=str(exc), **exc.details)])
    except Exception as exc:
        return CommandResult.err(
            [error_record("workspace_delete_reconcile_failed", reason=str(exc))]
        )
    return CommandResult.ok([{"status": "reconciled", "recovered_deletes": list(recovered)}])


def reset_workspace_flow(command_input, ctx: CommandContext) -> CommandResult:
    import uuid

    from chipcompiler.engine.snapshot import (
        read_engineering_snapshot,
        read_engineering_snapshot_from_directory,
    )
    from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError
    from chipcompiler.engine.workspace_reset import reset_workspace_flow as reset

    if ctx.project_state != "manifest" or ctx.manifest_error or ctx.run_id is None:
        return CommandResult.err(
            [error_record("workspace_not_declared", reason=ctx.manifest_error)]
        )
    try:
        current = read_engineering_snapshot_from_directory(ctx.run_dir)
        expected = command_input.expected_revision or current["workspaceRevision"]
        workspace = reset(
            ctx.run_dir,
            expected,
            command_id=command_input.command_id or str(uuid.uuid4()),
            blocking=not command_input.no_wait,
        )
        snapshot = read_engineering_snapshot(workspace)
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except WorkspaceLifecycleError as exc:
        return CommandResult.err(
            [error_record(exc.code, reason=str(exc), **exc.details)],
            exit_code=21 if exc.code == "revision_conflict" else 1,
        )
    except Exception as exc:
        return CommandResult.err([error_record("workspace_reset_failed", reason=str(exc))])
    return CommandResult.ok(
        [
            {
                "workspace_id": ctx.run_id,
                "status": "flow_reset",
                "workspace": ctx.run_dir,
                "workspace_revision": snapshot["workspaceRevision"],
            }
        ]
    )


def _run_project(
    command_input: RunInput, ctx: CommandContext, *, execute_flow: bool
) -> CommandResult:
    def error(kind: str, **fields) -> CommandResult:
        return CommandResult.err([{"kind": "error", "error": kind, **fields}])

    if ctx.project_state == "legacy":
        return error("legacy_workspace_migration_required")
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
    from chipcompiler.cli.project import run_dispatch, run_prepare

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
                    "path": os.path.join(project_dir, "ecc.toml"),
                }
            ]
        )

    from chipcompiler.cli.project import effective_config
    from chipcompiler.cli.project.effective_config import flow_config_selects_steps

    if ctx.project_state == "manifest":
        resolved_cfg = effective_config.resolve_effective_config(ctx, ctx.run_id, cfg)
        if isinstance(resolved_cfg, CommandResult):
            return resolved_cfg
        cfg, flow_config, entry_warnings = resolved_cfg
        layer_warnings.extend(entry_warnings)
    else:
        # Virgin projects have no manifest layer; an ecc.toml skip policy
        # still rides on the flow config (policy-only when no range applies).
        from chipcompiler.cli.project.effective_config import (
            _attach_lec_engine,
            _attach_skip_steps,
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

    assert cfg is not None

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
    # The resolved skip policy and LEC engine survive every target override
    # below (they come from configuration, never from the target spelling).
    skip_policy = flow_config.get("skip_steps") if isinstance(flow_config, dict) else None
    lec_engine_policy = flow_config.get("lec_engine") if isinstance(flow_config, dict) else None
    if command_input.preset is not None:
        # The explicit CLI selection takes precedence over a manifest range
        # for this invocation without changing either project config file.
        cfg.flow_preset = effective_preset
        cfg.manifest_driven = False
        flow_config = {"skip_steps": skip_policy} if skip_policy is not None else None
        if lec_engine_policy is not None:
            flow_config = flow_config or {}
            flow_config["lec_engine"] = lec_engine_policy

    if command_input.from_step is not None and command_input.to_step is not None:
        try:
            from chipcompiler.rtl2gds import build_flow_range, resolve_skip_steps

            skip = resolve_skip_steps(
                {"skip_steps": skip_policy} if skip_policy is not None else None
            )
            build_flow_range(command_input.from_step, command_input.to_step, skip=skip)
        except ValueError as exc:
            return error("flow_range_invalid", reason=str(exc))
        flow_config = {
            "start_step": command_input.from_step,
            "end_step": command_input.to_step,
        }
        if skip_policy is not None:
            flow_config["skip_steps"] = skip_policy
        if lec_engine_policy is not None:
            flow_config["lec_engine"] = lec_engine_policy

    cli_overrides: dict[str, object] = {}
    raw_sets = command_input.param_set
    if raw_sets:
        from chipcompiler.cli.project.params import parse_cli_overrides

        cli_overrides, set_errors = parse_cli_overrides(list(raw_sets))
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

    # TODO: Move non-interactive project run preparation/execution into
    # the historical project runner or
    # chipcompiler.engine.project_run.prepare_and_run. Keep CLI ownership limited
    # to input parsing, progress renderer selection, and CommandResult mapping.
    project_state = ctx.project_state
    warning_records: list[dict] = []
    run_dir = ctx.run_dir
    run_name = ctx.run_id or "default"
    workspace_registered = False

    if project_state in ("virgin", "manifest"):
        resolved = run_prepare.resolve_manifest_run_target(command_input, ctx)
        if isinstance(resolved, CommandResult):
            return resolved
        run_dir, run_name, workspace_registered, warning_records = resolved
    warning_records = layer_warnings + warning_records

    flow_json = os.path.join(run_dir, "home", "flow.json")
    fresh_target = not os.path.exists(flow_json) or command_input.overwrite
    if fresh_target and command_input.from_step is not None and command_input.to_step is None:
        return error("flow_range_requires_pair")
    if fresh_target and (command_input.resume or command_input.only is not None):
        return error("selector_requires_workspace")
    if not fresh_target and ctx.project_state == "manifest" and cfg.manifest_driven:
        return run_dispatch.dispatch_project_run(
            command_input,
            ctx,
            cfg,
            run_dir,
            run_name,
            cli_overrides,
            flow_config,
            project_state,
            warning_records,
            workspace_registered=workspace_registered,
            execute_flow=execute_flow,
        )
    errors = effective_config.validate_effective(
        ctx,
        cfg,
        # An overwrite wipes and recreates the target, so it validates as a
        # fresh run (a derivable flow target is required) even when the
        # ledger still exists at preflight time.
        fresh=fresh_target,
        flow_config=flow_config,
        cli_overrides=cli_overrides,
    )
    if errors:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": _config_error_code(err),
                    "reason": err,
                }
                for err in errors
            ]
        )

    # A creation-time (fresh/overwrite only) configuration conflict: the
    # synthesis_lec preset exists to run the LEC the effective policy skips.
    # Existing ledgers are never re-filtered, so resume/rerun is unaffected.
    if (
        fresh_target
        and effective_preset == "synthesis_lec"
        and "lec" in resolve_skip_steps_for_flow_config(flow_config)
    ):
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "config_error",
                    "reason": (
                        "the synthesis_lec preset conflicts with the effective skip_steps "
                        "policy (lec is skipped); set skip_steps = [] to enable it"
                    ),
                }
            ]
        )

    protected = (project_dir, os.path.join(project_dir, "runs"))
    spelled = {os.path.normpath(p) for p in protected}
    canonical = {os.path.realpath(p) for p in protected}
    if os.path.normpath(run_dir) in spelled or os.path.realpath(run_dir) in canonical:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "invalid_workspace",
                    "workspace_id": run_name,
                    "workspace": run_dir,
                    "reason": (
                        "workspace name must not resolve to the project or legacy runs container"
                    ),
                }
            ]
        )

    # Fresh targets preflight before any mutation. Named presets probe the
    # tools their builder needs; manifest/CLI flow ranges derive the same
    # probe set from the selected chain, so a missing tool fails fast
    # instead of surfacing mid-creation.
    if fresh_target:
        if flow_config_selects_steps(flow_config):
            preflight = _preflight_flow_range(flow_config, project)
        elif effective_preset:
            preflight = _preflight_environment(effective_preset, project, flow_config)
        else:
            preflight = None
        if preflight is not None:
            return preflight

    if (
        not fresh_target
        and not ctx.workspace_path_explicit
        and (
            command_input.resume
            or command_input.from_step is not None
            or command_input.only is not None
        )
    ):
        return _run_workspace(command_input, ctx)

    return run_dispatch.dispatch_project_run(
        command_input,
        ctx,
        cfg,
        run_dir,
        run_name,
        cli_overrides,
        flow_config,
        project_state,
        warning_records,
        workspace_registered=workspace_registered,
        execute_flow=execute_flow,
    )


def _config_error_code(reason: str) -> str:
    for code in ("step_input_missing", "unsupported_flow_run"):
        if reason.startswith(f"{code}:"):
            return code
    return "config_error"


def resolve_skip_steps_for_flow_config(flow_config) -> tuple[str, ...]:
    """The effective skip policy of a creation flow config (default when none)."""
    from chipcompiler.rtl2gds import resolve_skip_steps

    return resolve_skip_steps(
        flow_config if isinstance(flow_config, dict) and "skip_steps" in flow_config else None
    )


def _run_workspace(command_input: RunInput, ctx: CommandContext) -> CommandResult:
    def error(kind: str, **fields) -> CommandResult:
        return CommandResult.err([{"kind": "error", "error": kind, **fields}])

    selectors = sum(
        (
            command_input.resume,
            command_input.from_step is not None,
            command_input.only is not None,
        )
    )
    if selectors > 1:
        return error("selector_conflict")
    if command_input.force and command_input.only is None:
        return error("force_requires_only")

    from chipcompiler.cli.project import run_workspace

    # Only manifest projects carry a project.json status to write back.
    project_dir = ctx.project_dir if ctx.project_state == "manifest" else None
    return run_workspace.execute_workspace_run(
        command_input, ctx.run_dir, ctx.run_id, project_dir=project_dir
    )
