"""The one writer for the flow ledger (``home/flow.json``).

Every first-party write path goes through :func:`save_ledger`: it stamps the
schema version, serializes under a per-path re-entrant lock, and reports
failure instead of raising, so callers can restore their in-memory state. For
a workspace ledger it also resets steps built from upstream runs that changed,
writes each step's results into its step directory and stamps the digest of
those results (see ``chipcompiler.data.step.results``).
Recovery paths that deliberately do not load a Workspace (reconcile and
interrupted runs) keep a low-level writer and are listed in the regression
guard's allowlist.
"""

import logging
import threading
from contextlib import contextmanager
from copy import deepcopy
from typing import cast

from chipcompiler.data.schema_versions import SCHEMA_VERSION_FIELD
from chipcompiler.data.types import StateEnum
from chipcompiler.data.workspace.flow_data import FLOW_JSON_SCHEMA_VERSION
from chipcompiler.data.workspace.flow_types import (
    STEP_RESULTS_DIGEST_FIELD,
    FlowStepEntry,
    ledger_workspace_directory,
)

logger = logging.getLogger(__name__)

_VALID_TRANSITIONS: dict[str, set[str]] = {
    StateEnum.Unstart.value: {
        StateEnum.Ongoing.value,
        StateEnum.Imcomplete.value,
    },
    StateEnum.Pending.value: {
        StateEnum.Ongoing.value,
        StateEnum.Imcomplete.value,
    },
    StateEnum.Ongoing.value: {
        StateEnum.Success.value,
        StateEnum.Imcomplete.value,
        StateEnum.Invalid.value,
    },
    # Terminal states have no outgoing lifecycle transitions. Batch resets
    # (clear_flow_states, suffix invalidation) assign Unstart directly and
    # bypass this guard by design.
    StateEnum.Success.value: set(),
    StateEnum.Imcomplete.value: set(),
    StateEnum.Invalid.value: set(),
}

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


@contextmanager
def ledger_lock(flow):
    """Hold the shared per-path lock across a read-modify-write transaction."""
    path = flow.path
    if path is None:
        yield
        return
    with _lock_for(path):
        yield


def save_ledger(flow) -> bool:
    """Persist *flow* to disk with the current schema version.

    The in-process lock is shared by every writer of the same path, so two
    flows over one workspace serialize their writes the way one EngineFlow's
    instance lock used to. Each step's ``state.json`` is written before
    ``flow.json``; a failure restores both the files and memory.
    """
    if getattr(flow, "read_only", False):
        raise RuntimeError("flow ledger is read-only")

    from chipcompiler.data.step.results import (
        persist_step_results,
        restore_step_results,
        results_digest,
    )
    from chipcompiler.utility import json_write

    path = flow.path
    if path is None:
        return False
    with _lock_for(path):
        previous_document = {
            field: flow.data[field]
            for field in (SCHEMA_VERSION_FIELD, STEP_RESULTS_DIGEST_FIELD)
            if field in flow.data
        }
        steps = flow.data.get("steps", [])
        # A malformed ledger may hold non-object steps; they carry no results.
        records = cast("list[FlowStepEntry]", [step for step in steps if isinstance(step, dict)])
        workspace_directory = ledger_workspace_directory(path)
        reset = (
            [] if workspace_directory is None else _reset_stale_steps(workspace_directory, records)
        )
        flow.data[SCHEMA_VERSION_FIELD] = FLOW_JSON_SCHEMA_VERSION
        written: list = []
        try:
            if workspace_directory is not None:
                written = persist_step_results(workspace_directory, records)
                flow.data[STEP_RESULTS_DIGEST_FIELD] = results_digest(records)
            if json_write(path, deepcopy(flow.data)):
                return True
        except OSError:
            logger.exception("Failed to write the step results of %s", path)
        # Keep memory and disk describing the same document.
        restore_step_results(written)
        for field in (SCHEMA_VERSION_FIELD, STEP_RESULTS_DIGEST_FIELD):
            if field in previous_document:
                flow.data[field] = previous_document[field]
            else:
                flow.data.pop(field, None)
        for record, previous in reset:
            steps[next(index for index, step in enumerate(steps) if step is record)] = previous
        return False


