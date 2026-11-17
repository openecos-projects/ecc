"""The Flow Steps a Workspace parameter edit is scoped to and invalidates from."""

from typing import Any

from chipcompiler.params import list_schemas

from .workspace_lifecycle import WorkspaceLifecycleError


def step_catalog(workspace: Any, step_id: str):
    """``(step, schemas)``: the parameters the per-step view of *step_id* lists."""
    identity = str(step_id)
    steps = [str(step.get("name", "")) for step in workspace.flow.steps() if step.get("name")]
    step = next(
        (candidate for candidate in steps if str(candidate) == identity),
        None,
    )
    if step is None:
        raise WorkspaceLifecycleError("unknown_flow_step", f"Flow Step not found: {step_id}")
    first = str(steps[0])
    schemas = tuple(
        schema
        for schema in list_schemas()
        if schema.pdk_target is None and schema.listed_at(identity, first)
    )
    return step, schemas


def earliest_flow_step(workspace: Any, affected_steps: list[str]) -> str:
    """The first Flow Step among *affected_steps*, in flow order."""
    identities = {str(step) for step in affected_steps}
    for step in workspace.flow.steps():
        name = str(step.get("name", ""))
        if name in identities:
            return name
    raise WorkspaceLifecycleError(
        "parameter_not_in_flow", "No affected parameter step exists in this Workspace flow"
    )


def require_flow_step(workspace: Any, parameter: str, step: str, *, step_value: bool) -> None:
    """Every parameter of a batch must reach a step of this Workspace's flow."""
    if any(str(item.get("name", "")) == str(step) for item in workspace.flow.steps()):
        return
    if step_value:
        raise WorkspaceLifecycleError(
            "unknown_flow_step", f"Flow Step of {parameter} not in this Workspace flow: {step}"
        )
    raise WorkspaceLifecycleError(
        "parameter_not_in_flow", f"No step of {parameter} exists in this Workspace flow"
    )
