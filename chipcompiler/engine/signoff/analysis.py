"""Analysis refresh and validation checks for the signoff package collector.

Split from the collector core: these mixin methods rebuild current
analysis and checklist snapshots for completed steps and turn stale or
missing evidence into package issues. Artifact discovery, lookup, and
materialization stay in collector.py and discovery.py; shared helpers
(``_step_dirs``, ``_read_json``) resolve through the composed collector.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from chipcompiler.analysis.qor.summary_contract import (
    gate_reason,
    is_supported_summary,
    summary_analysis_revision,
    summary_blocking_issues,
    summary_gates,
    summary_missing_metrics,
    summary_quality_status,
)
from chipcompiler.data import (
    LEC_STEP_TOOLS,
    EccOutput,
    StateEnum,
    StepEnum,
    ToolName,
    Workspace,
)
from chipcompiler.data.workspace.flow_policy import FlowInputResolver, FlowInputStepError
from chipcompiler.data.workspace.flow_types import FlowStepEntry
from chipcompiler.engine.signoff.models import SIGNOFF_REQUIRED_QOR_STEPS, SignoffPackageIssue
from chipcompiler.engine.step_chain import apply_info_spef_override, build_workspace_step_for_info


class CollectorAnalysisMixin:
    if TYPE_CHECKING:
        workspace: Workspace

        def _step_dirs(self) -> dict[str, str]: ...

        def _read_json(self, path: Path) -> dict: ...

    def _refresh_workspace_analysis(self, workspace_dir: Path) -> list[SignoffPackageIssue]:
        """Rebuild current analysis and checklist snapshots for completed steps."""
        if self.workspace.flow.path is None:
            self.workspace.flow.path = workspace_dir / "home" / "flow.json"
        issues: list[SignoffPackageIssue] = []
        records = self.workspace.flow.steps()
        resolver = FlowInputResolver(records)

        for index, flow_step in enumerate(records):
            step_name = str(flow_step.get("name", ""))
            tool = str(flow_step.get("tool", ""))
            if not step_name or not tool:
                continue

            input_source = None
            try:
                input_source = resolver.input_source(index)
                workspace_step = self._build_workspace_step(flow_step, input_source)
            except (ImportError, OSError, TypeError, ValueError, FlowInputStepError):
                # A malformed explicit input is reported as a stale/missing
                # analysis issue; execution stays strict and raises.
                workspace_step = None
            if workspace_step is None:
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=step_name in SIGNOFF_REQUIRED_QOR_STEPS,
                        reason=f"Could not construct the current {tool} step definition",
                        kind="freshness",
                    )
                )
                continue
            resolver.record(workspace_step)

            rcx_step = resolver.created_step(StepEnum.RCX.value)
            if (
                rcx_step is not None
                and workspace_step.name == StepEnum.STA.value
                and isinstance(rcx_step.output, EccOutput)
                and isinstance(workspace_step.output, EccOutput)
            ):
                workspace_step.output.spef = rcx_step.output.spef

            if flow_step.get("state") != StateEnum.Success.value:
                continue
            if tool in LEC_STEP_TOOLS:
                continue

            try:
                self._refresh_step_analysis(workspace_step)
            except Exception as error:
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=step_name in SIGNOFF_REQUIRED_QOR_STEPS,
                        reason=f"Current-output analysis refresh failed: {error}",
                        kind="freshness",
                    )
                )

        return issues

    def _build_workspace_step(self, flow_step: FlowStepEntry, input_source):
        try:
            workspace_step = build_workspace_step_for_info(self.workspace, flow_step, input_source)
        except ImportError:
            return None
        if workspace_step is not None:
            apply_info_spef_override(flow_step, workspace_step)
        return workspace_step

    def _refresh_step_analysis(self, step) -> None:
        if step.tool == ToolName.YOSYS:
            from chipcompiler.tools.yosys.checklist import YosysChecklist
            from chipcompiler.tools.yosys.metrics import build_step_metrics

            checker_class = YosysChecklist
        elif step.tool == ToolName.DREAMPLACE:
            from chipcompiler.tools.ecc.metrics import build_step_metrics
            from chipcompiler.tools.ecc_dreamplace.checklist import DreamplaceChecklist

            checker_class = DreamplaceChecklist
        else:
            from chipcompiler.tools.ecc.checklist import EccChecklist
            from chipcompiler.tools.ecc.metrics import build_step_metrics

            checker_class = EccChecklist

        if build_step_metrics(workspace=self.workspace, step=step) is None:
            raise RuntimeError("no current metrics could be built")
        checker = checker_class(workspace=self.workspace, workspace_step=step)
        checker.check()

    def _qor_summary_issues(
        self, workspace_dir: Path, flow_data: dict
    ) -> list[SignoffPackageIssue]:
        issues: list[SignoffPackageIssue] = []
        for flow_step in flow_data.get("steps", []):
            if not isinstance(flow_step, dict) or flow_step.get("state") != StateEnum.Success.value:
                continue
            step_name = str(flow_step.get("name", ""))
            step_dir = self._step_dirs().get(step_name)
            if not step_name or not step_dir:
                continue
            summary_path = workspace_dir / step_dir / "analysis" / "qor_summary.json"
            summary = self._read_json(summary_path)
            required = step_name in SIGNOFF_REQUIRED_QOR_STEPS
            if not is_supported_summary(summary):
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=required,
                        reason=(
                            "qor_summary.json is missing or does not use a supported "
                            "QoR summary contract"
                        ),
                        kind="freshness",
                    )
                )
                continue

            if not summary_analysis_revision(summary):
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=required,
                        reason="qor_summary.json has no current analysis revision",
                        kind="freshness",
                    )
                )

            for blocking_issue in summary_blocking_issues(summary):
                metric_id = str(blocking_issue.get("metric_id", "QoR blocking issue"))
                reason = str(blocking_issue.get("reason", "Current QoR analysis blocked signoff."))
                value = blocking_issue.get("value")
                if value is not None:
                    reason = f"{reason} actual={value}"
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=required,
                        label=metric_id,
                        reason=reason,
                        kind="analysis",
                    )
                )

            gates = summary_gates(summary)
            failed_gates = [gate for gate in gates if gate.get("state") == "failed"]
            for gate in failed_gates:
                if gate.get("blocking") is False:
                    continue
                gate_id = str(gate.get("id", "QoR hard gate"))
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=required,
                        label=gate_id,
                        reason=gate_reason(gate),
                        kind="analysis",
                    )
                )

            quality_status = summary_quality_status(summary)
            if quality_status in {"blocked", "incomplete"} and not failed_gates:
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=required,
                        reason=(
                            f"QoR quality status is {quality_status} without a failed gate record."
                        ),
                        kind="analysis",
                    )
                )

            for missing_metric in summary_missing_metrics(summary):
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=False,
                        label=str(missing_metric.get("metric_id", "QoR metric")),
                        reason=str(
                            missing_metric.get(
                                "reason", "The required current QoR metric is unavailable."
                            )
                        ),
                        kind="analysis",
                    )
                )
        return issues

    def _analysis_issue(
        self,
        step_name: str,
        *,
        required: bool,
        reason: str,
        kind: str,
        label: str | None = None,
    ) -> SignoffPackageIssue:
        step_dir = self._step_dirs().get(step_name, step_name)
        return SignoffPackageIssue(
            kind=kind,
            label=label or f"{step_name} QoR analysis",
            location=f"{step_dir}/analysis/qor_summary.json",
            reason=reason,
            required=required,
            destination=f"analysis/{step_name}/qor_summary.json",
        )

    def _checklist_counts(self, checklist_data: dict) -> dict:
        counts = {"passed": 0, "warning": 0, "failed": 0}
        for item in checklist_data.get("checklist", []):
            if not isinstance(item, dict):
                continue
            state = str(item.get("state", "")).lower()
            if state == "passed":
                counts["passed"] += 1
            elif state == "warning":
                counts["warning"] += 1
            elif state == "failed":
                counts["failed"] += 1
        return counts

    def _checklist_issues(self, checklist_data: dict) -> list[SignoffPackageIssue]:
        issues = []
        for item in checklist_data.get("checklist", []):
            if not isinstance(item, dict):
                continue
            state = str(item.get("state", "")).strip()
            normalized_state = state.lower()
            if normalized_state not in {"warning", "failed"}:
                continue
            scope = " / ".join(
                str(item.get(key, "")).strip()
                for key in ("step", "type", "item")
                if str(item.get(key, "")).strip()
            )
            info = str(item.get("info", "")).strip()
            issues.append(
                SignoffPackageIssue(
                    kind="checklist",
                    label=str(item.get("item", "Checklist item")).strip() or "Checklist item",
                    location=scope or "home/checklist.json",
                    reason=f"{state or normalized_state.title()}{f': {info}' if info else ''}",
                    required=False,
                    destination="final/reports/checklist.json",
                )
            )
        return issues

    def _sta_matrix(self, sta_config: dict) -> list[dict]:
        liberty_by_corner = {
            item.get("corner"): item
            for item in sta_config.get("liberty", [])
            if isinstance(item, dict)
        }
        matrix = []
        for signoff_group in sta_config.get("signoff", []):
            if not isinstance(signoff_group, dict):
                continue
            for lib_corner, rcx_corners in signoff_group.items():
                liberty = liberty_by_corner.get(lib_corner, {})
                if isinstance(rcx_corners, str):
                    rcx_corners = [rcx_corners]
                for rcx_corner in rcx_corners:
                    matrix.append(
                        {
                            "lib_corner": lib_corner,
                            "temperature": liberty.get("temperature", ""),
                            "rcx_corner": rcx_corner,
                        }
                    )
        return matrix

    def _temperature_token(self, temperature) -> str:
        try:
            numeric = float(temperature)
            if numeric.is_integer():
                temperature = int(numeric)
        except (TypeError, ValueError):
            pass
        return str(temperature).replace("-", "m").replace(".", "p")
