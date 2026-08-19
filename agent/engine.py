import os
import time
import traceback
from threading import Event, Thread

from chipcompiler.data import StateEnum, WorkspaceStep
from chipcompiler.engine.flow import EngineFlow, get_process_rss_mb, track_current_process_memory

from .tools import run_step as run_agent_step


class AgentEngineFlow(EngineFlow):
    def build_default_steps(self):
        super().build_default_steps()
        steps = self.workspace.flow.data["steps"]
        if any(step["name"] == "DRC" for step in steps):
            return
        filler_index = next(index for index, step in enumerate(steps) if step["name"] == "filler")
        steps.insert(filler_index, self.init_flow_step("DRC", "ecc", StateEnum.Unstart))
        self.save()

    def run_step(self, workspace_step: WorkspaceStep | str, *, rerun: bool = False) -> StateEnum:
        if isinstance(workspace_step, str):
            workspace_step = self.get_workspace_step(workspace_step)
        if workspace_step is None:
            return StateEnum.Invalid
        step_tag = f"{workspace_step.name}({workspace_step.tool})"
        if not rerun and self.check_state(
            name=workspace_step.name, tool=workspace_step.tool, state=StateEnum.Success
        ):
            self.workspace.logger.info("[SKIP] %s already succeeded", step_tag)
            self.clear_db_engine_after_step(workspace_step, StateEnum.Success)
            return StateEnum.Success

        start_time = time.time()
        timing_constraints = self.timing_constraint_facts()
        self.set_state(name=workspace_step.name, tool=workspace_step.tool, state=StateEnum.Ongoing)
        # The agent is an executor: it never writes step log files. Its bytes
        # stay on fd 1/2 and versioned step markers frame the step's stream
        # for the client-side archiver, exactly like EngineFlow.run_step.
        from chipcompiler.runtime.log_stream import emit_step_marker

        emit_step_marker("begin", step=workspace_step.name, tool=workspace_step.tool)
        start_memory, peak_memory, stop_monitor, monitor = self._start_memory_monitor()
        result = False
        try:
            result = run_agent_step(
                workspace=self.workspace, step=workspace_step, ecc_module=self.engine_db.engine
            )
            self.workspace.logger.info("[STEP] %s finished result=%s", step_tag, result)
        except Exception:
            self.workspace.logger.error("[STEP] %s failed with exception", step_tag)
            traceback.print_exc()
        finally:
            self._stop_memory_monitor(stop_monitor, monitor)

        elapsed = time.time() - start_time
        state = self._step_state(workspace_step, result)
        state, persisted = self._finish_step(
            workspace_step,
            state,
            elapsed,
            timing_constraints,
            max(0, round(peak_memory[0] - start_memory, 3)),
        )
        # The end marker closes the step's byte stream only after every
        # step-scoped write has persisted; a failed final save reads as a
        # crash to consumers, so the marker stays unwritten.
        if persisted:
            emit_step_marker("end", step=workspace_step.name, tool=workspace_step.tool)
        return state

    def _start_memory_monitor(self) -> tuple[float, list[float], Event, Thread]:
        start_memory = get_process_rss_mb(os.getpid())
        peak_memory = [start_memory]
        stop_monitor = Event()
        monitor = Thread(
            target=track_current_process_memory,
            args=(os.getpid(), stop_monitor, peak_memory),
            daemon=True,
        )
        monitor.start()
        return start_memory, peak_memory, stop_monitor, monitor

    @staticmethod
    def _stop_memory_monitor(stop_monitor: Event, monitor: Thread) -> None:
        stop_monitor.set()
        monitor.join()

    def _step_state(self, workspace_step: WorkspaceStep, result: object) -> StateEnum:
        if result is StateEnum.Invalid:
            return StateEnum.Invalid
        if result is True or result is StateEnum.Success:
            return (
                StateEnum.Success
                if self.check_step_result(workspace_step=workspace_step)
                else StateEnum.Imcomplete
            )
        return StateEnum.Imcomplete

    def _finish_step(
        self,
        workspace_step: WorkspaceStep,
        state: StateEnum,
        elapsed: float,
        timing_constraints: dict,
        peak_memory_mb: float,
    ) -> tuple[StateEnum, bool]:
        runtime = f"{int(elapsed // 3600)}:{int((elapsed % 3600) // 60)}:{int(elapsed % 60)}"
        persisted = self.set_state(
            name=workspace_step.name,
            tool=workspace_step.tool,
            state=state,
            runtime=runtime,
            peak_memory=peak_memory_mb,
        )
        if not persisted:
            # The final state did not reach disk: the recorded result is not
            # trustworthy. Downgrade the canonical record in memory (the
            # downgrade itself is not persisted — the save just failed).
            state = StateEnum.Imcomplete
            record = self.get_step(workspace_step.name, workspace_step.tool)
            if record is not None:
                record["state"] = StateEnum.Imcomplete.value
            self.workspace.logger.error(
                "[RESULT] %s(%s) final state could not be persisted; marking step Imcomplete",
                workspace_step.name,
                workspace_step.tool,
            )
        if state == StateEnum.Success:
            self._save_agent_step_facts(
                workspace_step,
                state,
                elapsed,
                peak_memory_mb,
                timing_constraints,
            )
        self.clear_db_engine_after_step(workspace_step, state)
        return state, persisted

    def _save_agent_step_facts(
        self,
        workspace_step: WorkspaceStep,
        state: StateEnum,
        elapsed: float,
        peak_memory: float,
        timing_constraints: dict,
    ) -> None:
        from chipcompiler.tools import build_step_metrics, save_layout_image

        if self.save_step_flow_facts(
            workspace_step=workspace_step,
            state=state,
            runtime_seconds=elapsed,
            peak_memory_mb=peak_memory,
            timing_constraints=timing_constraints,
        ):
            try:
                build_step_metrics(workspace=self.workspace, step=workspace_step)
            except Exception:
                self.workspace.logger.exception("[QOR] failed to refresh analysis")
        save_layout_image(workspace=self.workspace, step=workspace_step)