def reset_step_record(record: FlowStepEntry) -> None:
    """Mark one ledger step Unstart, clearing the results of its last run."""
    record["state"] = StateEnum.Unstart.value
    record["runtime"] = ""
    record["peak memory (mb)"] = 0
    record.pop("resource_observation", None)


def _reset_stale_steps(
    workspace_directory, records: list[FlowStepEntry]
) -> list[tuple[FlowStepEntry, FlowStepEntry]]:
    """Reset Success steps built from upstream runs that changed since.

    Returns each reset record with its previous content.
    """
    from chipcompiler.data.handshake.stale import stale_steps
    from chipcompiler.data.step import recorded_step_directory

    directories: dict[str, FlowStepEntry] = {}
    for record in records:
        try:
            directories[recorded_step_directory(record)] = record
        except ValueError:
            continue
    reset = []
    for stale in stale_steps(workspace_directory, list(directories)):
        record = directories[stale.step_directory]
        if record.get("state") == StateEnum.Success.value:
            reset.append((record, deepcopy(record)))
            reset_step_record(record)
            logger.info(
                "[FLOW] %s is stale: built from changed upstream runs in %s",
                record.get("name"),
                ", ".join(
                    [changed.step_directory for changed in stale.changed_inputs]
                    + list(stale.stale_upstream)
                ),
            )
    return reset


def validate_transition(old_state: str | None, new_state: str, step_name: str, tool: str) -> None:
    """Raise ``ValueError`` on illegal lifecycle transitions.

    Applies only to :func:`set_flow_state`; batch resets bypass it by design.
    """
    if old_state is None or old_state == new_state:
        return
    allowed = _VALID_TRANSITIONS.get(old_state, set())
    if new_state not in allowed:
        raise ValueError(
            f"Illegal state transition for {step_name}/{tool}: "
            f"{old_state} → {new_state}. "
            f"Allowed transitions from {old_state}: {sorted(allowed) or 'none'}"
        )


def set_flow_state(
    flow,
    name: str,
    tool: str,
    state: str | StateEnum,
    runtime: str | None = None,
    peak_memory: float | None = None,
    *,
    clear_runtime_operation: bool = False,
    persist=None,
) -> bool:
    """Move one ledger step to *state*, rolling memory back if the save fails.

    ``persist`` overrides the writer (the engine passes its own ``save`` so
    callers can substitute persistence); it defaults to :func:`save_ledger`.
    """
    write = persist if persist is not None else (lambda: save_ledger(flow))
    state_value = state.value if isinstance(state, StateEnum) else state
    with ledger_lock(flow):
        steps = flow.data.get("steps", [])
        for index, step in enumerate(steps):
            if step.get("name") != name or step.get("tool") != tool:
                continue
            old_state = step.get("state")
            validate_transition(old_state, state_value, name, tool)
            previous_step = deepcopy(step)
            step["state"] = state_value
            if state_value in {StateEnum.Ongoing.value, StateEnum.Unstart.value}:
                step.pop("resource_observation", None)
            if runtime is not None:
                step["runtime"] = runtime
            if peak_memory is not None:
                step["peak memory (mb)"] = peak_memory
            if clear_runtime_operation:
                info = step.get("info", {})
                info.pop("runtime_operation", None)
                info.pop("execution", None)

            if flow.path is None:
                return True
            if not write():
                steps[index] = previous_step
                logger.error(
                    "Failed to persist flow state for %s/%s (state=%s)",
                    name,
                    tool,
                    state_value,
                )
                return False
            return True
    return False


def clear_flow_states(flow, *, persist=None) -> bool:
    """Reset every step to Unstart and persist once."""
    write = persist if persist is not None else (lambda: save_ledger(flow))
    with ledger_lock(flow):
        previous_data = deepcopy(flow.data)
        for step in flow.data.get("steps", []):
            reset_step_record(step)
        if write():
            return True
        flow.data = previous_data
        return False
