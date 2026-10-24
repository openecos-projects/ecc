"""The one writer for the flow ledger (``home/flow.json``).

Every first-party write path goes through :func:`save_ledger`: it stamps the
schema version, serializes under a per-path re-entrant lock, and reports
failure instead of raising, so callers can restore their in-memory state.
Recovery paths that deliberately do not load a Workspace (reconcile,
interrupted runs, filesystem migration) keep a low-level writer and are listed
in the regression guard's allowlist.
"""

import logging
import threading
from contextlib import contextmanager
from copy import deepcopy

from chipcompiler.data.schema_migrations import SCHEMA_VERSION_FIELD
from chipcompiler.data.types import StateEnum
from chipcompiler.data.workspace.flow_data import FLOW_JSON_SCHEMA_VERSION

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
    instance lock used to.
    """
    from chipcompiler.utility import json_write

    path = flow.path
    if path is None:
        return False
    with _lock_for(path):
        has_version = SCHEMA_VERSION_FIELD in flow.data
        previous_version = flow.data.get(SCHEMA_VERSION_FIELD)
        flow.data[SCHEMA_VERSION_FIELD] = FLOW_JSON_SCHEMA_VERSION
        if json_write(path, deepcopy(flow.data)):
            return True
        # Keep memory and disk describing the same document.
        if has_version and previous_version is not None:
            flow.data[SCHEMA_VERSION_FIELD] = previous_version
        else:
            flow.data.pop(SCHEMA_VERSION_FIELD, None)
        return False


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
            step["state"] = StateEnum.Unstart.value
            step["runtime"] = ""
            step["peak memory (mb)"] = 0
            step.pop("resource_observation", None)
        if write():
            return True
        flow.data = previous_data
        return False
