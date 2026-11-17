"""The Flow Steps a Workspace parameter edit is scoped to and invalidates from."""

from typing import Any

from chipcompiler.data.step_parameters import is_step_scoped
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


def edit_scope(
    schema: Any,
    parameter: str,
    key_step: str | None,
    step: str | None,
    allowed: set[str] | None,
    seen: set[tuple[str | None, str]],
) -> str | None:
    """The step scope of one batch edit (``None`` for a workspace-wide value).

    *key_step* is the step named in the key (``placement:place.x``), *step* the
    batch's selected step with its *allowed* parameters. Rejects a step prefix
    on a workspace-wide parameter, an edit outside the selected step, and a
    second edit of the same stored value (tracked in *seen*).
    """
    if key_step is not None and not is_step_scoped(schema):
        raise WorkspaceLifecycleError(
            "parameter_not_applicable",
            f"{schema.param} is workspace-wide; drop the '{key_step}:' step prefix",
        )
    if allowed is not None and (
        schema.param not in allowed or (key_step is not None and key_step != step)
    ):
        raise WorkspaceLifecycleError(
            "parameter_not_applicable", f"Parameter {parameter} is not configurable at {step}"
        )
    scope = (key_step or step) if is_step_scoped(schema) else None
    if (scope, schema.param) in seen:
        raise WorkspaceLifecycleError(
            "conflicting_parameter_patch", "Parameters cannot be repeated or set and unset"
        )
    seen.add((scope, schema.param))
    return scope
