import inspect
from dataclasses import dataclass
from typing import Any, Literal

from chipcompiler.data import StateEnum


@dataclass(frozen=True)
class ExecutionPlan:
    intent: Literal["run", "rerun"]
    step_id: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    succeeded: bool
    state: str
    step_id: str | None = None


def execute(flow: Any, plan: ExecutionPlan, *, event_sink: Any = None) -> ExecutionResult:
    if plan.intent not in {"run", "rerun"}:
        raise ValueError(f"unsupported execution intent: {plan.intent}")
    if event_sink is None and getattr(flow.workspace, "directory", None):
        event_sink = _EngineeringCommitSink(flow.workspace)
    rerun = plan.intent == "rerun"
    if plan.step_id is None:
        succeeded = bool(_invoke(flow.run_steps, rerun=rerun, observer=event_sink))
        return ExecutionResult(
            succeeded=succeeded,
            state=StateEnum.Success.value if succeeded else StateEnum.Imcomplete.value,
        )

    get_workspace_step = getattr(flow, "get_workspace_step", None)
    step = (
        get_workspace_step(plan.step_id)
        if callable(get_workspace_step)
        else next(
            (
                candidate
                for candidate in getattr(flow, "workspace_steps", [])
                if getattr(candidate, "name", None) == plan.step_id
            ),
            None,
        )
    )
    if step is None:
        raise ValueError(f"step not found: {plan.step_id}")
    state = _invoke(flow.run_step, step, rerun=rerun, observer=event_sink)
    return ExecutionResult(
        succeeded=state is StateEnum.Success,
        state=getattr(state, "value", str(state)),
        step_id=plan.step_id,
    )


class _EngineeringCommitSink:
    def __init__(self, workspace: Any):
        from chipcompiler.engine.snapshot import ensure_engineering_snapshot

        self.workspace = workspace
        self.snapshot = ensure_engineering_snapshot(workspace)

    def commit_step(self, _step: Any, state: Any, _error: str | None = None) -> None:
        from chipcompiler.engine.snapshot import commit_engineering_snapshot

        self.snapshot = commit_engineering_snapshot(
            self.workspace,
            workspace_id=self.snapshot["workspaceId"],
            cause=f"flow_step.{getattr(state, 'value', str(state)).lower()}",
        )


def _invoke(callback, *args, rerun: bool, observer: Any):
    parameters = inspect.signature(callback).parameters.values()
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )
    kwargs = {}
    names = {parameter.name for parameter in parameters}
    if accepts_kwargs or "rerun" in names:
        kwargs["rerun"] = rerun
    if observer is not None and (accepts_kwargs or "observer" in names):
        kwargs["observer"] = observer
    return callback(*args, **kwargs)
