"""Execute candidate rerun steps in an isolated worker process.

The ECC C++ tools (DREAMPlace, sizer) keep process-global state: config
singletons and the native log redirect. Two candidates executing inside one
rpc-server process overwrite each other's state and cross-write step logs,
leaving steps Incomplete. Running each candidate's step loop in its own
process restores isolation without touching chipcompiler.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from chipcompiler.runtime.workspace_api import RuntimeApiError

PAYLOAD_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
_RESULT_NAME = "candidate-worker.v1.json"
_POLL_SECONDS = 1.0

_ISOLATION_FLAG = "ECC_CANDIDATE_STEP_ISOLATION"


def _state_value(state) -> str:
    return getattr(state, "value", str(state))


class _MarkerObserver:
    """Persist the parent's runtime operation marker without RPC wiring."""

    def __init__(self, marker):
        self.runtime_operation = marker


def run_candidate_steps_isolated(flow, steps, *, observer) -> None:
    """Run the candidate step loop in a subprocess, preserving failure shape.

    Falls back to in-process execution when isolation is disabled (unit
    tests drive fake flows through the same loop) or when a worker process
    cannot start, matching the legacy behavior of frozen environments.
    """
    if os.environ.get(_ISOLATION_FLAG, "1") == "0":
        from .workspace_api import _run_candidate_step

        for step in steps:
            _run_candidate_step(flow, step, observer=observer)
        return

    candidate_root = Path(flow.workspace.directory)
    result_path = candidate_root / "analysis" / _RESULT_NAME
    payload = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "candidate_directory": str(candidate_root),
        "step_names": [str(step.name) for step in steps],
        "runtime_operation": getattr(observer, "runtime_operation", None),
        "result_path": str(result_path),
    }
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "agent.candidate_worker"],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdin=subprocess.PIPE,
        )
    except OSError as exc:
        print(
            f"[candidate-worker] isolated execution unavailable ({exc});"
            " running candidate steps in process",
            file=sys.stderr,
        )
        from .workspace_api import _run_candidate_step

        for step in steps:
            _run_candidate_step(flow, step, observer=observer)
        return

    process.stdin.write(json.dumps(payload).encode("utf-8"))
    process.stdin.close()
    step_by_name = {str(step.name): step for step in steps}
    emitted: set[str] = set()
    while process.poll() is None:
        _replay_step_started(result_path, step_by_name, observer, emitted)
        time.sleep(_POLL_SECONDS)
    _replay_step_started(result_path, step_by_name, observer, emitted)
    result = _read_result(result_path)
    if process.returncode != 0 or not isinstance(result, dict) or result.get("ok") is not True:
        error = (result or {}).get("error") or (
            f"candidate worker exited with code {process.returncode}"
        )
        raise RuntimeApiError("command_failed", str(error))


def _replay_step_started(result_path: Path, step_by_name, observer, emitted: set[str]) -> None:
    """Re-emit step.started for steps the worker picked up.

    The worker cannot reach the operation manager, so the parent replays
    start markers from the worker result to keep operation.current_step and
    the RPC event stream equivalent to in-process execution.
    """
    callback = getattr(observer, "on_step_started", None)
    if not callable(callback):
        return
    result = _read_result(result_path)
    if not isinstance(result, dict):
        return
    for entry in result.get("steps", []):
        name = entry.get("name")
        if entry.get("state") == "Ongoing" and name not in emitted and name in step_by_name:
            emitted.add(name)
            callback(step_by_name[name])


def _read_result(result_path: Path):
    try:
        return json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main() -> int:
    payload = json.loads(sys.stdin.read())
    result_path = Path(payload["result_path"])
    result = {"schema_version": RESULT_SCHEMA_VERSION, "ok": False, "steps": [], "error": None}

    def flush() -> None:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result), encoding="utf-8")

    try:
        import chipcompiler.data as data_api
        from chipcompiler.runtime.workspace_api import _init_db_engine_for_workspace_step

        from .workspace_api import build_agent_flow_for_workspace

        workspace = data_api.load_workspace(directory=payload["candidate_directory"])
        if workspace is None:
            raise RuntimeError("load workspace failed")
        flow = build_agent_flow_for_workspace(workspace, create_step_workspaces=False)
        # workspace_steps is populated by create_step_workspaces; dirs already
        # exist from the parent's prepare phase, so only config init is skipped.
        flow.create_step_workspaces(initialize_config=False)
        observer = _MarkerObserver(payload.get("runtime_operation"))
        for name in payload["step_names"]:
            step = flow.get_workspace_step(name)
            if step is None:
                raise RuntimeError(f"candidate step missing: {name}")
            _init_db_engine_for_workspace_step(flow, step)
            result["steps"].append({"name": name, "state": "Ongoing"})
            flush()
            state = _state_value(flow.run_step(step, rerun=True, observer=observer))
            result["steps"][-1]["state"] = state
            flush()
            if state != "Success":
                result["error"] = f"candidate rerun step {name} failed with state {state}"
                break
        else:
            result["ok"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    flush()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
