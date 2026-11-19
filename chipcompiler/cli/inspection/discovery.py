import os
from pathlib import Path

from chipcompiler.cli.core.output import (
    disclosure_cmd,
    flow_step_status,
)
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.data.step import STEP_DIRECTORIES, StepDirectories

CORRUPT_FLOW_JSON = "CORRUPT"


def read_flow_json(run_dir: str) -> dict | str | None:
    from chipcompiler.data.schema_versions import UnsupportedSchemaVersionError
    from chipcompiler.data.workspace.flow_types import load_flow_document

    path = os.path.join(run_dir, "home", "flow.json")
    if not os.path.isfile(path):
        return None
    try:
        return dict(load_flow_document(Path(path)))
    except (UnsupportedSchemaVersionError, ValueError, OSError):
        return CORRUPT_FLOW_JSON


def _safe_steps(flow_data: dict) -> list[dict]:
    steps = flow_data.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [s for s in steps if isinstance(s, dict)]


def get_run_status(flow_data: dict) -> str:
    from chipcompiler.data import ADVISORY_FLOW_STEPS

    steps = _safe_steps(flow_data)
    if not steps:
        return "unstart"
    states = set()
    for step in steps:
        state = flow_step_status(step.get("state", ""))
        if state == "skipped":
            state = "success"
        if step.get("name") in ADVISORY_FLOW_STEPS and state == "incomplete":
            state = "success"
        states.add(state)
    if states & {"ongoing", "pending"}:
        return "ongoing"
    if states & {"incomplete", "invalid"}:
        return "failed"
    if states == {"success"}:
        return "success"
    if states == {"unstart"}:
        return "unstart"
    if states <= {"success", "unstart"}:
        # A bounded rerun (--only / --from / --to) leaves the executed
        # prefix success and the stale suffix unstart until the user
        # re-runs it: that is partial progress, not a failure.
        return "partial"
    return "failed"


def discover_step_dirs(run_dir: str) -> dict[str, str]:
    """Step name -> directory of each step whose artifacts *run_dir* holds.

    Ledger steps use their recorded directory; a step absent from a bounded
    ledger uses its inherited, else its base ``<step>_<tool>``, directory.
    """
    if not os.path.isdir(run_dir):
        return {}
    flow_data = read_flow_json(run_dir)
    steps = _safe_steps(flow_data) if isinstance(flow_data, dict) else []
    directories = StepDirectories.from_records(Path(run_dir), steps)
    names = dict.fromkeys([*directories.reader_step_names(), *STEP_DIRECTORIES])
    return {step: str(directories.path(step)) for step in names if directories.path(step).is_dir()}


def get_flow_step_names(run_dir: str) -> set[str]:
    flow_data = read_flow_json(run_dir)
    if not isinstance(flow_data, dict):
        return set()
    return {s.get("name", "") for s in _safe_steps(flow_data) if s.get("name")}


def _list_files(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
    )


def discover_logs(run_dir: str, step_token: str | None = None) -> list[str]:
    if step_token is None:
        return _list_files(os.path.join(run_dir, "log"))

    step_dirs = discover_step_dirs(run_dir)
    if step_token not in step_dirs:
        return []

    return _list_files(os.path.join(step_dirs[step_token], "log"))


def listing_step_order(run_dir: str) -> list[str]:
    """Return step tokens in flow.json order, with undiscovered extras alphabetically after."""
    step_dirs = discover_step_dirs(run_dir)
    if not step_dirs:
        return []

    flow_data = read_flow_json(run_dir)
    if isinstance(flow_data, dict):
        flow_tokens = [s.get("name", "") for s in _safe_steps(flow_data) if s.get("name")]
        flow_set = set(flow_tokens)
        result = [t for t in flow_tokens if t in step_dirs]
        result.extend(sorted(t for t in step_dirs if t not in flow_set))
        return result

    return sorted(step_dirs)


def resolve_workspace_path(workspace_arg, project, workspace_id, run_dir):
    """Return the managed workspace directory already selected by the context.

    ``--workspace`` is a project-local name, not an arbitrary filesystem path.
    The context resolves it through ``project.json`` before a handler reaches
    this helper, so no command may bypass the manifest with a raw directory.
    """
    _ = workspace_arg
    if not os.path.isdir(run_dir):
        return None, error_record(
            "missing_workspace",
            workspace=run_dir,
            run=disclosure_cmd("ecc run", project, workspace_id),
        )
    return run_dir, None


def resolve_command_workspace(workspace_arg, project, workspace_id, run_dir):
    """Load the workspace a command should operate on.

    The project workspace directory (`run_dir`) is already resolved by the
    command context. Wraps resolve_workspace_path with
    load_workspace, which appends a workspace log entry. Read-only commands
    must use resolve_workspace_path instead. Returns (workspace,
    error-record-or-None); the caller maps a non-None record to
    a CommandResult.err.
    """
    import inspect

    from chipcompiler.data import load_workspace

    path, error = resolve_workspace_path(workspace_arg, project, workspace_id, run_dir)
    if error is not None:
        return None, error
    assert path is not None
    try:
        load_kwargs = (
            {"read_only": True}
            if "read_only" in inspect.signature(load_workspace).parameters
            else {}
        )
        workspace = load_workspace(path, **load_kwargs)
    except Exception as exc:
        return None, error_record("invalid_workspace", workspace=path, reason=str(exc))
    if workspace is None:
        return None, error_record("invalid_workspace", workspace=path)
    return workspace, None


def resolve_loaded_workspace(command_input, ctx: CommandContext):
    """Resolve and load the workspace for handlers that need a Workspace.

    Returns (workspace, failure CommandResult-or-None). A malformed manifest
    is rejected first: silently falling through to ``<project>/default``
    would report against (and mutate) the wrong workspace.
    """
    if ctx.manifest_error:
        from chipcompiler.cli.core.records import error_record

        return None, CommandResult.err(
            [
                error_record(
                    ctx.manifest_error.split(":", 1)[0],
                    reason=ctx.manifest_error,
                )
            ]
        )
    workspace, error = resolve_command_workspace(
        command_input.workspace, ctx.project, ctx.run_id, ctx.run_dir
    )
    if error is not None:
        return None, CommandResult.err([error])
    return workspace, None


def workspace_display(command_input, ctx: CommandContext) -> str:
    """Human-facing managed workspace path."""
    return ctx.run_dir
