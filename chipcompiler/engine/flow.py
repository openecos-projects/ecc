#!/usr/bin/env python

import logging
import os
import time
from copy import deepcopy
from pathlib import Path

from chipcompiler.data import (
    EccOutput,
    SkippableStepEnum,
    StateEnum,
    StepBaseEnum,
    StepEnum,
    Workspace,
    WorkspaceStep,
    is_finished_step_state,
    log_flow,
)
from chipcompiler.engine import EngineDB
from chipcompiler.engine.flow_completion import (
    finalize_interrupted_subflow as _finalize_interrupted_subflow,
)
from chipcompiler.engine.flow_completion import (
    normalize_legacy_terminal_state as _normalize_legacy_terminal_state,
)
from chipcompiler.engine.flow_completion import (
    notify_flow_observer as _notify_flow_observer,
)
from chipcompiler.engine.flow_completion import (
    notify_step_completed,
)
from chipcompiler.engine.flow_completion import (
    refresh_qor_report as _refresh_qor_report,
)
from chipcompiler.engine.flow_completion import (
    refresh_signoff_checklist as _refresh_signoff_checklist,
)
from chipcompiler.engine.signoff import (
    SignoffPackageCollector,
    SignoffPackageOptions,
    SignoffPackageResult,
)
from chipcompiler.engine.step_execution import execute_tool_step, record_tool_failure
from chipcompiler.utility import file_digest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State machine transition guards
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, set[str]] = {
    StateEnum.Unstart.value: {
        StateEnum.Ongoing.value,
        StateEnum.Imcomplete.value,
    },
    StateEnum.Pending.value: {
        StateEnum.Ongoing.value,
        StateEnum.Imcomplete.value,
    },
    StateEnum.Ongoing.value: {
        StateEnum.Success.value,
        StateEnum.Imcomplete.value,
        StateEnum.Invalid.value,
    },
    # Terminal states — no outgoing lifecycle transitions.
    # Batch resets (clear_states, _invalidate_suffix) bypass set_state() and
    # can assign any state directly, including Unstart for terminal states.
    StateEnum.Success.value: set(),
    StateEnum.Imcomplete.value: set(),
    StateEnum.Invalid.value: set(),
}


def _validate_transition(old_state: str | None, new_state: str, step_name: str, tool: str) -> None:
    """Raise ``ValueError`` on illegal lifecycle transitions.

    This guard applies only to ``set_state()`` calls.  Batch reset operations
    (``clear_states``, ``_invalidate_suffix``, ``_prepare_steps_for_rerun``)
    assign ``step["state"]`` directly and bypass this check by design.
    """
    if old_state is None or old_state == new_state:
        return
    allowed = _VALID_TRANSITIONS.get(old_state, set())
    if new_state not in allowed:
        raise ValueError(
            f"Illegal state transition for {step_name}/{tool}: "
            f"{old_state} → {new_state}. "
            f"Allowed transitions from {old_state}: {sorted(allowed) or 'none'}"
        )


_GEOMETRY_SNAPSHOT_STEPS = frozenset(
    {
        StepEnum.PRE_FLOORPLAN.value,
        StepEnum.MACRO_PLACEMENT.value,
        StepEnum.POST_FLOORPLAN.value,
        StepEnum.PLACEMENT.value,
        StepEnum.CTS.value,
        SkippableStepEnum.TIMING_OPT.value,
        StepEnum.LEGALIZATION.value,
        StepEnum.ROUTING.value,
        StepEnum.DRC.value,
        StepEnum.LVS.value,
        StepEnum.FILLER.value,
    }
)


