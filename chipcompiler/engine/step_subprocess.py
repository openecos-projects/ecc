"""Run a single flow step's tool execution in an isolated worker process.

The worker rebuilds the workspace from disk, initializes the native DB engine
for the one step, and invokes ``chipcompiler.tools.run_step`` with its stdio
captured to the step log. The parent process keeps ownership of the flow
ledger (flow.json) and all observer notifications; the worker only reports
subflow stage events and its final outcome through a result file.

Motivation mirrors ``agent/candidate_worker.py``: the native EDA tools keep
process-global state (config singletons, native log redirect), so running
every step in one process lets them pollute each other and the parent's
stdio (``utility/log.py`` dup2 capture).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.engine.step_execution import (
    StepExecutionResult,
    _prepare_log_file,
    get_process_rss_mb,
)

logger = logging.getLogger(__name__)

PAYLOAD_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
_RESULT_NAME = "step-worker.v1.json"
_POLL_SECONDS = 1.0
_TERMINATE_TIMEOUT_SECONDS = 5.0

_ENABLED_ENV = "ECC_STEP_SUBPROCESS"


def is_enabled() -> bool:
    """Subprocess execution is the default; ECC_STEP_SUBPROCESS=0 opts out.

    Frozen builds have no interpreter to spawn for ``python -m`` and fall
    back to in-process execution.
    """
    if os.environ.get(_ENABLED_ENV, "1") == "0":
        return False
    if getattr(sys, "frozen", False):
        logger.warning(
            "step subprocess execution is not available in frozen builds; "
            "running this step in process (set %s=0 to silence this warning)",
            _ENABLED_ENV,
        )
        return False
    return True


def execute_step_subprocess(
    workspace: Workspace,
    workspace_step: WorkspaceStep,
    *,
    observer=None,
    started_at: float | None = None,
) -> StepExecutionResult:
    """Run one step's tool in a worker process and report its outcome.

    Never raises: failures are returned as ``StepExecutionResult.error`` so
    the surrounding ledger logic sees the same shape as in-process execution.
    """
    start_time = time.time() if started_at is None else started_at
    step_tag = f"{workspace_step.name}({workspace_step.tool})"
    log_file = _prepare_log_file(workspace_step)
    result_path = Path(os.path.dirname(log_file) or ".") / _RESULT_NAME
    payload = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "workspace_directory": str(workspace.directory),
        "step_name": str(workspace_step.name),
        "tool": str(workspace_step.tool),
        "result_path": str(result_path),
        "parent_pid": os.getpid(),
    }

    try:
        if log_file:
            with open(log_file, "ab") as log_handle:
                process = _spawn_worker(log_handle)
        else:
            process = _spawn_worker(None)
    except OSError as exc:
        return _result(start_time, 0.0, error=f"{step_tag} worker failed to start: {exc}")

    workspace.logger.info(
        "[STEP] %s pid=%s worker started", step_tag, process.pid
    )
    process.stdin.write(json.dumps(payload).encode("utf-8"))
    process.stdin.close()

    start_memory_mb = get_process_rss_mb(process.pid)
    peak_memory_mb = start_memory_mb
    step_error = None
    emitted = 0
    try:
        while process.poll() is None:
            cancel_error = _cancel_error(observer)
            if cancel_error is not None:
                step_error = f"{step_tag} cancelled: {cancel_error}"
                break
            peak_memory_mb = max(peak_memory_mb, get_process_rss_mb(process.pid))
            emitted = _replay_events(result_path, workspace_step, observer, emitted)
            time.sleep(_POLL_SECONDS)
        peak_memory_mb = max(peak_memory_mb, get_process_rss_mb(process.pid))
        emitted = _replay_events(result_path, workspace_step, observer, emitted)
    finally:
        _terminate_worker(process)

    result = _read_result(result_path)
    if step_error is None:
        if not isinstance(result, dict) or result.get("done") is not True:
            step_error = f"{step_tag} worker exited with code {process.returncode}."
        elif result.get("ok") is not True:
            step_error = f"{step_tag} worker reported failure: {result.get('error')}"
    return _result(start_time, peak_memory_mb - start_memory_mb, error=step_error)


def _spawn_worker(log_handle) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "chipcompiler.engine.step_subprocess"],
        stdin=subprocess.PIPE,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )


def _result(start_time: float, peak_memory_mb: float, *, error: str | None) -> StepExecutionResult:
    peak_memory_mb = 0 if peak_memory_mb < 0 else round(peak_memory_mb, 3)
    elapsed = time.time() - start_time
    return StepExecutionResult(
        error=error,
        elapsed_seconds=elapsed,
        peak_memory_mb=peak_memory_mb,
        runtime=f"{int(elapsed // 3600)}:{int((elapsed % 3600) // 60)}:{int(elapsed % 60)}",
    )


def _cancel_error(observer) -> str | None:
    callback = getattr(observer, "raise_if_cancelled", None)
    if not callable(callback):
        return None
    try:
        callback()
    except (Exception, SystemExit) as exc:
        return str(exc) or type(exc).__name__
    return None


def _terminate_worker(process: subprocess.Popen) -> None:
    """Reap a worker left running by cancellation or an observer failure."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _replay_events(result_path: Path, workspace_step: WorkspaceStep, observer, emitted: int) -> int:
    """Deliver worker-side subflow stage events to the parent observer."""
    callback = getattr(observer, "on_subflow_stage", None)
    result = _read_result(result_path)
    if not callable(callback) or not isinstance(result, dict):
        return emitted
    events = result.get("events")
    if not isinstance(events, list):
        return emitted
    for event in events[emitted:]:
        if isinstance(event, dict) and event.get("type") == "subflow_stage":
            callback(workspace_step, dict(event.get("subflow_step") or {}))
    return len(events)


