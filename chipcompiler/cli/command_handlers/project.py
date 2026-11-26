import contextlib
import os
import shlex

from chipcompiler.cli.core.inputs import (
    CheckInput,
    InitInput,
    RtlImportInput,
    RunInput,
    WorkspaceCreateInput,
    WorkspaceImportInput,
)
from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record, manifest_error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project.preparation import (
    config_error_code,
    preflight_fresh_setup,
    resolve_run_setup,
    validate_run_setup,
)
from chipcompiler.project.manifest import CONFIG_FILENAME


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
    entry_flow_config: dict | None = None
    entry_warnings: list[dict] = []
    if ctx.project_state == "manifest":
        resolved_cfg = effective_config.resolve_effective_config(ctx, ctx.run_id, cfg)
        if isinstance(resolved_cfg, CommandResult):
            return resolved_cfg
        cfg, entry_flow_config, entry_warnings = resolved_cfg
    elif cfg is None:
        return CommandResult.err(
            [
                error_record(
                    "missing_config",
                    path=os.path.join(ctx.project_dir, CONFIG_FILENAME),
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )

    errors = effective_config.validate_effective(
        ctx, cfg, fresh=False, flow_config=entry_flow_config
    )

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

    records: list[dict[str, object]] = [
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

    from chipcompiler.cli.project.flow_selection import selection_warnings

    records.extend(selection_warnings(cfg, entry_flow_config))
    records.extend(entry_warnings)

    return CommandResult.ok(records)


def _canonically_inside(path: str, anchor: str) -> bool:
    """Return True when path's canonical resolution is anchor or below it."""
    real_base = os.path.realpath(anchor)
    real = os.path.realpath(path)
    return real == real_base or real.startswith(real_base.rstrip(os.sep) + os.sep)


def run(command_input: RunInput, ctx: CommandContext) -> CommandResult:
    try:
        return _run_project(command_input, ctx, execute_flow=True)
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)


def create_workspace(command_input: WorkspaceCreateInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.creation import (
        build_create_run_input,
        create_draft_or_preview_workspace,
    )

    try:
        if command_input.draft is None and not command_input.preview:
            run_input = build_create_run_input(command_input, ctx)
            if isinstance(run_input, CommandResult):
                return run_input
            return _run_project(run_input, ctx, execute_flow=False)
        return create_draft_or_preview_workspace(command_input, ctx)
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
    if ctx.manifest_error:
        # An undeclared name still resolves run_dir to <project>/<name>.
        # Refreshing it would rebuild a directory the project does not manage.
        return CommandResult.err(
            [error_record(ctx.manifest_error.split(":", 1)[0], reason=ctx.manifest_error)]
        )
    if not os.path.isdir(ctx.run_dir):
        return _workspace_directory_missing(ctx)
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
            [error_record(config_error_code(problem), reason=problem) for problem in errors]
        )
    from chipcompiler.cli.project.workspace_spec import workspace_update_spec
    from chipcompiler.engine import update_workspace_from_spec
    from chipcompiler.engine.snapshot.store import (
        read_engineering_snapshot,
        read_engineering_snapshot_from_directory,
    )
    from chipcompiler.engine.workspace.lifecycle import WorkspaceLifecycleError

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

        update_parameters = inspect.signature(update_workspace_from_spec).parameters
        supports_backup = "retain_backup" in update_parameters
        if command_input.keep_backup and not supports_backup:
            from shutil import copytree

            from chipcompiler.engine.workspace.backup import _free_backup_path

            fallback_backup = _free_backup_path(Path(ctx.run_dir))
            copytree(ctx.run_dir, fallback_backup)
        update_kwargs = {
            "blocking": not command_input.no_wait,
            **({"retain_backup": command_input.keep_backup} if supports_backup else {}),
        }
        if not command_input.expected_revision and "revision_pinned" in update_parameters:
            # The revision was filled in above, not named by the caller: it
            # is checked, but it is not part of the command's identity.
            update_kwargs["revision_pinned"] = False
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
        if ctx.run_id is not None:
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
        from chipcompiler.cli.core.records import legacy_workspace_error_record

        return CommandResult.err([legacy_workspace_error_record()])
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
                    path=os.path.join(ctx.project_dir, CONFIG_FILENAME),
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


def archive_workspace(command_input, ctx: CommandContext) -> CommandResult:
    return _manage_workspace_lifecycle(command_input, ctx, "archive")


def delete_workspace(command_input, ctx: CommandContext) -> CommandResult:
    return _manage_workspace_lifecycle(command_input, ctx, "delete")


def _manage_workspace_lifecycle(
    command_input, ctx: CommandContext, operation: str
) -> CommandResult:
    import uuid

    from chipcompiler.engine.snapshot.store import read_engineering_snapshot_from_directory
    from chipcompiler.engine.workspace.lifecycle import WorkspaceLifecycleError
    from chipcompiler.engine.workspace.management import (
        archive_managed_workspace,
        delete_managed_workspace,
        unregister_missing_workspace,
    )

    if ctx.project_state != "manifest" or ctx.manifest_error or ctx.run_id is None:
        return CommandResult.err([manifest_error_record(ctx.manifest_error)])
    missing = not os.path.isdir(ctx.run_dir)
    if missing and operation != "delete":
        return _workspace_directory_missing(ctx)
    try:
        if missing:
            # Nothing is left but the registration: there is no revision to
            # check and no directory to keep or remove.
            workspace = unregister_missing_workspace(
                ctx.project_dir, ctx.run_id, blocking=not command_input.no_wait
            )
            return CommandResult.ok(
                [{"workspace_id": ctx.run_id, "status": "deleted", "workspace": str(workspace)}]
            )
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


def _workspace_directory_missing(ctx: CommandContext) -> CommandResult:
    """The error of a command that needs the directory of a declared workspace."""
    project = ctx.project
    workspace_id = ctx.run_id or ""
    return CommandResult.err(
        [
            error_record(
                "workspace_missing",
                reason=f"workspace directory does not exist: {ctx.run_dir}",
                workspace_id=workspace_id,
                delete_cmd=disclosure_cmd(
                    f"ecc workspace delete {shlex.quote(workspace_id)}", project
                ),
                create_cmd=disclosure_cmd(
                    f"ecc workspace create {shlex.quote(workspace_id)}", project
                ),
            )
        ]
    )


def reconcile_workspace_deletes(command_input, ctx: CommandContext) -> CommandResult:
    from chipcompiler.engine.workspace.lifecycle import WorkspaceLifecycleError
    from chipcompiler.engine.workspace.management import reconcile_workspace_deletes as reconcile

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

    from chipcompiler.engine.snapshot.store import (
        read_engineering_snapshot,
        read_engineering_snapshot_from_directory,
    )
    from chipcompiler.engine.workspace.lifecycle import WorkspaceLifecycleError
    from chipcompiler.engine.workspace.reset import reset_workspace_flow as reset

    if ctx.project_state != "manifest" or ctx.manifest_error or ctx.run_id is None:
        return CommandResult.err([manifest_error_record(ctx.manifest_error)])
    if not os.path.isdir(ctx.run_dir):
        return _workspace_directory_missing(ctx)
    try:
        current = read_engineering_snapshot_from_directory(ctx.run_dir)
        expected = command_input.expected_revision or current["workspaceRevision"]
        workspace = reset(
            ctx.run_dir,
            expected,
            command_id=command_input.command_id or str(uuid.uuid4()),
            blocking=not command_input.no_wait,
            revision_pinned=bool(command_input.expected_revision),
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
    command_input: RunInput,
    ctx: CommandContext,
    *,
    execute_flow: bool,
) -> CommandResult:
    from chipcompiler.cli.project import run_dispatch

    setup = resolve_run_setup(command_input, ctx, execute_flow=execute_flow)
    if isinstance(setup, CommandResult):
        return setup

    warning_records = setup.warning_records
    # Manifest-only continuations use the Workspace's recorded target.
    if setup.fresh_target or ctx.project_state != "manifest" or not setup.cfg.manifest_driven:
        validation_error = validate_run_setup(setup, ctx)
        if validation_error is not None:
            return validation_error

        if setup.fresh_target:
            preflight, warning_records = preflight_fresh_setup(setup, ctx.project)
            if preflight is not None:
                return preflight

        undeclared_directory = ctx.project_state == "manifest" and not setup.workspace_registered
        if (
            execute_flow
            and not setup.fresh_target
            and not ctx.workspace_path_explicit
            and not undeclared_directory
            and (
                command_input.resume
                or command_input.from_step is not None
                or command_input.only is not None
            )
        ):
            from chipcompiler.cli.project.run_workspace import execute_workspace_run

            return execute_workspace_run(
                command_input,
                ctx.run_dir,
                ctx.run_id,
                project_dir=ctx.project_dir if ctx.project_state == "manifest" else None,
                ctx=ctx,
            )

    return run_dispatch.dispatch_project_run(
        command_input,
        ctx,
        setup.cfg,
        setup.run_dir,
        setup.run_name,
        setup.cli_overrides,
        setup.flow_config,
        ctx.project_state,
        warning_records,
        workspace_registered=setup.workspace_registered,
        execute_flow=execute_flow,
    )
