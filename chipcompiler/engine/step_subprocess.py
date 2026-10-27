"""Run one flow step's native tool execution in a one-shot worker process."""

import logging
import os
import time
from functools import partial
from pathlib import Path

from chipcompiler.data import EccOutput, StepEnum, Workspace, WorkspaceStep, is_sta_step
from chipcompiler.engine import worker
from chipcompiler.engine.resource_observation import new_attempt_id, start_observation
from chipcompiler.engine.step_execution import (
    STEP_WORKER_MODULE,
    StepExecutionResult,
    _prepare_log_file,
    get_process_rss_mb,
)

logger = logging.getLogger(__name__)

PAYLOAD_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
_RESULT_NAME = "step-worker.v1.json"


def execute_step_subprocess(
    workspace: Workspace,
    workspace_step: WorkspaceStep,
    *,
    observer=None,
    started_at: float | None = None,
    worker_module: str = STEP_WORKER_MODULE,
    layout_image: bool = True,
) -> StepExecutionResult:
    start_time = time.time() if started_at is None else started_at
    step_tag = f"{workspace_step.name}({workspace_step.tool})"
    log_file = _prepare_log_file(workspace_step)
    result_path = Path(os.path.dirname(log_file) or ".") / _RESULT_NAME
    attempt_id = new_attempt_id()
    payload = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "workspace_directory": str(workspace.directory),
        "step_name": str(workspace_step.name),
        "tool": str(workspace_step.tool),
        "attempt_id": attempt_id,
        "layout_image": layout_image,
    }

    try:
        if log_file:
            with open(log_file, "ab") as log_handle:
                process = worker.spawn(
                    worker_module, payload, result_path=result_path, stdout=log_handle
                )
        else:
            process = worker.spawn(worker_module, payload, result_path=result_path, stdout=None)
    except (OSError, RuntimeError) as exc:
        return _result(start_time, 0.0, error=f"{step_tag} worker failed to start: {exc}")

    resource_observation = None
    resources = None
    start_memory_mb = 0.0
    peak_memory_mb = 0.0
    step_error = None
    cancel_error = None
    emitted = 0
    returncode = None
    try:
        workspace.logger.info("[STEP] %s pid=%s worker started", step_tag, process.pid)
        memory_reader = get_process_rss_mb
        if is_sta_step(workspace_step):
            from chipcompiler.tools.ecc.sta_parallel import get_sta_process_rss_mb

            memory_reader = get_sta_process_rss_mb
        start_memory_mb = memory_reader(process.pid)
        peak_memory_mb = start_memory_mb
        resources = start_observation(
            process.pid,
            attempt_id=attempt_id,
            isolated=True,
            step=workspace_step.name,
            tool=workspace_step.tool,
        )

        def on_poll(result: dict | None) -> None:
            nonlocal emitted, peak_memory_mb
            peak_memory_mb = max(peak_memory_mb, memory_reader(process.pid))
            emitted = _replay_events(result, workspace_step, observer, emitted, attempt_id)

        def cancel() -> None:
            nonlocal cancel_error
            callback = getattr(observer, "raise_if_cancelled", None)
            if not callable(callback):
                return
            try:
                callback()
            except (Exception, SystemExit) as exc:
                cancel_error = exc
                raise

        try:
            returncode = worker.poll_until_exit(
                process, result_path=result_path, on_poll=on_poll, cancel=cancel
            )
        except (Exception, SystemExit) as exc:
            if cancel_error is not exc:
                raise
            on_poll(worker.read_result(result_path))
            step_error = f"{step_tag} cancelled: {str(exc) or type(exc).__name__}"
    finally:
        try:
            if resources is not None:
                resource_observation = resources.finish()
        finally:
            worker.terminate_process_group(process)

    result = worker.read_result(result_path)
    if step_error is None:
        if not isinstance(result, dict):
            step_error = f"{step_tag} worker exited with code {returncode}."
        elif result.get("attempt_id") != attempt_id:
            if returncode != 0:
                step_error = f"{step_tag} worker exited with code {returncode}."
            else:
                step_error = f"{step_tag} worker result has a mismatched attempt id."
        elif result.get("done") is not True:
            step_error = f"{step_tag} worker exited with code {returncode}."
        elif result.get("ok") is not True:
            step_error = f"{step_tag} worker reported failure: {result.get('error')}"
        elif returncode != 0:
            step_error = f"{step_tag} worker exited with code {returncode}."
    if (
        isinstance(result, dict)
        and result.get("attempt_id") == attempt_id
        and result.get("done") is True
        and workspace_step.name == StepEnum.RCX.value
        and "rcx_spef" in result
        and cancel_error is None
        and (step_error is None or result.get("ok") is False)
    ):
        rcx_error = _restore_rcx_outputs(workspace_step, result)
        if rcx_error is not None:
            step_error = rcx_error
    if (
        isinstance(result, dict)
        and result.get("attempt_id") == attempt_id
        and result.get("done") is True
    ):
        try:
            from chipcompiler.data.parameter import load_parameter, parameters_have_chip_identity

            parameter_path = workspace.parameters.path
            if parameter_path is None:
                raise ValueError("worker parameter path is missing")
            parameters = load_parameter(parameter_path)
            if not parameters_have_chip_identity(parameters.data):
                raise ValueError("worker parameters are missing the chip identity")
            workspace.parameters = parameters
        except (OSError, ValueError) as exc:
            step_error = step_error or f"{step_tag} worker parameters could not be reloaded: {exc}"
    return _result(
        start_time,
        peak_memory_mb - start_memory_mb,
        error=step_error,
        resource_observation=resource_observation,
    )


