import logging
import os
import time
import traceback as _traceback_mod
from dataclasses import dataclass
from threading import Event, Thread

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.engine.db import EngineDB
from chipcompiler.utility.log import capture_stdio_to_file, flush_cstdio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepExecutionResult:
    error: str | None
    elapsed_seconds: float
    peak_memory_mb: float
    runtime: str


def get_process_rss_mb(pid: int) -> float:
    rss_mb = 0.0
    try:
        with open(f"/proc/{pid}/status") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    rss_mb = int(line.split()[1]) / 1024
                    break
    except (OSError, ValueError):
        pass
    return rss_mb


def track_current_process_memory(pid: int, stop_event: Event, peak_memory: list[float]) -> None:
    while not stop_event.is_set():
        peak_memory[0] = max(peak_memory[0], get_process_rss_mb(pid))
        stop_event.wait(0.1)
    peak_memory[0] = max(peak_memory[0], get_process_rss_mb(pid))


def execute_tool_step(
    workspace: Workspace,
    workspace_step: WorkspaceStep,
    engine_db: EngineDB | None,
    *,
    observer=None,
    started_at: float | None = None,
) -> StepExecutionResult:
    """Run one tool while containing its stdio, memory monitor, and failures."""
    start_time = time.time() if started_at is None else started_at
    step_tag = f"{workspace_step.name}({workspace_step.tool})"
    log_file = _prepare_log_file(workspace_step)
    pid = os.getpid()
    start_memory_mb = 0.0
    peak_memory = [0.0]
    stop_memory_monitor = Event()
    memory_monitor = None
    previous_observer = getattr(workspace, "_runtime_flow_observer", None)
    observer_installed = False
    step_error = None
    try:
        workspace.logger.info(f"[STEP] {step_tag} pid={pid} started")
        start_memory_mb = get_process_rss_mb(pid)
        peak_memory[0] = start_memory_mb
        memory_monitor = Thread(
            target=track_current_process_memory,
            args=(pid, stop_memory_monitor, peak_memory),
            daemon=True,
        )
        memory_monitor.start()
        if observer is not None:
            workspace._runtime_flow_observer = observer
            observer_installed = True
        with capture_stdio_to_file(log_file) as capture_ok:
            if not capture_ok:
                workspace.logger.warning(
                    "[STEP] %s step log path unavailable: %s", step_tag, log_file
                )
            try:
                from chipcompiler.tools import run_step

                if engine_db is None:
                    raise AttributeError("'NoneType' object has no attribute 'engine'")
                initialization_error = getattr(engine_db, "initialization_error", None)
                if initialization_error is not None:
                    raise initialization_error
                result = run_step(
                    workspace=workspace,
                    step=workspace_step,
                    ecc_module=engine_db.engine,
                )
                workspace.logger.info(f"[STEP] {step_tag} finished result={result}")
            except (Exception, SystemExit) as exc:
                step_error = record_tool_failure(
                    workspace.logger, step_tag, exc, step_log_file=log_file
                )
    except (Exception, SystemExit) as exc:
        failure_message = record_tool_failure(
            workspace.logger, step_tag, exc, step_log_file=log_file
        )
        step_error = step_error or failure_message
    finally:
        stop_memory_monitor.set()
        if memory_monitor is not None:
            try:
                memory_monitor.join()
            except (Exception, SystemExit) as exc:
                failure_message = record_tool_failure(
                    workspace.logger,
                    step_tag,
                    exc,
                    step_log_file=log_file,
                )
                step_error = step_error or failure_message
        try:
            if observer_installed:
                if previous_observer is None:
                    delattr(workspace, "_runtime_flow_observer")
                else:
                    workspace._runtime_flow_observer = previous_observer
        except (Exception, SystemExit) as exc:
            failure_message = record_tool_failure(
                workspace.logger, step_tag, exc, step_log_file=log_file
            )
            step_error = step_error or failure_message

    peak_memory_mb = peak_memory[0] - start_memory_mb
    peak_memory_mb = 0 if peak_memory_mb < 0 else round(peak_memory_mb, 3)
    elapsed = time.time() - start_time
    return StepExecutionResult(
        error=step_error,
        elapsed_seconds=elapsed,
        peak_memory_mb=peak_memory_mb,
        runtime=f"{int(elapsed // 3600)}:{int((elapsed % 3600) // 60)}:{int(elapsed % 60)}",
    )


def record_tool_failure(
    tool_logger: logging.Logger,
    step_tag: str,
    error: BaseException,
    step_log_file: str = "",
) -> str:
    flush_cstdio()
    message = _tool_error_message(step_tag, error)
    tool_logger.error(f"[STEP] {step_tag} failed: {message}")
    tool_logger.exception(f"[STEP] {step_tag} exception details")
    if step_log_file:
        try:
            tool_logger.write_to_file(step_log_file, f"[STEP] {step_tag} failed: {message}")
            tb_text = "".join(
                _traceback_mod.format_exception(type(error), error, error.__traceback__)
            )
            tool_logger.write_to_file(step_log_file, tb_text)
        except Exception:
            pass
    return message


def _prepare_log_file(workspace_step: WorkspaceStep) -> str:
    log_file = workspace_step.log.file or ""
    if not log_file:
        return ""
    log_file = os.path.abspath(log_file)
    try:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    except Exception:
        logger.exception("Failed to prepare stdio log file: %s", log_file)
        return ""
    return log_file


def _tool_error_message(step_tag: str, error: BaseException) -> str:
    if isinstance(error, SystemExit):
        return f"{step_tag} exited unexpectedly (code {error.code!r})."
    return str(error) or type(error).__name__