class EngineFlow:
    def __init__(self, workspace: Workspace, engine_db: EngineDB = None):
        self.workspace = workspace
        self.workspace_steps = []
        self.engine_db = engine_db  # db engine for this flow

        if self.workspace is not None:
            self.load()

    def build_default_steps(self):
        """Seed the canonical rtl2gds chain (test helper; the CLI/GUI paths
        resolve their own target and policy before seeding)."""
        from chipcompiler.rtl2gds import build_rtl2gds_flow

        steps = [
            self.init_flow_step(step, tool, state) for step, tool, state in build_rtl2gds_flow()
        ]
        # Persist the golden netlist on the LEC step so reloads do not have
        # to guess roles from the golden_* filename convention.
        golden = getattr(self.workspace.design, "golden_verilog", None)
        if golden:
            for step in steps:
                if step["name"] == SkippableStepEnum.LEC.value:
                    step["info"] = {"golden_verilog": str(golden)}

        self.workspace.flow.data = {"steps": steps}

        self.save()

    def has_init(self):
        return self.workspace is not None and len(self.workspace.flow.data.get("steps", [])) > 0

    def init_flow_step(
        self,
        step: StepBaseEnum | str,
        tool: str,
        state: str | StateEnum,
        info: dict | None = None,
    ):
        step_value = step.value if isinstance(step, StepBaseEnum) else step
        state_value = state.value if isinstance(state, StateEnum) else state
        return {
            "name": step_value,  # step name
            "tool": tool,  # eda tool name
            "state": state_value,  # step state
            "runtime": "",  # step run time
            "peak memory (mb)": 0,  # step peak memory
            "info": info or {},  # step additional infomation
        }

    def add_step(
        self,
        step: StepBaseEnum | str,
        tool: str,
        state: str | StateEnum,
        info: dict | None = None,
    ):
        steps = self.workspace.flow.data.get("steps", [])
        steps.append(self.init_flow_step(step, tool, state, info=info))

        self.workspace.flow.data = {"steps": steps}

        self.save()

    def load(self) -> bool:
        """
        load flow config json from workspace
        """
        from chipcompiler.utility import json_read

        if not self.workspace.flow.path:
            self.workspace.flow.data = {}
            return False
        self.workspace.flow.data = json_read(self.workspace.flow.path)
        return len(self.workspace.flow.data.get("steps", [])) > 0

    def save(self) -> bool:
        """
        save flow to workspace json
        """
        from chipcompiler.utility import json_write

        return json_write(self.workspace.flow.path, self.workspace.flow.data)

    def get_step(self, name: str, tool: str):
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                return step

        return None

    def get_workspace_step(self, name: str) -> WorkspaceStep | None:
        for workspace_step in self.workspace_steps:
            if workspace_step.name == name:
                return workspace_step

        return None

    def check_state(self, name: str, tool: str, state: str | StateEnum):
        """
        return True if step state has been set
        """
        step = self.get_step(name, tool)
        state_value = state.value if isinstance(state, StateEnum) else state
        return step is not None and step.get("state") == state_value

    def set_state(
        self,
        name: str,
        tool: str,
        state: str | StateEnum,
        runtime: str = None,
        peak_memory: float = None,
        *,
        clear_runtime_operation: bool = False,
    ) -> bool:
        state_value = state.value if isinstance(state, StateEnum) else state
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                old_state = step.get("state")
                _validate_transition(old_state, state_value, name, tool)
                previous_step = deepcopy(step)
                step["state"] = state_value
                if runtime is not None:
                    step["runtime"] = runtime
                if peak_memory is not None:
                    step["peak memory (mb)"] = peak_memory
                if clear_runtime_operation:
                    step.get("info", {}).pop("runtime_operation", None)

                if self.workspace.flow.path is None:
                    return True
                if not self.save():
                    step.clear()
                    step.update(previous_step)
                    logger.error(
                        "Failed to persist flow state for %s/%s (state=%s)",
                        name,
                        tool,
                        state_value,
                    )
                    return False
                return True

        return False

    def clear_states(self):
        from chipcompiler.data import StateEnum

        for step in self.workspace.flow.data.get("steps", []):
            step["state"] = StateEnum.Unstart.value
            step["runtime"] = ""
            step["peak memory (mb)"] = 0

        self.save()

    def is_flow_success(self):
        """
        check all steps success
        """
        from chipcompiler.data import StateEnum

        for step in self.workspace.flow.data.get("steps", []):
            if step["state"] != StateEnum.Success.value:
                return False

        return True

    def check_step_result(self, workspace_step: WorkspaceStep):
        """
        check step output exist
        """

        success = False
        output = workspace_step.output
        # HARDEN/RCX/GDS results live on the place-and-route (ecc) output leaves.
        ecc_output = output if isinstance(output, EccOutput) else None
        if workspace_step.tool == "yosys_lec" or workspace_step.name in (
            SkippableStepEnum.LEC.value,
            SkippableStepEnum.POST_ROUTE_LEC.value,
        ):
            from chipcompiler.tools.yosys_lec.utility import lec_result_is_proven

            step_input = workspace_step.input
            return lec_result_is_proven(
                output.json,
                golden_verilog=getattr(step_input, "golden_verilog", None),
                gate_verilog=getattr(step_input, "gate_verilog", None),
            )
        match workspace_step.name:
            case StepEnum.SYNTHESIS.value:
                if os.path.exists(output.verilog or ""):
                    success = True
            case StepEnum.HARDEN.value:
                if (
                    ecc_output
                    and os.path.exists(ecc_output.lef or "")
                    and os.path.exists(ecc_output.lib or "")
                ):
                    success = True
            case StepEnum.LVS.value:
                if (
                    ecc_output
                    and os.path.exists(output.def_ or "")
                    and os.path.exists(output.verilog or "")
                    and os.path.exists(output.gds or "")
                    and os.path.exists(workspace_step.report.step or "")
                    and os.path.exists(workspace_step.feature.step or "")
                ):
                    success = True
            case StepEnum.RCX.value:
                spef_list = ecc_output.spef if ecc_output else []
                success = bool(spef_list) and all(
                    os.path.isfile(spef) and os.path.getsize(spef) > 0 for spef in spef_list
                )
            case SkippableStepEnum.TIMING_OPT.value:
                if os.path.exists(output.def_ or "") and os.path.exists(output.verilog or ""):
                    success = True
            case _:
                gds = ecc_output.gds if ecc_output else None
                if (
                    os.path.exists(output.def_ or "")
                    and os.path.exists(output.verilog or "")
                    and os.path.exists(gds or "")
                ):
                    success = True
        if success and workspace_step.name in _GEOMETRY_SNAPSHOT_STEPS:
            geometry_manifest = ecc_output.geometry_manifest if ecc_output else None
            # Unit callers may construct a minimal EccOutput without a geometry
            # destination. Real physical flow steps declare one in their builder;
            # when declared, it is part of the success contract.
            return geometry_manifest is None or geometry_manifest.is_file()
        return success

    def collect_signoff_package(
        self,
        options: SignoffPackageOptions | None = None,
    ) -> SignoffPackageResult:
        """
        Collect harden-flow signoff resources from this flow workspace.
        """
        return SignoffPackageCollector(self.workspace).collect(options)

    def create_step_workspaces(
        self,
        *,
        executable_steps: set[str] | None = None,
        initialize_config: bool = True,
    ):
        """
        create all step workspaces

        executable_steps: names of the steps that will actually run. Only those
        steps verify tool dependencies; other steps are always built so the
        input/output chaining stays intact when a non-selected tool is absent.
        initialize_config: whether step factories may regenerate tool configs.
        """
        self.workspace_steps = []
        pre_step = None
        synthesis_gate_verilog = ""
        synthesis_golden_verilog = ""
        for step in self.workspace.flow.data.get("steps", []):
            if pre_step is None:
                # use the origin def and verilog in workspace for the first step.
                input_def = self.workspace.design.origin_def
                input_verilog = self.workspace.design.origin_verilog
                input_db = None
            else:
                # use the output def and verilog from last step.
                input_def = pre_step.output.def_
                input_verilog = pre_step.output.verilog
                input_db = pre_step.output.db

            from chipcompiler.tools import create_step

            if step["tool"] == "yosys_lec":
                step_info = step.get("info", {}) or {}
                explicit_golden = step_info.get("golden_verilog") or None
                if explicit_golden:
                    input_db = explicit_golden
                elif pre_step is None and self.workspace.design.golden_verilog is not None:
                    input_db = self.workspace.design.golden_verilog
                elif step["name"] == SkippableStepEnum.POST_ROUTE_LEC.value:
                    input_db = synthesis_gate_verilog or self.workspace.design.origin_verilog
                elif pre_step is not None and pre_step.name == StepEnum.SYNTHESIS.value:
                    input_db = synthesis_golden_verilog or None

            # create workspace step
            eda_step = create_step(
                workspace=self.workspace,
                step=step["name"],
                eda=step["tool"],
                input_def=input_def,
                input_verilog=input_verilog,
                input_db=input_db,
                initialize_config=initialize_config,
                check_dependency=executable_steps is None or step["name"] in executable_steps,
            )
            # save workspace step
            if eda_step is not None:
                step_info = step.get("info", {}) or {}
                if (
                    eda_step.name == StepEnum.STA.value
                    and step_info.get("spef")
                    and isinstance(eda_step.output, EccOutput)
                ):
                    eda_step.output.spef = [Path(step_info["spef"])]
                if (
                    pre_step is not None
                    and pre_step.name == StepEnum.RCX.value
                    and eda_step.name == StepEnum.STA.value
                    and isinstance(eda_step.output, EccOutput)
                    and isinstance(pre_step.output, EccOutput)
                ):
                    eda_step.output.spef = pre_step.output.spef
                self.workspace_steps.append(eda_step)
                if eda_step.tool != "yosys_lec":
                    pre_step = eda_step
                if eda_step.name == StepEnum.SYNTHESIS.value:
                    synthesis_gate_verilog = eda_step.output.verilog
                    synthesis_golden_verilog = getattr(eda_step.output, "golden_verilog", None)
            else:
                self.set_state(name=step["name"], tool=step["tool"], state=StateEnum.Imcomplete)
                logger.error(
                    "Failed to create step workspace for %s (tool=%s); "
                    "step marked Incomplete, remaining steps will not be created",
                    step.get("name", step),
                    step.get("tool", "?"),
                )
                break

    def init_db_engine(self) -> bool:
        if len(self.workspace_steps) <= 0:
            return False

        # check ecc is initialized by last step, if exist and success,
        # use it to init db engine directly.
        if self.engine_db is None:
            self.engine_db = EngineDB(workspace=self.workspace)
        else:
            if self.engine_db.has_init():
                return True

        # init engine step by last workpsace step data if all steps finished
        workspace_step = None
        for ws_step in self.workspace_steps:
            step = self.get_step(name=ws_step.name, tool=ws_step.tool)
            state = step.get("state") if step is not None else None
            if not is_finished_step_state(state):
                # use the first unfinished step to setup db engine
                workspace_step = ws_step
                break

        # LEC is a netlist comparison step and does not expose an ECC DB
        # input. Keep any existing DB alive, but do not try to initialize one
        # from the Yosys LEC workspace.
        if workspace_step is not None and workspace_step.tool == "yosys_lec":
            return True

        return self.engine_db.create_db_engine(step=workspace_step)

    def clear_db_engine_after_step(self, workspace_step: WorkspaceStep, state: StateEnum) -> None:
        _ = state
        if workspace_step.tool == "sizer":
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

        digest = file_digest(sdc_path)
        if digest is None:
            return {"availability": "unreadable"}
        sha256, size_bytes = digest
        return {
            "availability": "available",
            "sha256": sha256,
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

    def run_steps(
        self, *, rerun: bool = False, observer=None, require_full_ledger: bool = True
    ) -> bool:
        """
        run all flow steps

        require_full_ledger: verify at the end that every persisted ledger
        step had a workspace step. Callers that intentionally bind execution
        to a range narrower than the persisted ledger pass False.
        """

        for workspace_step in self.workspace_steps:
            _notify_flow_observer(observer, "raise_if_cancelled")
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
                case StateEnum.Invalid:
                    return False
                case StateEnum.Unstart:
                    return False
                case StateEnum.Imcomplete:
                    # An Incomplete step is an infrastructure or check
                    # failure: it blocks the flow.
                    return False
                case StateEnum.Pending:
                    return False
                case StateEnum.Ongoing:
                    return False

        total_steps = len(self.workspace.flow.data.get("steps", []))
        if require_full_ledger and len(self.workspace_steps) < total_steps:
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

        step_tag = f"{workspace_step.name}({workspace_step.tool})"

        if not rerun and self.check_state(
            name=workspace_step.name, tool=workspace_step.tool, state=StateEnum.Success
        ):
            self.workspace.logger.info("[SKIP] %s already succeeded", step_tag)
            self.clear_db_engine_after_step(workspace_step, StateEnum.Success)
            _notify_flow_observer(observer, "on_step_skipped", workspace_step)
            _refresh_qor_report(self.workspace, step_tag)
            return StateEnum.Success

        _normalize_legacy_terminal_state(self, workspace_step, step_tag)

        # set state ongoing
        start_time = time.time()
        timing_constraints = self.timing_constraint_facts()
        flow_step = self.get_step(workspace_step.name, workspace_step.tool)
        operation_marker = getattr(observer, "runtime_operation", None)
        if operation_marker:
            if flow_step is None:
                raise RuntimeError(f"cannot persist runtime operation marker for {step_tag}")
            previous_state = flow_step.get("state")
            _validate_transition(
                previous_state,
                StateEnum.Ongoing.value,
                workspace_step.name,
                workspace_step.tool,
            )
            previous_info = dict(flow_step.get("info", {}))
            flow_step.setdefault("info", {})["runtime_operation"] = {
                **operation_marker,
                "started_at": start_time,
            }
            flow_step["state"] = StateEnum.Ongoing.value
            if not self.save():
                flow_step["state"] = previous_state
                flow_step["info"] = previous_info
                raise RuntimeError(f"failed to persist runtime operation marker for {step_tag}")
        else:
            if flow_step is not None and not self.set_state(
                name=workspace_step.name,
                tool=workspace_step.tool,
                state=StateEnum.Ongoing,
            ):
                raise RuntimeError(f"failed to persist ongoing state for {step_tag}")
        _notify_flow_observer(observer, "on_step_started", workspace_step)
        previous_step = deepcopy(flow_step) if flow_step is not None else None

        execution = execute_tool_step(
            self.workspace,
            workspace_step,
            self.engine_db,
            observer=observer,
            started_at=start_time,
        )
        step_error = execution.error
        elapsed = execution.elapsed_seconds
        peak_memory_mb = execution.peak_memory_mb
        runtime = execution.runtime

        state = StateEnum.Imcomplete
        terminal_persisted = False
        try:
            if step_error is None:
                state = (
                    StateEnum.Success
                    if self.check_step_result(workspace_step=workspace_step)
                    else StateEnum.Imcomplete
                )
                if state == StateEnum.Imcomplete:
                    step_error = f"{step_tag} did not produce the required outputs."

            if state == StateEnum.Imcomplete:
                _finalize_interrupted_subflow(
                    observer,
                    workspace_step,
                    runtime,
                    peak_memory_mb,
                )

            # Run fallible post-success work BEFORE the terminal commit: a
            # failure here must still transition Ongoing -> a terminal failure
            # state; after a persisted Success the transition table forbids
            # the rollback and the ledger would claim a failed step succeeded.
            if state == StateEnum.Success:
                from chipcompiler.tools import save_layout_image

                save_layout_image(workspace=self.workspace, step=workspace_step)

            if flow_step is not None and not self.set_state(
                name=workspace_step.name,
                tool=workspace_step.tool,
                state=state,
                runtime=runtime,
                peak_memory=peak_memory_mb,
                clear_runtime_operation=True,
            ):
                raise RuntimeError(f"failed to persist terminal state for {step_tag}")
            terminal_persisted = True

            # QoR facts persist only after the ledger commits: a refresh
            # failure degrades to a warning, never a state rollback attempt.
            if state == StateEnum.Success:
                try:
                    if self.save_step_flow_facts(
                        workspace_step=workspace_step,
                        state=state,
                        runtime_seconds=elapsed,
                        peak_memory_mb=peak_memory_mb,
                        timing_constraints=timing_constraints,
                    ):
                        try:
                            from chipcompiler.tools import build_step_metrics

                            if (
                                build_step_metrics(workspace=self.workspace, step=workspace_step)
                                is None
                            ):
                                self.workspace.logger.warning(
                                    "[QOR] %s run facts saved; analysis refresh unavailable",
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
                except Exception:
                    self.workspace.logger.exception(
                        "[QOR] %s failed to save run facts after the step succeeded",
                        step_tag,
                    )

            # The workspace QoR report renders the per-step analysis
            # artifacts refreshed above, so it runs after they exist; a
            # failure degrades to a warning like the facts refresh.
            if state == StateEnum.Success:
                _refresh_qor_report(self.workspace, step_tag)
        except (Exception, SystemExit) as exc:
            failure_message = record_tool_failure(self.workspace.logger, step_tag, exc)
            step_error = step_error or failure_message
            state = StateEnum.Imcomplete
            _finalize_interrupted_subflow(
                observer,
                workspace_step,
                runtime,
                peak_memory_mb,
            )
            if flow_step is not None and not self.set_state(
                name=workspace_step.name,
                tool=workspace_step.tool,
                state=state,
                runtime=runtime,
                peak_memory=peak_memory_mb,
                clear_runtime_operation=True,
            ):
                raise RuntimeError(f"failed to persist terminal state for {step_tag}") from exc
            terminal_persisted = True
        finally:
            if terminal_persisted:
                _refresh_signoff_checklist(self.workspace, workspace_step)
            try:
                self.clear_db_engine_after_step(workspace_step, state)
            except (Exception, SystemExit):
                logger.exception("Failed to release DB engine after %s", step_tag)
            if terminal_persisted:
                notify_step_completed(
                    self,
                    observer,
                    workspace_step,
                    state,
                    step_error,
                    previous_step,
                )

        self.workspace.logger.info(
            "[RESULT] %s state=%s runtime=%s mem=%sMB",
            step_tag,
            state.value,
            runtime,
            peak_memory_mb,
        )
        return state

    def init_db_engine_for_step(self, workspace_step: WorkspaceStep) -> bool:
        """Initialize the native DB engine from an explicitly selected step."""
        if self.engine_db is None:
            self.engine_db = EngineDB(workspace=self.workspace)
        elif self.engine_db.has_init():
            return True

        if workspace_step.tool == "yosys_lec":
            # LEC is a netlist comparison step with no ECC DB input; the
            # batch path (init_db_engine) skips it the same way.
            return True

        return self.engine_db.create_db_engine(step=workspace_step)
