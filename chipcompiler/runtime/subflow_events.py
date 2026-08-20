from __future__ import annotations

from copy import deepcopy
from typing import Any

from chipcompiler.data import StateEnum
from chipcompiler.utility import json_write


def publish_subflow_stage(
    workspace: Any,
    workspace_step: Any,
    subflow_step: dict[str, Any],
) -> None:
    """Forward a saved inner-flow transition to the optional GUI observer.

    Tool implementations run below the engine layer, so the observer is stored
    only for the duration of one EngineFlow.run_step invocation. Keeping this
    bridge optional preserves CLI execution and tool failure semantics.
    """

    observer = getattr(workspace, "_runtime_flow_observer", None)
    callback = getattr(observer, "on_subflow_stage", None)
    if not callable(callback):
        return
    try:
        callback(workspace_step, dict(subflow_step))
    except (Exception, SystemExit):
        # GUI event delivery must not affect an EDA tool's result.
        return


def finalize_interrupted_subflow(
    workspace_step: Any,
    runtime: str,
    peak_memory_mb: float,
) -> list[dict[str, Any]]:
    subflow = getattr(workspace_step, "subflow", None)
    steps = getattr(subflow, "steps", None) or []
    previous_steps = deepcopy(steps)
    interrupted = []
    for step in steps:
        if step.get("state") != "Ongoing":
            continue
        step["state"] = StateEnum.Imcomplete.value
        step["runtime"] = runtime
        step["peak memory (mb)"] = peak_memory_mb
        interrupted.append(dict(step))
    path = getattr(subflow, "path", None)
    if interrupted and path and not json_write(path, {"path": str(path), "steps": steps}):
        for step, previous_step in zip(steps, previous_steps, strict=True):
            step.clear()
            step.update(previous_step)
        raise OSError(f"failed to save interrupted subflow: {path}")
    return interrupted
