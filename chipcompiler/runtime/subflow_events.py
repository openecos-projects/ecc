from __future__ import annotations

from typing import Any


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
    except Exception:
        # GUI event delivery must not affect an EDA tool's result.
        return
