"""Workspace-run orchestration behind `ecc run --workspace`.

Owns the worker-call construction, tool preflight, and outcome
reconciliation for `--resume`/`--from`/`--only` selections. The CLI handler
in project.py stays a thin dispatcher.
"""

import os
import shlex

from chipcompiler.cli.core.inputs import RunInput
from chipcompiler.cli.core.types import CommandContext, CommandResult


def _worker_binary_missing_error() -> str | None:
    from chipcompiler.runtime.worker_operation import _default_worker_argv

    argv = _default_worker_argv()
    if not os.path.isfile(argv[0]):
        return f"worker binary not found: {argv[0]}"
    # A non-executable file would pass an existence check and only blow up
    # in Popen — after the run directory or --overwrite target is gone.
    if not os.access(argv[0], os.X_OK):
        return f"worker binary is not executable: {argv[0]}"
    return None


def _read_flow_data(workspace_dir: str) -> dict | None:
    """Read home/flow.json, tolerating a missing or corrupt file."""
    from chipcompiler.cli.inspection.discovery import CORRUPT_FLOW_JSON, read_flow_json

    flow_data = read_flow_json(workspace_dir)
    if flow_data is None or flow_data is CORRUPT_FLOW_JSON:
        return None
    return flow_data


def _load_valid_steps(workspace_dir: str) -> set[tuple[str, str]] | None:
    flow_data = _read_flow_data(workspace_dir)
    if flow_data is None:
        return None
    return {
        (s["name"], s["tool"])
        for s in flow_data.get("steps", [])
        if isinstance(s, dict) and "name" in s and "tool" in s
    }


def _preflight_selected_tools(engine_flow, selected: list[str]) -> str | None:
    """Fail before any mutation if a selected step's tool is unavailable."""
    from chipcompiler.tools.eda import load_eda_module

    tools = {
        step["name"]: step.get("tool")
        for step in engine_flow.workspace.flow.data.get("steps", [])
        if isinstance(step, dict) and "name" in step
    }
    for name in selected:
        tool = tools.get(name)
        if not tool:
            continue
        try:
            if load_eda_module(tool, check_dependency=True) is None:
                return f"tool unavailable for step {name}: {tool}"
        except Exception as exc:
            # Dependency checks raise (e.g. yosys is_eda_exist) rather than
            # returning None; both shapes mean unavailable.
            return f"tool unavailable for step {name}: {tool} ({exc})"
        if tool == "sizer":
            from chipcompiler.tools.ecc_sizer import is_sizer_runtime_exist

            try:
                if not is_sizer_runtime_exist():
                    return f"sizer runtime incomplete for step {name}: missing src/sizer_os.tcl"
            except Exception as exc:
                return f"sizer runtime check failed for step {name}: {exc}"
    return None


def _make_run_operation(workspace_dir: str, *, on_output=None, on_step_event=None):
    """Build a RunOperation for a workspace with step-log archiving wired in."""
    from pathlib import Path

    from chipcompiler.runtime.log_stream import step_log_archive_resolver
    from chipcompiler.runtime.worker_operation import RunOperation

    return RunOperation(
        workspace_dir=Path(workspace_dir),
        flow_json_path=Path(workspace_dir) / "home" / "flow.json",
        log_path_resolver=step_log_archive_resolver(workspace_dir),
        on_output=on_output,
        on_step_event=on_step_event,
        valid_steps=_load_valid_steps(workspace_dir),
    )


def _run_worker_calls(workspace_dir: str, calls: list[tuple[str, dict]], **callbacks):
    """Execute an ordered RPC sequence through the workspace's worker.

    A missing worker binary is a structured failure, never a crash.
    """
    from chipcompiler.runtime.worker_operation import OperationResult

    missing = _worker_binary_missing_error()
    if missing is not None:
        return OperationResult(success=False, error=missing)

    op = _make_run_operation(workspace_dir, **callbacks)
    return op.run_sequence(calls)


def _run_flow_via_worker(workspace_dir: str, *, on_output=None, on_step_event=None):
    """Execute flow.run through an isolated worker process."""
    return _run_worker_calls(
        workspace_dir,
        [("flow.run", {"rerun": False})],
        on_output=on_output,
        on_step_event=on_step_event,
    )