def _read_result(result_path: Path):
    try:
        return json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class _ResultFileObserver:
    """Persist subflow stage events from tool code into the worker result."""

    def __init__(self, result: dict, flush):
        self._result = result
        self._flush = flush

    def on_subflow_stage(self, _step, subflow_step) -> None:
        self._result["events"].append(
            {"type": "subflow_stage", "subflow_step": dict(subflow_step)}
        )
        self._flush()


def _arm_parent_death_signal(parent_pid: int) -> None:
    import ctypes

    # A caller can be killed without running its Python cleanup.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def main() -> int:
    payload = json.loads(sys.stdin.read())
    if sys.platform == "linux":
        _arm_parent_death_signal(payload["parent_pid"])
    result_path = Path(payload["result_path"])
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "ok": False,
        "done": False,
        "error": None,
        "events": [],
    }

    def flush() -> None:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result), encoding="utf-8")

    try:
        import chipcompiler.data as data_api
        from chipcompiler.engine.flow import EngineFlow

        workspace = data_api.load_workspace(directory=payload["workspace_directory"])
        if workspace is None:
            raise RuntimeError("load workspace failed")
        flow = EngineFlow(workspace)
        # Directories and configs already exist from the parent's flow setup;
        # eda.run_step refreshes the step config on every run.
        flow.create_step_workspaces(initialize_config=False)
        step = flow.get_workspace_step(payload["step_name"])
        if step is None or step.tool != payload["tool"]:
            raise RuntimeError(
                f"step {payload['step_name']}({payload['tool']}) missing in worker"
            )
        workspace._runtime_flow_observer = _ResultFileObserver(result, flush)

        flow.init_db_engine_for_step(step)
        initialization_error = getattr(flow.engine_db, "initialization_error", None)
        if initialization_error is not None:
            raise initialization_error

        from chipcompiler.utility.log import capture_stdio_to_file

        with capture_stdio_to_file(step.log.file):
            from chipcompiler.tools import run_step

            ok = run_step(workspace=workspace, step=step, ecc_module=flow.engine_db.engine)
        result["ok"] = bool(ok)
        if not ok:
            result["error"] = f"step {payload['step_name']} reported failure"
    except (Exception, SystemExit) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["done"] = True
    flush()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
