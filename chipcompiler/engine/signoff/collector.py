"""Signoff package collection: discovery, materialization, and archiving.

The collector core orchestrates one signoff package build: it verifies
step states, copies artifacts into ``final/reports`` layout, writes the
manifest and summary, and archives the tree. Validation lives in
analysis.py, artifact lookup in discovery.py, and the package data
model in models.py.
"""

import glob
import json
import os
import shutil
import tarfile
import time
from pathlib import Path

from chipcompiler.data import StateEnum, StepEnum, Workspace
from chipcompiler.engine.signoff.analysis import CollectorAnalysisMixin
from chipcompiler.engine.signoff.discovery import CollectorDiscoveryMixin
from chipcompiler.engine.signoff.models import (
    SignoffPackageIssue,
    SignoffPackageOptions,
    SignoffPackageResult,
)
from chipcompiler.tools.ecc.sta_qor import (
    STA_POWER_REPORT_FILENAME,
    STA_QOR_SUMMARY_FILENAME,
    STA_REPORT_FILENAMES,
    STA_TIMING_PATHS_FILENAME,
    sta_artifact_directory,
)
from chipcompiler.utility import file_digest
from chipcompiler.utility.filelist import (
    FILELIST_SUFFIXES,
    parse_filelist,
    resolve_initial_rtl,
    rewrite_absolute_entries,
)


