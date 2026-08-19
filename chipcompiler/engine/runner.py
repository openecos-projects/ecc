"""Step execution lifecycle for EngineFlow.

Owns the protocol-critical ordering for a single step or a full flow:
markers, memory tracking, the authoritative final save, post-processing,
db cleanup, observer callbacks, and the render gate. EngineFlow inherits
this mixin; the data/state/build methods stay in flow.py.
"""

import hashlib
import logging
import os
import time
from contextlib import nullcontext
from threading import Event, Thread

from chipcompiler.data import StateEnum, WorkspaceStep, log_flow
from chipcompiler.engine import EngineDB


def get_process_rss_mb(pid: int) -> float:
    peak_memory = 0
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    peak_memory = rss_kb / 1024
                    break
    except (OSError, ValueError):
        pass
    return peak_memory


def track_current_process_memory(pid: int, stop_event: Event, peak_memory: list[float]):
    while not stop_event.is_set():
        peak_memory[0] = max(peak_memory[0], get_process_rss_mb(pid))
        stop_event.wait(0.1)
    peak_memory[0] = max(peak_memory[0], get_process_rss_mb(pid))


class EngineFlowRunner:
    """Mixin: step/flow execution lifecycle; requires the EngineFlow spine."""

    def clear_db_engine_after_step(self, workspace_step: WorkspaceStep, state: StateEnum) -> None:
        if workspace_step.tool == "sizer" and state == StateEnum.Success:
            engine_db = self.engine_db
            self.engine_db = None
            if engine_db is not None:
                close = getattr(engine_db, "close", None)
                if callable(close):
                    close()

    def timing_constraint_facts(self) -> dict:
        sdc_path = self.workspace.pdk.sdc
        if sdc_path is None:
            return {"availability": "missing_source"}

        try:
            path = os.fspath(sdc_path)
            size_bytes = os.path.getsize(path)
            digest = hashlib.sha256()
            with open(path, "rb") as sdc_file:
                for chunk in iter(lambda: sdc_file.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return {"availability": "unreadable"}

        return {
            "availability": "available",
            "sha256": digest.hexdigest(),
            "size_bytes": size_bytes,
        }

    def save_step_flow_facts(
        self,
        workspace_step: WorkspaceStep,
        state: StateEnum,
        runtime_seconds: float,
        peak_memory_mb: float,
        timing_constraints: dict,
    ) -> bool:
        feature_path = getattr(workspace_step.feature, "step", None)
        if feature_path is None or feature_path == "":
            return False

        from chipcompiler.utility import JsonReadError, json_read_strict, json_write

        try:
            existing = json_read_strict(feature_path)
        except (FileNotFoundError, JsonReadError):
            existing = {}
        payload = existing if isinstance(existing, dict) else {}
        payload["run"] = {
            "state": state.value,
            "runtime_seconds": round(runtime_seconds, 3),
            "peak_memory_mb": round(peak_memory_mb, 3),
        }
        payload["constraints"] = {"sdc": timing_constraints}
        return json_write(file_path=feature_path, data=payload)

        return True

    def run_steps(self, *, rerun: bool = False, observer=None) -> bool:
        """
        run all flow steps
        """
        from chipcompiler.runtime.log_stream import archive_own_step_logs

        from .rerun import downgrade_unarchived_step

        # Direct in-process runs (documented Python API) self-archive so step
        # logs exist and markers stay off the caller's terminal; inside a
        # worker/sidecar process the outer client owns the stream and this
        # context passes through.
        succeeded = True
        directory = self.workspace.directory
        with archive_own_step_logs(directory) if directory is not None else nullcontext() as reader:
            try:
                for workspace_step in self.workspace_steps:
                    self.workspace.logger.log_section(
                        f"{workspace_step.tool} - begin step - {workspace_step.name}"
                    )
                    self.init_db_engine()
                    state = (
                        self.run_step(workspace_step, rerun=rerun)
                        if observer is None
                        else self.run_step(workspace_step, rerun=rerun, observer=observer)
                    )

                    log_flow(workspace=self.workspace)
                    self.workspace.logger.log_section(
                        f"{workspace_step.tool} - end step - {workspace_step.name}"
                    )

                    match state:
                        case StateEnum.Success:
                            continue
                        case _:
                            succeeded = False
                            break
            except BaseException:
                # Reconcile archive evidence before the exception propagates.
                if reader is not None:
                    downgrade_unarchived_step(self, reader, [])
                raise

        # An archive failure or unmatched begin must not report success over a
        # missing step log; reconcile after the reader drains. (reader is None
        # when an outer client owns the stream — nothing to reconcile here.)
        if reader is not None and (
            reader.state.error is not None or reader.state.active_step is not None
        ):
            downgrade_unarchived_step(self, reader, [])
            succeeded = False
        if not succeeded:
            return False

        total_steps = len(self.workspace.flow.data.get("steps", []))
        if len(self.workspace_steps) < total_steps:
            self.workspace.logger.error(
                "Flow incomplete: %d of %d steps were created; remaining steps could not be set up",
                len(self.workspace_steps),
                total_steps,
            )
            return False

        return True

    def run_step(
        self,
        workspace_step: WorkspaceStep | str,
        *,
        rerun: bool = False,
        observer=None,
    ) -> StateEnum:
        """
        run single step
        """
        if isinstance(workspace_step, str):
            workspace_step = self.get_workspace_step(workspace_step)
        if workspace_step is None:
            return StateEnum.Invalid

        from chipcompiler.runtime.log_stream import archive_own_step_logs

        from .rerun import downgrade_unarchived_step

        # Direct callers get client-side archival too; inside a worker/sidecar
        # process or an explicit archive context this passes through.
        if self.workspace.directory is None:
            return self._run_step_body(workspace_step, rerun=rerun, observer=observer)
        reader = None
        try:
            with archive_own_step_logs(self.workspace.directory) as active_reader:
                reader = active_reader
                state = self._run_step_body(workspace_step, rerun=rerun, observer=observer)
        except BaseException:
            # Reconcile archive evidence before the exception propagates.
            if reader is not None:
                downgrade_unarchived_step(self, reader, [])
            raise
        # An archive failure or unmatched begin must not report Success over a
        # missing log; reconcile after the reader drains.
        if reader is not None and (
            reader.state.error is not None or reader.state.active_step is not None
        ):
            downgrade_unarchived_step(self, reader, [])
            return StateEnum.Imcomplete
        return state

    def _run_step_body(
        self,
        workspace_step: WorkspaceStep,
        *,
        rerun: bool = False,
        observer=None,
    ) -> StateEnum:
        step_tag = f"{workspace_step.name}({workspace_step.tool})"

        if not rerun and self.check_state(
            name=workspace_step.name, tool=workspace_step.tool, state=StateEnum.Success
        ):
            self.workspace.logger.info("[SKIP] %s already succeeded", step_tag)
            self.clear_db_engine_after_step(workspace_step, StateEnum.Success)
            _notify_flow_observer(observer, "on_step_skipped", workspace_step)
            return StateEnum.Success

        # set state ongoing
        start_time = time.time()
        timing_constraints = self.timing_constraint_facts()
        self.set_state(name=workspace_step.name, tool=workspace_step.tool, state=StateEnum.Ongoing)
        _notify_flow_observer(observer, "on_step_started", workspace_step)

        self.workspace.logger.info(f"[STEP] {step_tag} pid={os.getpid()} started")

        from chipcompiler.runtime.log_stream import emit_step_marker

        try:
            emit_step_marker("begin", step=workspace_step.name, tool=workspace_step.tool)
        except OSError:
            # fd 2 is closed or the reader pipe is broken: the marker never
            # reached any client, so recovery could never identify this step
            # from the stream. Downgrade the persisted Ongoing now instead of
            # leaving a permanent Ongoing no repair pass can find.
            self.set_state(
                name=workspace_step.name, tool=workspace_step.tool, state=StateEnum.Imcomplete
            )
            raise

        pid = os.getpid()
        start_memory_mb = get_process_rss_mb(pid)
        peak_memory = [start_memory_mb]
        stop_memory_monitor = Event()
        memory_monitor = Thread(
            target=track_current_process_memory,
            args=(pid, stop_memory_monitor, peak_memory),
            daemon=True,
        )
        memory_monitor.start()
        previous_observer = getattr(self.workspace, "_runtime_flow_observer", None)
        if observer is not None:
            self.workspace._runtime_flow_observer = observer
        step_raised_exception = False
        result = None
        try:
            result = self._invoke_step_tool(workspace_step)
            self.workspace.logger.info(f"[STEP] {step_tag} finished result={result}")
        except Exception:
            step_raised_exception = True
            self.workspace.logger.error(f"[STEP] {step_tag} failed with exception")
            self.workspace.logger.exception(f"[STEP] {step_tag} exception details")
        finally:
            stop_memory_monitor.set()
            memory_monitor.join()
            if observer is not None:
                if previous_observer is None:
                    delattr(self.workspace, "_runtime_flow_observer")
                else:
                    self.workspace._runtime_flow_observer = previous_observer

        # compute metrics
        peak_memory_mb = peak_memory[0] - start_memory_mb
        peak_memory_mb = 0 if peak_memory_mb < 0 else round(peak_memory_mb, 3)
        elapsed = time.time() - start_time
        runtime = f"{int(elapsed // 3600)}:{int((elapsed % 3600) // 60)}:{int(elapsed % 60)}"

        # determine and save state
        state = self._derive_step_state(workspace_step, result, raised=step_raised_exception)

        persisted = self.set_state(
            name=workspace_step.name,
            tool=workspace_step.tool,
            state=state,
            runtime=runtime,
            peak_memory=peak_memory_mb,
        )
        if not persisted:
            # The marker protocol guarantees the final state is persisted
            # before the end marker; a failed save makes the run's result
            # untrustworthy. Downgrade the canonical in-memory record (the
            # downgrade itself is not persisted — the save just failed),
            # suppress the end marker, and report the step incomplete.
            state = StateEnum.Imcomplete
            record = self.get_step(workspace_step.name, workspace_step.tool)
            if record is not None:
                record["state"] = StateEnum.Imcomplete.value
            self.workspace.logger.error(
                "[RESULT] %s final state could not be persisted; marking step Imcomplete",
                step_tag,
            )
        self.workspace.logger.info(
            "[RESULT] %s state=%s runtime=%s mem=%sMB exitcode=%s",
            step_tag,
            state.value,
            runtime,
            peak_memory_mb,
            0,
        )

        # save layout snapshot on success
        if state == StateEnum.Success:
            if self.save_step_flow_facts(
                workspace_step=workspace_step,
                state=state,
                runtime_seconds=elapsed,
                peak_memory_mb=peak_memory_mb,
                timing_constraints=timing_constraints,
            ):
                try:
                    from chipcompiler.tools import build_step_metrics

                    if build_step_metrics(workspace=self.workspace, step=workspace_step) is None:
                        self.workspace.logger.warning(
                            "[QOR] %s run facts were saved but analysis refresh is unavailable",
                            step_tag,
                        )
                except Exception:
                    self.workspace.logger.exception(
                        "[QOR] %s failed to refresh analysis after saving run facts",
                        step_tag,
                    )
            else:
                self.workspace.logger.warning(
                    "[QOR] %s has no step feature path; run facts were not saved",
                    step_tag,
                )
            from chipcompiler.tools import save_layout_image

            save_layout_image(workspace=self.workspace, step=workspace_step)

        self.clear_db_engine_after_step(workspace_step, state)
        # The end marker closes the step's byte stream only after every
        # step-scoped write (state persistence, [RESULT], QOR, layout, db
        # cleanup) has flushed, and always before the completion notification.
        # When the final state could not be persisted, the marker stays
        # unwritten: consumers treat the step as crashed and repair its state.
        if persisted:
            emit_step_marker("end", step=workspace_step.name, tool=workspace_step.tool)
        _notify_flow_observer(observer, "on_step_completed", workspace_step, state)
        if state == StateEnum.Success and not _wait_for_step_rendered(
            observer,
            workspace_step,
            state,
        ):
            return StateEnum.Invalid

        return state

    def init_db_engine_for_step(self, workspace_step: WorkspaceStep) -> bool:
        """Initialize the native DB engine from an explicitly selected step."""
        if self.engine_db is None:
            self.engine_db = EngineDB(workspace=self.workspace)
        elif self.engine_db.has_init():
            return True

        return self.engine_db.create_db_engine(step=workspace_step)

    def _invoke_step_tool(self, workspace_step: WorkspaceStep):
        """Run the step's tool. Subclasses redirect to their own runner."""
        from chipcompiler.tools import run_step as run_tool_step

        return run_tool_step(
            workspace=self.workspace, step=workspace_step, ecc_module=self.engine_db.engine
        )

    def _derive_step_state(
        self, workspace_step: WorkspaceStep, result, *, raised: bool
    ) -> StateEnum:
        """Map the tool result to the step state. Subclasses keep their own
        result vocabulary; the base engine trusts the artifact check."""
        if raised:
            return StateEnum.Imcomplete
        return (
            StateEnum.Success
            if self.check_step_result(workspace_step=workspace_step)
            else StateEnum.Imcomplete
        )


def _notify_flow_observer(observer, method_name: str, *args) -> None:
    """Keep optional GUI observers outside the flow engine's failure domain."""
    if observer is None:
        return
    callback = getattr(observer, method_name, None)
    if not callable(callback):
        return
    try:
        callback(*args)
    except Exception:
        # Runtime observers must never turn a completed tool execution into a
        # failed flow. The coordinator records transport failures separately.
        logging.getLogger(__name__).exception("flow observer callback failed: %s", method_name)


def _wait_for_step_rendered(observer, workspace_step: WorkspaceStep, state: StateEnum) -> bool:
    if observer is None or state != StateEnum.Success:
        return True
    callback = getattr(observer, "wait_for_step_rendered", None)
    if not callable(callback):
        return True
    try:
        return bool(callback(workspace_step, state))
    except Exception:
        # Fail-open: observer bugs must not invalidate successful tool results.
        logging.getLogger(__name__).exception("flow observer render gate failed")
        return True
