"""Workspace execution preferences owned by ``home/flow.json``."""

from copy import deepcopy

from .flow_ledger import save_ledger
from .flow_types import FlowDocument


def declared_step_subprocess(data: FlowDocument) -> bool | None:
    """Read an explicit choice, rejecting malformed saved preferences."""
    options = data.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("flow.options must be an object")
    execution = options.get("execution", {})
    if not isinstance(execution, dict):
        raise ValueError("flow.options.execution must be an object")
    if "step_subprocess" not in execution:
        return None
    value = execution["step_subprocess"]
    if not isinstance(value, bool):
        raise ValueError("flow.options.execution.step_subprocess must be a boolean")
    return value


def save_step_subprocess(flow, *, value: bool) -> None:
    """Persist one preference without changing steps or other option fields."""
    if not isinstance(value, bool):
        raise ValueError("step_subprocess must be a boolean")
    declared_step_subprocess(flow.data)
    previous = deepcopy(flow.data)
    options = flow.data.setdefault("options", {})
    execution = options.setdefault("execution", {})
    execution["step_subprocess"] = value
    if not save_ledger(flow):
        flow.data = previous
        raise OSError("Failed to persist workspace execution preferences")