def _run_workspace(command_input: RunInput, ctx: CommandContext) -> CommandResult:
    def error(kind: str, **fields) -> CommandResult:
        return CommandResult.err([{"kind": "error", "error": kind, **fields}])

    if ctx.project is not None or command_input.project.run_id is not None:
        return error("project_workspace_conflict")
    if command_input.overwrite:
        return error("overwrite_requires_project")
    if command_input.param_set:
        return error("set_requires_project")
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

    from chipcompiler.data import load_workspace
    from chipcompiler.engine import EngineFlow, rerun

    workspace_path = os.path.abspath(os.path.expanduser(command_input.workspace))
    try:
        workspace = load_workspace(workspace_path)
    except Exception as exc:
        return error("invalid_workspace", workspace=workspace_path, reason=str(exc))
    if workspace is None:
        return error("invalid_workspace", workspace=workspace_path)

    try:
        engine_flow = EngineFlow(workspace=workspace)
    except Exception as exc:
        return error("invalid_workspace", workspace=workspace_path, reason=str(exc))
    if not engine_flow.has_init():
        return error("missing_flow", workspace=workspace_path)

    try:
        selected = rerun.selected_step_names(
            engine_flow,
            from_step=command_input.from_step,
            only=command_input.only,
            force=command_input.force,
        )
    except ValueError as exc:
        return error("unknown_step", workspace=workspace_path, reason=str(exc))

    def no_op_result() -> CommandResult:
        return CommandResult.ok(
            [
                {
                    "run": "workspace",
                    "status": "success",
                    "workspace": workspace_path,
                    "executed_steps": [],
                    "no_op": True,
                }
            ]
        )

    if not selected:
        # --only on an already-successful step without --force, or --resume
        # with every step successful: nothing to execute.
        return no_op_result()

    # Preflight the whole selected suffix before anything is invalidated:
    # the first worker call resets and clears the suffix, so discovering an
    # unavailable tool mid-sequence would leave the workspace mutated.
    tool_error = _preflight_selected_tools(engine_flow, selected)
    if tool_error is not None:
        return error("config_error", workspace=workspace_path, reason=tool_error)

    target = selected[0]
    if command_input.only is not None:
        # An executed --only step always reruns with clean artifacts; the
        # --force distinction only gates whether a successful step qualifies.
        # Downstream steps keep their outputs but are marked Unstart.
        calls = [("flow.run_step", {"step": target, "rerun": True, "invalidate_dependents": True})]
    else:
        # --resume/--from run exactly the selected suffix, step by step. A
        # trailing unscoped flow.run would resume from the FIRST non-success
        # step — possibly before the --from boundary — so the suffix is
        # driven as explicit run_step calls instead.
        calls = [("flow.run_step", {"step": target, "rerun": True, "reset_dependents": True})]
        calls += [("flow.run_step", {"step": name, "rerun": True}) for name in selected[1:]]

    op_result = _run_worker_calls(workspace_path, calls)

    if op_result.success:
        return CommandResult.ok(
            [
                {
                    "run": "workspace",
                    "status": "success",
                    "workspace": workspace_path,
                    "executed_steps": list(selected),
                    "no_op": False,
                }
            ]
        )

    executed, failed_step = _workspace_run_outcome(selected, op_result.completed_calls)
    record = {
        "run": "workspace",
        "status": "failed",
        "workspace": workspace_path,
        "executed_steps": executed,
        "no_op": False,
        "resume_cmd": f"ecc run --workspace {shlex.quote(workspace_path)} --resume",
    }
    if failed_step is not None:
        record["failed_step"] = failed_step
    if op_result.error:
        record["error"] = op_result.error
    if op_result.exit_code is not None:
        record["exit_code"] = op_result.exit_code
    if op_result.repaired_steps:
        record["repaired_steps"] = op_result.repaired_steps
    return CommandResult.err([record])


def _workspace_run_outcome(
    selected: list[str], completed_calls: int
) -> tuple[list[str], str | None]:
    """Derive executed steps and the failed step from completed worker calls.

    Final flow.json states are not execution evidence: a worker that dies
    during startup leaves already-successful steps (`--from` on a succeeded
    suffix, `--only --force`) looking executed. A completed flow.run_step
    RPC implies its step succeeded, so the completed-call prefix is exactly
    what ran; the first step after it is the one whose call failed.
    """
    executed = selected[:completed_calls]
    failed_step = selected[completed_calls] if completed_calls < len(selected) else None
    return executed, failed_step