class SignoffPackageCollector(CollectorAnalysisMixin, CollectorDiscoveryMixin):
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def text_report(self) -> str:
        """GUI-parity text design summary for this workspace.

        The implementation lives in engine.signoff.report to keep this module
        from growing further; re-exported below as the public entry point.
        """
        return generate_text_report(self.workspace)

    def collect(
        self,
        options: SignoffPackageOptions | None = None,
    ) -> SignoffPackageResult:
        options = options or SignoffPackageOptions()
        if self.workspace is None or not self.workspace.directory:
            raise FileNotFoundError("workspace is not configured")

        workspace_dir = Path(self.workspace.directory)
        if not workspace_dir.exists():
            raise FileNotFoundError(f"workspace does not exist: {workspace_dir}")

        refresh_issues = (
            self._refresh_workspace_analysis(workspace_dir) if options.refresh_analysis else []
        )

        from chipcompiler.data.workspace_config import workspace_config_path

        parameters = self._read_parameters(workspace_config_path(workspace_dir))
        design = (
            self.workspace.design.name
            or parameters.get("design", "")
            or self._design_from_outputs(workspace_dir)
        )
        top_module = self.workspace.design.top_module or parameters.get("top_module", "") or design
        pdk_name = getattr(self.workspace.pdk, "name", "") or parameters.get("pdk", "")
        if not design:
            raise ValueError("cannot determine design name for signoff package")

        package_root = Path(options.output_dir) if options.output_dir else workspace_dir / "signoff"
        package_dir = package_root / f"{design}_signoff_package"
        if options.materialize:
            if package_dir.exists():
                shutil.rmtree(package_dir)
            package_dir.mkdir(parents=True, exist_ok=True)

        copied: list[dict] = []
        missing_required: list[str] = []
        missing_optional: list[str] = []
        warnings: list[str] = []
        issues: list[SignoffPackageIssue] = []

        def add_file(
            role: str,
            source: Path | None,
            destination: str,
            *,
            required: bool = False,
            content: str | None = None,
        ) -> None:
            self._add_file(
                workspace_dir=workspace_dir,
                package_dir=package_dir,
                role=role,
                source=source,
                destination=destination,
                required=required,
                copied=copied,
                missing_required=missing_required,
                missing_optional=missing_optional,
                issues=issues,
                materialize=options.materialize,
                content=content,
            )

        flow_path = workspace_dir / "home" / "flow.json"
        checklist_path = workspace_dir / "home" / "checklist.json"
        if self.workspace.flow.path is None:
            self.workspace.flow.path = flow_path
        checklist_data = self._read_json(checklist_path)

        has_synthesis = self.workspace.flow.has_step(StepEnum.SYNTHESIS)
        synthesis_verilog = self._synthesis_output_verilog() if has_synthesis else None
        # Golden precedence mirrors the execution wiring: synthesis output,
        # then the declared golden netlist, then the origin RTL.
        lec_golden = (
            synthesis_verilog
            or getattr(self.workspace.design, "golden_verilog", None)
            or getattr(self.workspace.design, "origin_verilog", None)
        )
        filler_verilog = workspace_dir / "filler_ecc" / "output" / f"{design}_filler.v.gz"
        # The canonical chain wires postRouteLec's gate input to the LVS output.
        lec_gate = workspace_dir / "lvs_ecc" / "output" / f"{design}_lvs.v.gz"
        require_lec = self._requires_post_route_lec(lec_golden, lec_gate)
        required_steps = self._required_step_states(require_lec=require_lec)
        for step_name, state in required_steps.items():
            if state != StateEnum.Success.value:
                missing_required.append(f"flow step {step_name} is {state or 'missing'}")
                issues.append(
                    SignoffPackageIssue(
                        kind="flow",
                        label=f"{step_name} flow step",
                        location=step_name,
                        reason=f"State is {state or 'missing'}",
                        required=True,
                        destination=f"flow step {step_name}",
                    )
                )

        config_dir = workspace_dir / "config"
        required_configs = {
            "db_ecc.json",
            "rcx_ecc.json",
            "sta_ecc.json",
        }
        if not config_dir.is_dir():
            missing_required.append("config directory")
            issues.append(
                SignoffPackageIssue(
                    kind="resource",
                    label="Config directory",
                    location="config",
                    reason="Required directory does not exist",
                    required=True,
                    destination="config directory",
                )
            )
        else:
            for config_file in sorted(path for path in config_dir.rglob("*") if path.is_file()):
                rel = config_file.relative_to(config_dir).as_posix()
                add_file(
                    role=f"config.{config_file.stem}",
                    source=config_file,
                    destination=f"config/{rel}",
                    required=config_file.name in required_configs,
                )
            for config_name in sorted(required_configs):
                if not (config_dir / config_name).is_file():
                    missing_required.append(f"config/{config_name}")
                    issues.append(
                        SignoffPackageIssue(
                            kind="resource",
                            label=f"Config {config_name}",
                            location=f"config/{config_name}",
                            reason="Required file is missing or empty",
                            required=True,
                            destination=f"config/{config_name}",
                        )
                    )

        db_config = self._read_json(config_dir / "db_ecc.json")
        configured_filelist = (
            None if not has_synthesis else getattr(self.workspace.design, "input_filelist", None)
        )
        origin_rtl = resolve_initial_rtl(
            configured_filelist,
            getattr(self.workspace.design, "origin_verilog", None),
            workspace_dir / "origin",
        )
        if origin_rtl is not None:
            rtl_suffix = ".v.gz" if origin_rtl.name.endswith(".v.gz") else origin_rtl.suffix.lower()
            rtl_destination = f"initial/{design}{rtl_suffix}"
        else:
            rtl_destination = f"initial/{design}.v"
        if origin_rtl is None or not origin_rtl.is_file():
            missing_required.append("origin RTL")
            issues.append(
                SignoffPackageIssue(
                    kind="resource",
                    label="Origin RTL",
                    location=self._review_source_path(workspace_dir, origin_rtl, "origin"),
                    reason="Required file is missing or empty",
                    required=True,
                    destination=rtl_destination,
                )
            )
        origin_sdc = self._path_from_config(
            workspace_dir,
            db_config.get("INPUT", {}).get("sdc_path", ""),
        )
        if origin_sdc is None:
            origin_sdc, origin_sdc_reason = self._find_one(
                workspace_dir / "origin",
                preferred_name=f"{design}.sdc",
                pattern="*.sdc",
            )
            if origin_sdc is None:
                missing_required.append("origin SDC")
                issues.append(
                    SignoffPackageIssue(
                        kind="resource",
                        label="Origin SDC",
                        location=f"origin/{design}.sdc",
                        reason=origin_sdc_reason,
                        required=True,
                        destination=f"initial/{design}.sdc",
                    )
                )

        add_file(
            role="harden.gds",
            source=workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.gds",
            destination=f"harden/{design}.gds",
            required=True,
        )
        add_file(
            role="harden.lef",
            source=workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.lef",
            destination=f"harden/{design}.lef",
            required=True,
        )
        add_file(
            role="harden.lib",
            source=workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.lib",
            destination=f"harden/{design}.lib",
            required=True,
        )
        add_file(
            role="harden.image",
            source=workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.png",
            destination=f"harden/{design}.png",
        )

        if origin_rtl is not None and origin_rtl.is_file():
            # Like synthesis, a configured input_filelist is always a filelist;
            # runtime-created ones are suffixless (origin/filelist), so the
            # suffix check alone would miss them.
            is_filelist = (
                origin_rtl.suffix.lower() in FILELIST_SUFFIXES
                or origin_rtl.name == "filelist"
                or (configured_filelist is not None and origin_rtl == Path(configured_filelist))
            )
            if is_filelist:
                # Workspace creation copies filelist sources into origin/ keeping
                # each entry's filelist-relative path (absolute entries land at
                # their basename); bundle them the same way and rewrite absolute
                # entries to those basenames so the packaged filelist stays
                # resolvable. +incdir header trees are not bundled.
                try:
                    rtl_entries = parse_filelist(str(origin_rtl))
                    filelist_text = rewrite_absolute_entries(origin_rtl.read_text(encoding="utf-8"))
                except (OSError, ValueError) as error:
                    # Without the entries the packaged filelist would dangle, so
                    # block the export instead of shipping an incomplete package.
                    issues.append(
                        SignoffPackageIssue(
                            kind="resource",
                            label="Origin RTL sources",
                            location=self._review_source_path(workspace_dir, origin_rtl, "origin"),
                            reason=f"Could not parse origin filelist for packaging: {error}",
                            required=True,
                            destination=rtl_destination,
                        )
                    )
                    rtl_entries = []
                else:
                    add_file(
                        "initial.filelist",
                        origin_rtl,
                        rtl_destination,
                        required=True,
                        content=filelist_text,
                    )
                packaged_entries = set()
                escaped_entries = []
                for rtl_entry in rtl_entries:
                    relative = (
                        os.path.basename(rtl_entry) if os.path.isabs(rtl_entry) else rtl_entry
                    )
                    # Parent-relative entries would escape initial/ (and already
                    # escaped origin/ at creation); bundling them corrupts the
                    # package layout, so they block the export instead.
                    normalized = os.path.normpath(relative)
                    if normalized == ".." or normalized.startswith(f"..{os.sep}"):
                        escaped_entries.append(rtl_entry)
                        continue
                    if normalized in packaged_entries:
                        continue
                    packaged_entries.add(normalized)
                    add_file(
                        "initial.verilog",
                        workspace_dir / "origin" / normalized,
                        f"initial/{normalized}",
                        required=True,
                    )
                if escaped_entries:
                    issues.append(
                        SignoffPackageIssue(
                            kind="resource",
                            label="Origin RTL sources",
                            location=self._review_source_path(workspace_dir, origin_rtl, "origin"),
                            reason=(
                                "Filelist entries escape the package layout: "
                                + ", ".join(escaped_entries)
                            ),
                            required=True,
                            destination=rtl_destination,
                        )
                    )
            else:
                add_file("initial.verilog", origin_rtl, rtl_destination, required=True)
        if origin_sdc is not None:
            add_file("initial.sdc", origin_sdc, f"initial/{design}.sdc", required=True)
        from chipcompiler.data.workspace_config import workspace_config_path

        parameters_config = workspace_config_path(workspace_dir)
        if not parameters_config.exists():
            # A read-only legacy workspace (TOML migration deferred) runs on
            # its parameters.json — package the file it actually runs on.
            parameters_config = workspace_dir / "home" / "parameters.json"
        add_file(
            "initial.parameters",
            parameters_config,
            f"initial/{parameters_config.name}",
            required=True,
        )

        if has_synthesis:
            add_file(
                role="synthesis.verilog",
                source=synthesis_verilog,
                destination=f"synthesis/{design}.v.gz",
                required=True,
            )

        lec_dir = workspace_dir / self._step_dirs()[StepEnum.POST_ROUTE_LEC.value]
        lec_result = lec_dir / "output" / f"{design}_{StepEnum.POST_ROUTE_LEC.value}_result.json"
        if require_lec:
            add_file(
                role="lec.result",
                source=lec_result,
                destination="final/reports/postRouteLec/result.json",
                required=True,
            )
            add_file(
                role="lec.equiv_status",
                source=lec_dir / "report" / "equiv_status.rpt",
                destination="final/reports/postRouteLec/report/equiv_status.rpt",
                required=True,
            )
            add_file(
                role="lec.status_report",
                source=lec_dir / "report" / "run_lec_status.rpt",
                destination="final/reports/postRouteLec/report/run_lec_status.rpt",
                required=True,
            )
            add_file(
                role="lec.failed_rtlil",
                source=lec_dir / "report" / "equiv_failed.il",
                destination="final/reports/postRouteLec/report/equiv_failed.il",
            )
            add_file(
                role="lec.failed_verilog",
                source=lec_dir / "report" / "equiv_failed.v",
                destination="final/reports/postRouteLec/report/equiv_failed.v",
            )
            from chipcompiler.tools.yosys_lec.utility import lec_result_status

            lec_status = lec_result_status(
                lec_result,
                golden_verilog=lec_golden,
                gate_verilog=lec_gate,
            )
            if lec_result.is_file() and lec_status != "proven":
                missing_required.append("final/reports/postRouteLec/result.json")
                issues.append(
                    SignoffPackageIssue(
                        kind="resource",
                        label="lec.result",
                        location=self._review_source_path(
                            workspace_dir,
                            lec_result,
                            "final/reports/postRouteLec/result.json",
                        ),
                        reason=(
                            "Yosys LEC proof is stale; golden or gate netlist changed"
                            if lec_status == "stale"
                            else "Yosys LEC did not prove equivalence"
                        ),
                        required=True,
                        destination="final/reports/postRouteLec/result.json",
                    )
                )

        add_file(
            role="final.design.verilog",
            source=filler_verilog,
            destination=f"final/design/{design}.v.gz",
            required=True,
        )
        add_file(
            role="final.design.def",
            source=workspace_dir / "filler_ecc" / "output" / f"{design}_filler.def.gz",
            destination=f"final/design/{design}.def.gz",
            required=True,
        )
        add_file(
            role="final.design.gds",
            source=workspace_dir / "filler_ecc" / "output" / f"{design}_filler.gds",
            destination=f"final/design/{design}.gds",
            required=True,
        )
        add_file(
            role="final.design.image",
            source=workspace_dir / "filler_ecc" / "output" / f"{design}_filler.png",
            destination=f"final/design/{design}.png",
        )

        sta_config = self._read_json(config_dir / "sta_ecc.json")
        sta_matrix = self._sta_matrix(sta_config)
        expected_spefs = set()
        for item in sta_matrix:
            expected_spefs.add(
                f"{top_module}_{item['rcx_corner']}_{self._temperature_token(item['temperature'])}C.spef"
            )
            report_dir = sta_artifact_directory(
                workspace_dir / "sta_ecc" / "report",
                item["lib_corner"],
                item["temperature"],
                item["rcx_corner"],
            )
            feature_dir = sta_artifact_directory(
                workspace_dir / "sta_ecc" / "feature",
                item["lib_corner"],
                item["temperature"],
                item["rcx_corner"],
            )
            report_dest = (
                f"final/timing/sta/{item['lib_corner']}_"
                f"{self._temperature_token(item['temperature'])}/"
                f"{item['rcx_corner']}/report"
            )
            for report_name in STA_REPORT_FILENAMES:
                add_file(
                    role="final.sta_report",
                    source=report_dir / report_name,
                    destination=f"{report_dest}/{report_name}",
                    required=True,
                )
            # Optional: workspaces whose STA ran before power collection have
            # no per-corner power report; package it when present.
            add_file(
                role="final.sta_report",
                source=report_dir / STA_POWER_REPORT_FILENAME,
                destination=f"{report_dest}/{STA_POWER_REPORT_FILENAME}",
            )
            item["report"] = f"{report_dest}/qor_summary.rpt"
            feature_dest = report_dest.removesuffix("/report") + "/feature"
            add_file(
                role="final.sta_qor_summary",
                source=feature_dir / STA_QOR_SUMMARY_FILENAME,
                destination=f"{feature_dest}/{STA_QOR_SUMMARY_FILENAME}",
                required=True,
            )
            add_file(
                role="final.sta_timing_paths",
                source=feature_dir / STA_TIMING_PATHS_FILENAME,
                destination=f"{feature_dest}/{STA_TIMING_PATHS_FILENAME}",
                required=True,
            )
            item["qor_summary"] = f"{feature_dest}/{STA_QOR_SUMMARY_FILENAME}"
            item["timing_paths"] = f"{feature_dest}/{STA_TIMING_PATHS_FILENAME}"

        rcx_output_dir = workspace_dir / "RCX_ecc" / "output"
        spef_paths = sorted(rcx_output_dir.glob("*.spef")) if rcx_output_dir.is_dir() else []
        if expected_spefs:
            for spef_name in sorted(expected_spefs):
                add_file(
                    role="final.spef",
                    source=rcx_output_dir / spef_name,
                    destination=f"final/timing/spef/{spef_name}",
                    required=True,
                )
            for spef_path in spef_paths:
                if spef_path.name not in expected_spefs:
                    add_file(
                        role="final.spef",
                        source=spef_path,
                        destination=f"final/timing/spef/{spef_path.name}",
                    )
        elif spef_paths:
            for spef_path in spef_paths:
                add_file(
                    role="final.spef",
                    source=spef_path,
                    destination=f"final/timing/spef/{spef_path.name}",
                    required=True,
                )
        else:
            missing_required.append("RCX SPEF files")
            issues.append(
                SignoffPackageIssue(
                    kind="resource",
                    label="RCX SPEF files",
                    location="RCX_ecc/output",
                    reason="No SPEF files were found",
                    required=True,
                    destination="RCX SPEF files",
                )
            )

        add_file("status.flow", flow_path, "final/reports/flow.json", required=True)

        for step_name, step_dir in self._step_dirs().items():
            if step_name == StepEnum.POST_ROUTE_LEC.value:
                continue
            for kind in ("analysis", "report"):
                self._copy_tree_files(
                    workspace_dir=workspace_dir,
                    package_dir=package_dir,
                    source_dir=workspace_dir / step_dir / kind,
                    destination_dir=f"final/reports/{step_name}/{kind}",
                    role=f"report.{kind}",
                    copied=copied,
                    missing_optional=missing_optional,
                    issues=issues,
                    materialize=options.materialize,
                )

        if options.include_debug:
            self._collect_debug_files(
                workspace_dir=workspace_dir,
                package_dir=package_dir,
                copied=copied,
                missing_optional=missing_optional,
                issues=issues,
                materialize=options.materialize,
            )

        # Resource collection finds package evidence, but the refreshed home
        # checklist is the single authority for signoff readiness and export.
        from chipcompiler.tools.ecc.signoff_checklist import rebuild_home_checklist

        analysis_issues = refresh_issues
        checklist_data = rebuild_home_checklist(
            self.workspace,
            resource_issues=[*issues, *analysis_issues],
            persist=options.materialize,
        )
        add_file(
            "status.checklist",
            checklist_path,
            "final/reports/checklist.json",
            required=True,
        )
        checklist_counts = checklist_data.get("summary", {})
        checklist_items = checklist_data.get("checklist", [])
        blocked_items = [
            item
            for item in checklist_items
            if isinstance(item, dict) and item.get("blocked") is True
        ]
        attention_items = [
            item
            for item in checklist_items
            if isinstance(item, dict) and item.get("state") == "warning"
        ]
        missing_required = [str(item.get("id")) for item in blocked_items]
        missing_optional = [str(item.get("id")) for item in attention_items]
        if blocked_items or attention_items:
            warnings.append("home checklist requires attention; see final/reports/checklist.json")

        qor_metrics = self._read_json(workspace_dir / "drc_ecc" / "analysis" / "qor_metrics.json")
        ok = len(blocked_items) == 0
        flow_success = all(state == StateEnum.Success.value for state in required_steps.values())
        summary = {
            "schema_version": 1,
            "status": "ok" if ok else "incomplete",
            "design": design,
            "top_module": top_module,
            "pdk": pdk_name,
            "required_steps": required_steps,
            "checks": {
                "flow": "passed" if flow_success else "failed",
                "home_checklist": checklist_counts,
                "qor_analysis_issue_count": len(analysis_issues),
            },
            "initial": {
                "verilog": rtl_destination,
                "sdc": f"initial/{design}.sdc",
                "parameters": f"initial/{parameters_config.name}",
            },
            "config": "config/",
            "harden": {
                "gds": f"harden/{design}.gds",
                "lef": f"harden/{design}.lef",
                "lib": f"harden/{design}.lib",
            },
            "final": {
                "verilog": f"final/design/{design}.v.gz",
                "def": f"final/design/{design}.def.gz",
                "gds": f"final/design/{design}.gds",
                "image": f"final/design/{design}.png",
            },
            "qor_metrics": qor_metrics,
            "sta_matrix": sta_matrix,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "warnings": warnings,
        }
        if require_lec:
            lec_payload = self._read_json(lec_result)
            summary["lec"] = {
                "status": lec_payload.get("status", ""),
                "result": "final/reports/postRouteLec/result.json",
                "equiv_status": "final/reports/postRouteLec/report/equiv_status.rpt",
                "status_report": "final/reports/postRouteLec/report/run_lec_status.rpt",
                "golden_verilog": lec_payload.get("golden_verilog", ""),
                "gate_verilog": lec_payload.get("gate_verilog", ""),
            }
        if has_synthesis:
            summary["synthesis"] = {"verilog": f"synthesis/{design}.v.gz"}
        summary_path = package_dir / "summary.json"

        manifest = {
            "schema_version": 1,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "workspace": str(workspace_dir.resolve()),
            "design": design,
            "top_module": top_module,
            "pdk": pdk_name,
            "flow": {
                "source": "home/flow.json",
                "all_required_steps_success": flow_success,
            },
            "files": copied,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "warnings": warnings,
        }
        manifest_path = package_dir / "manifest.json"

        archive_path = None
        if options.materialize:
            summary_path.write_text(json.dumps(summary, indent=2))
            manifest_path.write_text(json.dumps(manifest, indent=2))

            readme_path = package_dir / "README.md"
            input_verilog_description = "- Mapped synthesis netlist is under `synthesis/`.\n"
            if not has_synthesis:
                input_verilog_description = (
                    "- Original imported netlist is under `initial/` because this flow "
                    "has no Synthesis step.\n"
                )
            readme_path.write_text(
                f"# {design} Signoff Package\n\n"
                + f"- Workspace: {workspace_dir.resolve()}\n"
                + f"- Status: {summary['status']}\n"
                + input_verilog_description
                + "- Harden outputs are under `harden/`.\n"
                + "- Final physical resources are under `final/`.\n"
                + "- Post-route LEC evidence is under `final/reports/postRouteLec/`.\n"
            )

            if options.archive and (ok or options.allow_incomplete):
                archive_path = str(package_dir.with_suffix(".tar.gz"))
                archive_file = Path(archive_path)
                if archive_file.exists():
                    archive_file.unlink()
                with tarfile.open(archive_file, "w:gz") as archive:
                    archive.add(package_dir, arcname=package_dir.name)

        return SignoffPackageResult(
            ok=ok,
            package_dir=str(package_dir),
            archive_path=archive_path,
            manifest_path=str(manifest_path),
            summary_path=str(summary_path),
            copied=copied,
            missing_required=missing_required,
            missing_optional=missing_optional,
            warnings=warnings,
            issues=issues,
        )

    def _add_file(
        self,
        workspace_dir: Path,
        package_dir: Path,
        role: str,
        source: Path | None,
        destination: str,
        *,
        required: bool,
        copied: list[dict],
        missing_required: list[str],
        missing_optional: list[str],
        issues: list[SignoffPackageIssue],
        materialize: bool,
        content: str | None = None,
    ) -> None:
        if content is not None:
            missing = not content
        else:
            missing = source is None or not source.is_file() or source.stat().st_size <= 0
        if missing:
            if required:
                missing_required.append(destination)
            else:
                missing_optional.append(destination)
            issues.append(
                SignoffPackageIssue(
                    kind="resource",
                    label=role,
                    location=self._review_source_path(workspace_dir, source, destination),
                    reason=(
                        "Required file is missing or empty"
                        if required
                        else "Optional file is missing or empty"
                    ),
                    required=required,
                    destination=destination,
                )
            )
            return

        if materialize:
            target = package_dir / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                shutil.copy2(source, target)
            else:
                target.write_text(content, encoding="utf-8")
            size_bytes = target.stat().st_size
            digest = file_digest(target)
            sha256 = digest[0] if digest else None
        else:
            size_bytes = len(content.encode()) if content is not None else source.stat().st_size
            sha256 = None
        copied.append(
            {
                "role": role,
                "required": required,
                "source": self._source_path(workspace_dir, source),
                "destination": destination,
                "size_bytes": size_bytes,
                "sha256": sha256,
            }
        )

    def _copy_tree_files(
        self,
        workspace_dir: Path,
        package_dir: Path,
        source_dir: Path,
        destination_dir: str,
        role: str,
        copied: list[dict],
        missing_optional: list[str],
        issues: list[SignoffPackageIssue],
        *,
        materialize: bool,
    ) -> None:
        if not source_dir.is_dir():
            return
        for source in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            relative = source.relative_to(source_dir).as_posix()
            self._add_file(
                workspace_dir=workspace_dir,
                package_dir=package_dir,
                role=role,
                source=source,
                destination=f"{destination_dir}/{relative}",
                required=False,
                copied=copied,
                missing_required=[],
                missing_optional=missing_optional,
                issues=issues,
                materialize=materialize,
            )

    def _collect_debug_files(
        self,
        workspace_dir: Path,
        package_dir: Path,
        copied: list[dict],
        missing_optional: list[str],
        issues: list[SignoffPackageIssue],
        *,
        materialize: bool,
    ) -> None:
        patterns = [
            "*_ecc/feature/**/*",
            "*_ecc/subflow.json",
        ]
        for pattern in patterns:
            for path_text in sorted(glob.glob(str(workspace_dir / pattern), recursive=True)):
                source = Path(path_text)
                if not source.is_file():
                    continue
                destination = f"debug/{source.relative_to(workspace_dir).as_posix()}"
                self._add_file(
                    workspace_dir=workspace_dir,
                    package_dir=package_dir,
                    role="debug",
                    source=source,
                    destination=destination,
                    required=False,
                    copied=copied,
                    missing_required=[],
                    missing_optional=missing_optional,
                    issues=issues,
                    materialize=materialize,
                )
        output_db_dirs = sorted(workspace_dir.glob("*_ecc/output/*_db"))
        output_view_dirs = sorted(workspace_dir.glob("*_ecc/output/*_view"))
        for source in output_db_dirs + output_view_dirs:
            if not source.is_dir():
                continue
            self._copy_tree_files(
                workspace_dir=workspace_dir,
                package_dir=package_dir,
                source_dir=source,
                destination_dir=f"debug/{source.relative_to(workspace_dir).as_posix()}",
                role="debug",
                copied=copied,
                missing_optional=missing_optional,
                issues=issues,
                materialize=materialize,
            )

    def _step_dirs(self) -> dict[str, str]:
        from chipcompiler.data.step_dirs import STEP_DIRECTORIES

        return STEP_DIRECTORIES


# Public entry point for the text design summary; the implementation lives in


# the engine.signoff.report* sibling modules, re-exported here as the API.
from chipcompiler.engine.signoff.report import generate_text_report  # noqa: E402,F401
