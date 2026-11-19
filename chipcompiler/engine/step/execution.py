import logging
import os
from dataclasses import dataclass

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.engine.db import EngineDB
from chipcompiler.utility.log import Logger, flush_cstdio

logger = logging.getLogger(__name__)

STEP_WORKER_MODULE = "chipcompiler.engine.step.process"


@dataclass(frozen=True)
class StepExecutionResult:
    error: str | None
    elapsed_seconds: float
    peak_memory_mb: float
    runtime: str
    resource_observation: dict | None = None


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


def _execute_in_worker(
    workspace: Workspace,
    workspace_step: WorkspaceStep,
    engine_db: EngineDB | None,
    *,
    observer=None,
    started_at: float | None = None,
    worker_module: str = STEP_WORKER_MODULE,
    layout_image: bool = True,
    replay_attempt: str | None = None,
) -> StepExecutionResult:
    from chipcompiler.engine.step import process as step_subprocess

    return step_subprocess.execute_step_subprocess(
        workspace,
        workspace_step,
        observer=observer,
        started_at=started_at,
        worker_module=worker_module,
        layout_image=layout_image,
        replay_attempt=replay_attempt,
    )


def execute_tool_step(
    workspace: Workspace,
    workspace_step: WorkspaceStep,
    engine_db: EngineDB | None,
    *,
    observer=None,
    started_at: float | None = None,
    worker_module: str = STEP_WORKER_MODULE,
    layout_image: bool = True,
    replay_attempt: str | None = None,
) -> StepExecutionResult:
    kwargs = {
        "observer": observer,
        "started_at": started_at,
        "worker_module": worker_module,
        "layout_image": layout_image,
    }
    if replay_attempt is not None:
        kwargs["replay_attempt"] = replay_attempt
    return _execute_in_worker(workspace, workspace_step, engine_db, **kwargs)


def record_tool_failure(
    tool_logger: logging.Logger | Logger,
    step_tag: str,
    error: BaseException,
) -> str:
    flush_cstdio()
    message = _tool_error_message(step_tag, error)
    tool_logger.error(f"[STEP] {step_tag} failed: {message}")
    tool_logger.exception(f"[STEP] {step_tag} exception details")
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
