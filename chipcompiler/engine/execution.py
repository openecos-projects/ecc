import inspect
from dataclasses import dataclass
from typing import Any, Literal

from chipcompiler.data import StateEnum, is_finished_step_state
from chipcompiler.engine.observers import event_sink_for_workspace, execution_observer


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
    _notify_execution(event_sink, "on_execution_started", plan.intent, selected_ids)
    try:
        if not selected_ids:
            succeeded = bool(_invoke(flow.run_steps, rerun=rerun, observer=observer))
        else:
            steps = []
            for step_id in selected_ids:
                step = _find_step(flow, step_id)
                if step is None:
                    raise ValueError(f"step not found: {step_id}")
                steps.append(step)
            # The flow groups the selection into analysis waves and runs it.
            succeeded = bool(flow.run_steps(steps=steps, rerun=rerun, observer=observer))
    except BaseException as exc:
        _notify_execution(event_sink, "on_execution_finished", "interrupted", str(exc))
        raise
    # Steps of a parallel wave complete in any order; report them in flow order.
    order = selected_ids or tuple(
        getattr(step, "name", None) for step in getattr(flow, "workspace_steps", ())
    )
    rank = {step_id: position for position, step_id in enumerate(order)}

    def in_flow_order(names) -> tuple[str, ...]:
        return tuple(sorted(names, key=lambda name: rank.get(name, len(rank))))

    executed_steps = in_flow_order(getattr(observer, "executed_steps", ()))
    failed_steps = () if succeeded else in_flow_order(getattr(observer, "failed_steps", ()))
    failed_step = failed_steps[0] if failed_steps else None
    state = StateEnum.Success.value if succeeded else StateEnum.Imcomplete.value
    result = ExecutionResult(
        succeeded=succeeded,
        state=state,
        step_id=selected_ids[0] if len(selected_ids) == 1 else None,
        executed_steps=executed_steps,
        failed_step=failed_step,
    )
    _notify_execution(event_sink, "on_execution_finished", result.state, None)
    return result


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


def _notify_execution(event_sink: Any, method: str, *args) -> None:
    callback = getattr(event_sink, method, None)
    if not callable(callback):
        return
    try:
        callback(*args)
    except (Exception, SystemExit):
        if getattr(event_sink, "fatal_observer", False):
            raise


def _is_completed(flow: Any) -> bool:
    data = getattr(getattr(getattr(flow, "workspace", None), "flow", None), "data", {})
    steps = data.get("steps", []) if isinstance(data, dict) else []
    return bool(steps) and all(
        isinstance(step, dict) and is_finished_step_state(step.get("state")) for step in steps
    )


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
