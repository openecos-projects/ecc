import inspect
from dataclasses import dataclass
from typing import Any, Literal

from chipcompiler.data import StateEnum, is_finished_step_state


@dataclass(frozen=True)
class ExecutionPlan:
    intent: Literal["run", "rerun"]
    step_id: str | None = None
    step_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionResult:
    succeeded: bool
    state: str
    step_id: str | None = None
    executed_steps: tuple[str, ...] = ()
    failed_step: str | None = None
    no_op: bool = False


def execute(flow: Any, plan: ExecutionPlan, *, event_sink: Any = None) -> ExecutionResult:
    if plan.intent not in {"run", "rerun"}:
        raise ValueError(f"unsupported execution intent: {plan.intent}")
    selected_ids = tuple(plan.step_ids)
    if plan.step_id is not None:
        if selected_ids:
            raise ValueError("ExecutionPlan cannot set both step_id and step_ids")
        selected_ids = (plan.step_id,)
    if plan.intent == "run" and not selected_ids and _is_completed(flow):
        return ExecutionResult(
            succeeded=True,
            state=StateEnum.Success.value,
            executed_steps=(),
            no_op=True,
        )
    workspace = getattr(flow, "workspace", None)
    if event_sink is None:
        event_sink = event_sink_for_workspace(workspace)
    rerun = plan.intent == "rerun"
    observer = execution_observer(event_sink)
    if not selected_ids:
        succeeded = bool(_invoke(flow.run_steps, rerun=rerun, observer=observer))
    else:
        succeeded = True
        for step_id in selected_ids:
            observer.raise_if_cancelled()
            step = _find_step(flow, step_id)
            if step is None:
                raise ValueError(f"step not found: {step_id}")
            state = _invoke(flow.run_step, step, rerun=rerun, observer=observer)
            if (
                state is not StateEnum.Success
                and getattr(state, "value", state) != StateEnum.Success.value
            ):
                succeeded = False
                break
    executed_steps = tuple(getattr(observer, "executed_steps", ()))
    failed_step = getattr(observer, "failed_step", None)
    state = StateEnum.Success.value if succeeded else StateEnum.Imcomplete.value
    return ExecutionResult(
        succeeded=succeeded,
        state=state,
        step_id=selected_ids[0] if len(selected_ids) == 1 else None,
        executed_steps=executed_steps,
        failed_step=failed_step,
    )


def _find_step(flow: Any, step_id: str) -> Any | None:
    get_workspace_step = getattr(flow, "get_workspace_step", None)
    if callable(get_workspace_step):
        return get_workspace_step(step_id)
    return next(
        (
            candidate
            for candidate in getattr(flow, "workspace_steps", [])
            if getattr(candidate, "name", None) == step_id
        ),
        None,
    )


def _is_completed(flow: Any) -> bool:
    data = getattr(getattr(getattr(flow, "workspace", None), "flow", None), "data", {})
    steps = data.get("steps", []) if isinstance(data, dict) else []
    return bool(steps) and all(
        isinstance(step, dict) and is_finished_step_state(step.get("state")) for step in steps
    )


class ExecutionObserver:
    def __init__(self, delegate: Any):
        self.delegate = delegate
        self.fatal_observer = bool(getattr(delegate, "fatal_observer", False))
        self.executed_steps: list[str] = []
        self.failed_step: str | None = None

    def on_step_completed(self, step: Any, state: Any, error: str | None = None) -> None:
        name = getattr(step, "name", None)
        if isinstance(name, str) and name:
            if getattr(state, "value", state) == StateEnum.Success.value:
                self.executed_steps.append(name)
            elif self.failed_step is None:
                self.failed_step = name
        self._delegate_call("on_step_completed", step, state, error)

    @property
    def runtime_operation(self):
        return getattr(self.delegate, "runtime_operation", None)

    def raise_if_cancelled(self) -> None:
        self._delegate_call("raise_if_cancelled")

    def on_step_started(self, step: Any) -> None:
        self._delegate_call("on_step_started", step)

    def on_step_skipped(self, step: Any) -> None:
        self._delegate_call("on_step_skipped", step)

    def on_subflow_stage(self, step: Any, subflow_step: Any) -> None:
        self._delegate_call("on_subflow_stage", step, subflow_step)

    def on_step_diagnostic(self, step: Any, diagnostic: dict[str, Any]) -> None:
        self._delegate_call("on_step_diagnostic", step, diagnostic)

    def on_rerun_prepared(self, *args, **kwargs) -> None:
        self._delegate_call("on_rerun_prepared", *args, **kwargs)

    def wait_for_step_rendered(self, step: Any, state: Any) -> bool:
        result = self._delegate_call("wait_for_step_rendered", step, state)
        return True if result is None else bool(result)

    def _delegate_call(self, name: str, *args, **kwargs):
        callback = getattr(self.delegate, name, None)
        if callable(callback):
            return callback(*args, **kwargs)
        return None


class _EngineeringCommitSink:
    fatal_observer = True

    def __init__(self, workspace: Any):
        from chipcompiler.engine.snapshot import ensure_engineering_snapshot

        self.workspace = workspace
        self.snapshot = ensure_engineering_snapshot(workspace)

    def on_step_completed(self, _step: Any, state: Any, _error: str | None = None) -> None:
        from chipcompiler.engine.snapshot import commit_engineering_snapshot

        self.snapshot = commit_engineering_snapshot(
            self.workspace,
            workspace_id=self.snapshot["workspaceId"],
            cause=f"flow_step.{getattr(state, 'value', str(state)).lower()}",
        )


def event_sink_for_workspace(workspace: Any) -> _EngineeringCommitSink | None:
    if getattr(workspace, "directory", None):
        return _EngineeringCommitSink(workspace)
    return None


def execution_observer(event_sink: Any) -> ExecutionObserver:
    return ExecutionObserver(event_sink)


def invoke_engine(callback, *args, rerun: bool = False, observer: Any = None):
    return _invoke(callback, *args, rerun=rerun, observer=observer)


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
