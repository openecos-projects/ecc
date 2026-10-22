"""The one writer for the flow ledger (``home/flow.json``).

Every first-party write path goes through :func:`save_ledger`: it stamps the
schema version, serializes under a per-path re-entrant lock, and reports
failure instead of raising, so callers can restore their in-memory state.
Recovery paths that deliberately do not load a Workspace (reconcile,
interrupted runs, filesystem migration) keep a low-level writer and are listed
in the regression guard's allowlist.
"""

import threading
from copy import deepcopy

from chipcompiler.data.schema_migrations import SCHEMA_VERSION_FIELD
from chipcompiler.data.workspace.flow_data import FLOW_JSON_SCHEMA_VERSION

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
        if isinstance(flow.data, dict):
            flow.data[SCHEMA_VERSION_FIELD] = FLOW_JSON_SCHEMA_VERSION
        return json_write(path, deepcopy(flow.data))
