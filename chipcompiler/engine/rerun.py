#!/usr/bin/env python
"""Re-execution of persisted flow steps in an existing workspace.

Selection primitives behind ``ecc run --workspace``: resume from the first
non-successful step, re-execute a step and its persisted suffix, or run
exactly one step. Everything here drives an ``EngineFlow`` that was loaded
from an existing workspace; execution itself stays in ``EngineFlow.run_step``.
"""

import os
import shutil
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from chipcompiler.data import StateEnum, Workspace, WorkspaceStep, log_flow
from chipcompiler.utility.log import redirect_stdio_to_file
from chipcompiler.utility.path import path_is_within

if TYPE_CHECKING:
    from chipcompiler.engine.flow import EngineFlow


class StepRunResult(NamedTuple):
    ok: bool
    executed: tuple[str, ...]
    failed: str | None = None


def selected_step_names(
    flow: "EngineFlow", *, from_step: str = None, only: str = None, force: bool = False
) -> list[str]:
    """Resolve a run selector to the persisted step names it would execute."""
    steps = flow.workspace.flow.data.get("steps", [])
    if only is not None:
        index = _require_step_index(flow, only)
        if not force and steps[index].get("state") == StateEnum.Success.value:
            return []
        return [steps[index]["name"]]
    if from_step is not None:
        return [step["name"] for step in steps[_require_step_index(flow, from_step) :]]
    for index, step in enumerate(steps):
        if step.get("state") != StateEnum.Success.value:
            return [step["name"] for step in steps[index:]]
    return []


def run_resume(flow: "EngineFlow") -> StepRunResult:
    """Resume from the first non-successful step, re-executing the persisted suffix."""
    for step in flow.workspace.flow.data.get("steps", []):
        if step.get("state") != StateEnum.Success.value:
            return run_from(flow, step["name"])
    return StepRunResult(ok=True, executed=())


def run_from(flow: "EngineFlow", name: str) -> StepRunResult:
    """Re-execute the named step and every following step in persisted order."""
    steps = flow.workspace.flow.data.get("steps", [])
    index = _require_step_index(flow, name)
    _require_steps_available(flow, len(steps) - 1)
    suffix = flow.workspace_steps[index:]
    output_dirs = _validated_output_dirs(flow.workspace, suffix)
    _invalidate_suffix(flow, index)
    return _run_selected(flow, list(zip(suffix, output_dirs, strict=True)))


def run_only(flow: "EngineFlow", name: str, *, force: bool = False) -> StepRunResult:
    """Run exactly one persisted step; a successful step is re-run only with force."""
    steps = flow.workspace.flow.data.get("steps", [])
    index = _require_step_index(flow, name)
    if not force and steps[index].get("state") == StateEnum.Success.value:
        return StepRunResult(ok=True, executed=())
    _require_steps_available(flow, index)
    workspace_step = flow.get_workspace_step(name)
    (output_dir,) = _validated_output_dirs(flow.workspace, [workspace_step])
    _invalidate_suffix(flow, index)
    return _run_selected(flow, [(workspace_step, output_dir)])


def _require_step_index(flow: "EngineFlow", name: str) -> int:
    steps = flow.workspace.flow.data.get("steps", [])
    for index, step in enumerate(steps):
        if step.get("name") == name:
            return index
    available = ", ".join(str(step.get("name")) for step in steps)
    raise ValueError(f"unknown step '{name}'; available steps: {available}")


def _require_steps_available(flow: "EngineFlow", last_index: int) -> None:
    """Require flow steps up to last_index to align 1:1 with workspace_steps.

    The input chain of a step is built from its predecessor's outputs, so a
    step that failed to create (e.g. missing tool) silently shifts the
    inputs of every following step.
    """
    created = [step.name for step in flow.workspace_steps]
    for index, step in enumerate(flow.workspace.flow.data.get("steps", [])[: last_index + 1]):
        if index >= len(created) or created[index] != step["name"]:
            raise ValueError(f"step is unavailable in this workspace: {step['name']}")


def _invalidate_suffix(flow: "EngineFlow", index: int) -> None:
    """Mark the steps from index on as Unstart, persisted before any deletion."""
    steps = flow.workspace.flow.data.get("steps", [])
    for step in steps[index:]:
        step["state"] = StateEnum.Unstart.value
        step["runtime"] = ""
        step["peak memory (mb)"] = 0
    if not flow.save():
        raise ValueError("failed to persist step invalidation; refusing to modify outputs")


def _run_selected(flow: "EngineFlow", selected: list[tuple[WorkspaceStep, Path]]) -> StepRunResult:
    """Run the selected steps in order, each with a fresh output directory."""
    # a new selection must not inherit a DB positioned by an earlier run
    if flow.engine_db is not None:
        flow.engine_db.close()

    executed = []
    for workspace_step, output_dir in selected:
        flow.workspace.logger.log_section(
            f"{workspace_step.tool} - begin step - {workspace_step.name}"
        )
        _reset_output_dir(output_dir)
        _redirect_to_step_log(workspace_step)
        flow.init_db_engine_for_step(workspace_step)
        state = flow.run_step(workspace_step, rerun=True)
        log_flow(workspace=flow.workspace)
        flow.workspace.logger.log_section(
            f"{workspace_step.tool} - end step - {workspace_step.name}"
        )
        if state != StateEnum.Success:
            return StepRunResult(ok=False, executed=tuple(executed), failed=workspace_step.name)
        executed.append(workspace_step.name)
    return StepRunResult(ok=True, executed=tuple(executed))


def _validated_output_dirs(workspace: Workspace, steps: list[WorkspaceStep]) -> list[Path]:
    """Validate that each step output is its canonical ``<step_dir>/output`` dir.

    All targets are validated before any deletion or state change happens.
    """
    root = Path(workspace.directory).resolve()
    output_dirs = []
    for step in steps:
        step_directory = getattr(step, "directory", None)
        output_dir = getattr(step.output, "dir", None)
        if not step_directory or not output_dir:
            raise ValueError(f"step output directory is missing: {step.name}")
        step_directory = Path(step_directory)
        output_dir = Path(output_dir)
        if step_directory.is_symlink() or output_dir.is_symlink():
            raise ValueError(f"step output must not be a symlink: {output_dir}")
        resolved = output_dir.resolve()
        if (
            resolved == root
            or not path_is_within(resolved, root)
            or resolved != step_directory.resolve() / "output"
        ):
            raise ValueError(
                f"step output is not the canonical workspace output directory: {output_dir}"
            )
        output_dirs.append(resolved)
    return output_dirs


def _redirect_to_step_log(workspace_step: WorkspaceStep) -> None:
    """Redirect stdio before DB init so its warnings land in the step log."""
    log_file = workspace_step.log.file or ""
    if not log_file:
        return
    log_file = os.path.abspath(log_file)
    try:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        redirect_stdio_to_file(log_file)
    except Exception:
        traceback.print_exc()


def _reset_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
