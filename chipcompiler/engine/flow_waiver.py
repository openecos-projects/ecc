"""Deliberate, auditable flow-step exceptions.

A skipped step is a step the run intentionally did not perform; it stays in
the ledger so its position and reason are preserved, but it no longer gates
downstream PNR steps. A checklist waiver acknowledges a blocked checker
result without rewriting the checklist: the underlying violation evidence
stays visible, while the flow gate is allowed to pass it.
"""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from chipcompiler.data import FlowStepCategory, SkippableStepEnum, StateEnum
from chipcompiler.data.workspace.flow_ledger import validate_transition
from chipcompiler.data.workspace.flow_policy import flow_category


def _step_record(flow, name: str) -> dict:
    for step in flow.steps():
        if step.get("name") == name:
            return step
    raise KeyError(f"flow step not found: {name}")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _persist(flow) -> bool:
    save = getattr(flow, "save", None)
    if callable(save):
        return bool(save())
    from chipcompiler.data.workspace.flow_ledger import save_ledger

    return save_ledger(flow)


def _persist_step_update(flow, step: dict, previous_step: dict, failure_message: str) -> None:
    try:
        persisted = _persist(flow)
    except Exception:
        step.clear()
        step.update(previous_step)
        raise
    if not persisted:
        step.clear()
        step.update(previous_step)
        raise RuntimeError(failure_message)


def mark_step_skipped(workspace: Any, name: str, reason: str) -> dict:
    """Persist *name* as deliberately Skipped with an audit reason."""
    if name not in {step.value for step in SkippableStepEnum}:
        raise ValueError(f"step is not skippable: {name}")
    if not reason.strip():
        raise ValueError("a skip reason is required")
    flow = workspace.flow
    step = _step_record(flow, name)
    validate_transition(
        step.get("state"),
        StateEnum.Skipped.value,
        name,
        str(step.get("tool") or ""),
    )
    previous_step = deepcopy(step)
    step["state"] = StateEnum.Skipped.value
    step["runtime"] = ""
    step["peak memory (mb)"] = 0
    step.pop("resource_observation", None)
    step.pop("checklist_waiver", None)
    info = step.get("info")
    if isinstance(info, dict):
        info.pop("runtime_operation", None)
        info.pop("execution", None)
    step.pop("checklist", None)
    step["checklist_status"] = {
        "status": "skipped",
        "blocked": False,
        "failed_items": [],
        "source": "home/flow.json",
    }
    step["skip_reason"] = reason
    step["skipped_at"] = _timestamp()
    _persist_step_update(flow, step, previous_step, f"failed to persist skipped state for {name}")
    return step


def waive_checklist(workspace: Any, name: str, reason: str) -> dict:
    """Allow a blocked checker to stop gating downstream steps.

    The checker's checklist projection is deliberately left untouched so the
    workspace still reports the underlying signoff violations.
    """
    if not reason.strip():
        raise ValueError("a waiver reason is required")
    flow = workspace.flow
    step = _step_record(flow, name)
    if flow_category(step) != FlowStepCategory.CHECKER:
        raise ValueError(f"only checker steps can be waived: {name}")
    previous_step = deepcopy(step)
    step["checklist_waiver"] = {"reason": reason, "created_at": _timestamp()}
    _persist_step_update(
        flow, step, previous_step, f"failed to persist checklist waiver for {name}"
    )
    return step
