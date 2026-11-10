"""In-process test double for EngineFlow unit tests."""

import os
import time
from contextlib import nullcontext
from copy import copy, deepcopy
from threading import Event, RLock, Thread

from chipcompiler.data import is_sta_step
from chipcompiler.data.workspace import Flow
from chipcompiler.data.workspace.flow_ledger import ledger_lock
from chipcompiler.engine.resource_observation import new_attempt_id, start_observation
from chipcompiler.engine.step_execution import (
    StepExecutionResult,
    _prepare_log_file,
    get_process_rss_mb,
    record_tool_failure,
)
from chipcompiler.utility.log import capture_stdio_to_file


def _track_current_process_memory(pid, stop_event, peak_memory):
    while not stop_event.is_set():
        peak_memory[0] = max(peak_memory[0], get_process_rss_mb(pid))
        stop_event.wait(0.1)
    peak_memory[0] = max(peak_memory[0], get_process_rss_mb(pid))


# Worker processes isolate concurrent steps; one process cannot: stdio capture
# redirects the process-wide fds and the native DB engine is shared. The steps
# of a parallel checker wave therefore run their tools here one at a time, while
# the engine's ledger work around them stays concurrent.
_ONE_TOOL_AT_A_TIME = RLock()


def _worker_view(workspace):
    """The workspace as a worker process sees it: with a read-only ledger of its own.

    Sibling steps keep committing to the engine's ledger while a tool runs; the
    tool, and an EngineFlow built for it (which reloads its ledger), only ever
    see this snapshot.
    """
    flow = getattr(workspace, "flow", None)
    if not isinstance(flow, Flow):
        return workspace
    with ledger_lock(flow):
        data = deepcopy(flow.data)
    view = copy(workspace)
    view.flow = Flow(path=flow.path, data=data, read_only=True)
    return view


def _initialize_worker_db(workspace, workspace_step):
    from chipcompiler.engine.flow import EngineFlow

    flow = EngineFlow(workspace)
    flow.init_db_engine_for_step(workspace_step)
    return flow.engine_db


def _write_request(workspace, workspace_step, attempt_id, layout_image):
    """Write req.json as the real launcher does; None for test steps outside a workspace."""
    from pathlib import Path

    from chipcompiler.data.handshake import build_step_request, clear_response, write_request

    flow = getattr(workspace, "flow", None)
    # Sibling steps of a parallel wave commit to the same ledger records.
    guard = ledger_lock(flow) if isinstance(flow, Flow) else nullcontext()
    try:
        with guard:
            request = build_step_request(
                Path(workspace.directory),
                flow.steps() if flow is not None else [],
                workspace_step,
                attempt_id=attempt_id,
                layout_image=layout_image,
            )
    except (AttributeError, TypeError, ValueError):
        return None
    write_request(request)
    clear_response(request.directory)
    return request


def execute_in_process(
    workspace,
    workspace_step,
    engine_db,
    *,
    observer=None,
    started_at=None,
    worker_module=None,
    layout_image=True,
):
    with _ONE_TOOL_AT_A_TIME:
        return _execute_in_process(
            workspace,
            workspace_step,
            engine_db,
            observer=observer,
            started_at=started_at,
            worker_module=worker_module,
            layout_image=layout_image,
        )


def _execute_in_process(
    workspace,
    workspace_step,
    engine_db,
    *,
    observer,
    started_at,
    worker_module,
    layout_image,
):
    start_time = time.time() if started_at is None else started_at
    step_tag = f"{workspace_step.name}({workspace_step.tool})"
    log_file = _prepare_log_file(workspace_step)
    pid = os.getpid()
    attempt_id = new_attempt_id()
    request = _write_request(workspace, workspace_step, attempt_id, layout_image)
    worker_workspace = _worker_view(workspace)
    resources = start_observation(
        pid,
        attempt_id=attempt_id,
        isolated=False,
        step=workspace_step.name,
        tool=workspace_step.tool,
    )
    start_memory_mb = 0.0
    peak_memory = [0.0]
    stop_memory_monitor = Event()
    memory_monitor = None
    previous_observer = getattr(worker_workspace, "_runtime_flow_observer", None)
    observer_installed = False
    step_error = None
    try:
        workspace.logger.info(f"[STEP] {step_tag} pid={pid} started")
        start_memory_mb = get_process_rss_mb(pid)
        peak_memory[0] = start_memory_mb
        memory_tracker = _track_current_process_memory
        if is_sta_step(workspace_step):
            from chipcompiler.tools.ecc.sta_parallel import track_sta_process_memory

            memory_tracker = track_sta_process_memory
        memory_monitor = Thread(
            target=memory_tracker,
            args=(pid, stop_memory_monitor, peak_memory),
            daemon=True,
        )
        memory_monitor.start()
        if observer is not None:
            worker_workspace._runtime_flow_observer = observer
            observer_installed = True
        with capture_stdio_to_file(log_file):
            try:
                if worker_module == "agent.step_worker":
                    from agent.tools import run_step
                else:
                    from chipcompiler.tools import run_step

                if request is not None:
                    from chipcompiler.data.handshake import missing_design_data

                    declared_spef = getattr(getattr(workspace, "pdk", None), "spef", None)
                    if missing := missing_design_data(
                        request, workspace_step, declared_spef=declared_spef
                    ):
                        raise RuntimeError(f"{step_tag} cannot run: missing {sorted(missing)}")
                if engine_db is None:
                    engine_db = _initialize_worker_db(worker_workspace, workspace_step)
                if engine_db is None:
                    raise AttributeError("'NoneType' object has no attribute 'engine'")
                initialization_error = getattr(engine_db, "initialization_error", None)
                if initialization_error is not None:
                    raise initialization_error
                result = run_step(
                    workspace=worker_workspace,
                    step=workspace_step,
                    ecc_module=engine_db.engine,
                )
                workspace.logger.info(f"[STEP] {step_tag} finished result={result}")
                if result is not True:
                    step_error = f"{step_tag} reported failure (run_step returned {result!r})."
                if request is not None:
                    from chipcompiler.data.handshake import build_step_response, write_response

                    write_response(
                        request.directory,
                        build_step_response(request, workspace_step, succeeded=step_error is None),
                    )
            except (Exception, SystemExit) as exc:
                step_error = record_tool_failure(workspace.logger, step_tag, exc)
    except (Exception, SystemExit) as exc:
        failure_message = record_tool_failure(workspace.logger, step_tag, exc)
        step_error = step_error or failure_message
    finally:
        resource_observation = resources.finish()
        stop_memory_monitor.set()
        if memory_monitor is not None:
            try:
                memory_monitor.join()
            except (Exception, SystemExit) as exc:
                failure_message = record_tool_failure(workspace.logger, step_tag, exc)
                step_error = step_error or failure_message
        try:
            if observer_installed:
                if previous_observer is None:
                    delattr(worker_workspace, "_runtime_flow_observer")
                else:
                    worker_workspace._runtime_flow_observer = previous_observer
        except (Exception, SystemExit) as exc:
            failure_message = record_tool_failure(workspace.logger, step_tag, exc)
            step_error = step_error or failure_message

    peak_memory_mb = max(0.0, peak_memory[0] - start_memory_mb)
    elapsed = time.time() - start_time
    return StepExecutionResult(
        error=step_error,
        elapsed_seconds=elapsed,
        peak_memory_mb=round(peak_memory_mb, 3),
        runtime=f"{int(elapsed // 3600)}:{int((elapsed % 3600) // 60)}:{int(elapsed % 60)}",
        resource_observation=resource_observation,
    )