def _restore_rcx_outputs(step: WorkspaceStep, result: dict) -> str | None:
    output = step.output
    names = result.get("rcx_spef")
    if (
        not isinstance(output, EccOutput)
        or output.dir is None
        or not isinstance(names, list)
        or not names
        or any(
            not isinstance(name, str) or Path(name).name != name or not name.endswith(".spef")
            for name in names
        )
        or len(set(names)) != len(names)
    ):
        return "RCX worker did not return a valid published SPEF set"
    output.spef[:] = [Path(output.dir) / name for name in names]
    return None


def _result(
    start_time: float,
    peak_memory_mb: float,
    *,
    error: str | None,
    resource_observation: dict | None = None,
) -> StepExecutionResult:
    peak_memory_mb = 0 if peak_memory_mb < 0 else round(peak_memory_mb, 3)
    elapsed = time.time() - start_time
    return StepExecutionResult(
        error=error,
        elapsed_seconds=elapsed,
        peak_memory_mb=peak_memory_mb,
        runtime=f"{int(elapsed // 3600)}:{int((elapsed % 3600) // 60)}:{int(elapsed % 60)}",
        resource_observation=resource_observation,
    )


def _replay_events(
    result: dict | None,
    workspace_step: WorkspaceStep,
    observer,
    emitted: int,
    attempt_id: str,
) -> int:
    callback = getattr(observer, "on_subflow_stage", None)
    if (
        not callable(callback)
        or not isinstance(result, dict)
        or result.get("attempt_id") != attempt_id
    ):
        return emitted
    events = result.get("events")
    if not isinstance(events, list):
        return emitted
    for event in events[emitted:]:
        if isinstance(event, dict) and event.get("type") == "subflow_stage":
            callback(workspace_step, dict(event.get("subflow_step") or {}))
    return len(events)


class _ResultFileObserver:
    def __init__(self, result: dict, flush):
        self._result = result
        self._flush = flush

    def on_subflow_stage(self, _step, subflow_step) -> None:
        self._result["events"].append({"type": "subflow_stage", "subflow_step": dict(subflow_step)})
        self._flush()


def run_step_worker(
    payload: dict,
    result: dict,
    flush,
    *,
    flow_factory,
    tool_runner,
) -> bool:
    result["schema_version"] = RESULT_SCHEMA_VERSION
    import chipcompiler.data as data_api

    workspace = data_api.load_workspace(directory=payload["workspace_directory"], read_only=True)
    if workspace is None:
        raise RuntimeError("load workspace failed")
    workspace.flow.read_only = True
    flow = flow_factory(workspace)
    flow.create_step_workspaces(initialize_config=False)
    step = flow.get_workspace_step(payload["step_name"])
    if step is None or step.tool != payload["tool"]:
        raise RuntimeError(f"step {payload['step_name']}({payload['tool']}) missing in worker")
    workspace._runtime_flow_observer = _ResultFileObserver(result, flush)

    flow.init_db_engine_for_step(step)
    if flow.engine_db is None:
        raise RuntimeError("ECC engine was not initialized")
    initialization_error = getattr(flow.engine_db, "initialization_error", None)
    if initialization_error is not None:
        raise initialization_error

    from chipcompiler.utility.log import capture_stdio_to_file

    with capture_stdio_to_file(step.log.file):
        ok = tool_runner(workspace=workspace, step=step, ecc_module=flow.engine_db.engine) is True
    if ok and step.name == StepEnum.RCX.value and isinstance(step.output, EccOutput):
        result["rcx_spef"] = [Path(path).name for path in step.output.spef]
    outputs_complete = ok and flow.check_step_result(workspace_step=step)
    if outputs_complete and payload["layout_image"] and not flow._is_placement_only_step(step):
        from chipcompiler.tools import save_layout_image

        if not save_layout_image(workspace=workspace, step=step):
            workspace.logger.warning("[STEP] %s layout image was not generated", step.name)
    if not ok:
        result["error"] = f"step {payload['step_name']} reported failure"
    return ok


def main() -> int:
    from chipcompiler.engine.flow import EngineFlow
    from chipcompiler.tools import run_step

    handler = partial(run_step_worker, flow_factory=EngineFlow, tool_runner=run_step)
    return worker.worker_main(handler)


if __name__ == "__main__":
    raise SystemExit(main())
