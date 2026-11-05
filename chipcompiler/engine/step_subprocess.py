"""Run one flow step's native tool execution in a one-shot worker process."""

import json
import logging
import os
import time
from functools import partial
from pathlib import Path

from chipcompiler.data import (
    LEC_STEP_TOOLS,
    EccOutput,
    StepEnum,
    Workspace,
    WorkspaceStep,
    is_sta_step,
)
from chipcompiler.data.types import AnalysisData
from chipcompiler.data.workspace.step_handshake import (
    REQ_FILE,
    RSP_FILE,
    HandshakeError,
    ResponseStatus,
    StepRequest,
    clear_response,
    load_request,
    load_response,
    write_request,
    write_response,
)
from chipcompiler.engine import worker
from chipcompiler.engine.resource_observation import new_attempt_id, start_observation
from chipcompiler.engine.step_execution import (
    STEP_WORKER_MODULE,
    StepExecutionResult,
    _prepare_log_file,
    get_process_rss_mb,
)
from chipcompiler.engine.step_request import build_step_request
from chipcompiler.engine.step_response import build_step_response, missing_design_data

logger = logging.getLogger(__name__)

PAYLOAD_SCHEMA_VERSION = 2
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

    try:
        request = build_step_request(
            Path(workspace.directory),
            workspace.flow.steps(),
            workspace_step,
            attempt_id=attempt_id,
            layout_image=layout_image,
        )
        write_request(request)
        clear_response(request.directory)
    except (OSError, ValueError) as exc:
        return _result(start_time, 0.0, error=f"{step_tag} {REQ_FILE} was not written: {exc}")
    payload = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "step_directory": str(request.directory),
        "attempt_id": attempt_id,
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
    _reload_subflow_state(workspace_step, result, attempt_id)
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
    response = None
    if isinstance(result, dict) and result.get("attempt_id") == attempt_id:
        try:
            response = load_response(request.directory)
        except HandshakeError as exc:
            step_error = step_error or f"{step_tag} {exc}"
        if response is not None and response.attempt_id != attempt_id:
            response = None
    if step_error is None and response is None:
        step_error = f"{step_tag} worker did not publish {RSP_FILE} for this attempt."
    if (
        response is not None
        and response.status is ResponseStatus.SUCCESS
        and result is not None
        and result.get("done") is True
        and workspace_step.name == StepEnum.RCX.value
        and cancel_error is None
        and (step_error is None or result.get("ok") is False)
    ):
        rcx_error = _restore_rcx_outputs(
            workspace_step, response.outputs.get(AnalysisData.PARASITICS, ())
        )
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


def _reload_subflow_state(step: WorkspaceStep, result: dict | None, attempt_id: str) -> None:
    if isinstance(result, dict) and result.get("attempt_id") != attempt_id:
        return
    subflow = getattr(step, "subflow", None)
    path = getattr(subflow, "path", None)
    if not path:
        return
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    steps = data.get("steps")
    if isinstance(steps, list) and all(isinstance(item, dict) for item in steps):
        step.subflow.steps = steps


def _restore_rcx_outputs(step: WorkspaceStep, spef: tuple[Path, ...]) -> str | None:
    output = step.output
    if (
        not isinstance(output, EccOutput)
        or output.dir is None
        or not spef
        or any(path.parent != Path(output.dir) or path.suffix != ".spef" for path in spef)
        or len(set(spef)) != len(spef)
    ):
        return "RCX worker did not return a valid published SPEF set"
    output.spef[:] = list(spef)
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

    request = load_request(Path(payload["step_directory"]))
    if request.attempt_id != payload["attempt_id"]:
        raise RuntimeError(f"{REQ_FILE} belongs to another attempt: {request.attempt_id}")
    workspace = data_api.load_workspace(directory=request.workspace_directory, read_only=True)
    if workspace is None:
        raise RuntimeError("load workspace failed")
    # The step's inputs, upstream steps and position in the flow come only from
    # req.json. The ledger stays loaded read-only for the checklist and QoR
    # evidence code, which still reads step states from it.
    workspace.flow.read_only = True
    step = _build_requested_step(workspace, request)
    try:
        declared_spef = getattr(getattr(workspace, "pdk", None), "spef", None)
        if missing := missing_design_data(request, step, declared_spef=declared_spef):
            raise RuntimeError(
                f"{request.step} cannot run: missing {', '.join(sorted(missing))} "
                "(no upstream step provides it and the project does not declare it)"
            )
        flow = flow_factory(workspace)
        workspace._runtime_flow_observer = _ResultFileObserver(result, flush)

        flow.init_db_engine_for_step(step)
        if flow.engine_db is None:
            raise RuntimeError("ECC engine was not initialized")
        initialization_error = getattr(flow.engine_db, "initialization_error", None)
        if initialization_error is not None:
            raise initialization_error

        from chipcompiler.utility.log import capture_stdio_to_file

        with capture_stdio_to_file(step.log.file):
            engine = flow.engine_db.engine
            ok = tool_runner(workspace=workspace, step=step, ecc_module=engine) is True
        outputs_complete = ok and flow.check_step_result(workspace_step=step)
    except (Exception, SystemExit):
        # Downstream steps must see this attempt failed, not a missing answer.
        write_response(request.directory, build_step_response(request, step, succeeded=False))
        raise
    # rsp.json describes the step's design data; the layout thumbnail below is
    # not part of it, so the response is published before rendering.
    write_response(
        request.directory, build_step_response(request, step, succeeded=outputs_complete)
    )
    if outputs_complete and request.layout_image and not flow._is_placement_only_step(step):
        from chipcompiler.tools import save_layout_image

        if not save_layout_image(workspace=workspace, step=step):
            workspace.logger.warning("[STEP] %s layout image was not generated", step.name)
    if not ok:
        result["error"] = f"step {request.step} reported failure"
    return ok


def _build_requested_step(workspace: Workspace, request: StepRequest) -> WorkspaceStep:
    from chipcompiler.tools import create_step

    inputs = request.inputs
    step = create_step(
        workspace=workspace,
        step=request.step,
        eda=request.tool,
        input_def=inputs.design.def_,
        input_verilog=inputs.design.verilog,
        input_db=inputs.golden_verilog if request.tool in LEC_STEP_TOOLS else inputs.design.db,
        step_directory=request.directory,
        initialize_config=False,
    )
    if step is None:
        raise RuntimeError(f"step {request.step}({request.tool}) could not be built in the worker")
    if step.directory is None or Path(step.directory) != request.directory:
        raise RuntimeError(
            f"step {request.step} builds into {step.directory}, not {request.directory}"
        )
    if inputs.spef and isinstance(step.output, EccOutput):
        step.output.spef = list(inputs.spef)
    return step


def main() -> int:
    from chipcompiler.engine.flow import EngineFlow
    from chipcompiler.tools import run_step

    handler = partial(run_step_worker, flow_factory=EngineFlow, tool_runner=run_step)
    return worker.worker_main(handler)


if __name__ == "__main__":
    raise SystemExit(main())
