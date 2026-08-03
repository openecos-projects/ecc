import glob
import hashlib
import importlib
import json
import shutil
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from chipcompiler.data import StateEnum, StepEnum, Workspace
from chipcompiler.tools.ecc.sta_qor import (
    STA_QOR_SUMMARY_FILENAME,
    STA_REPORT_FILENAMES,
    STA_TIMING_PATHS_FILENAME,
    sta_artifact_directory,
)

SIGNOFF_REQUIRED_QOR_STEPS = {
    StepEnum.HARDEN.value,
    StepEnum.RCX.value,
    StepEnum.STA.value,
    StepEnum.DRC.value,
    StepEnum.FILLER.value,
    StepEnum.ROUTING.value,
}


@dataclass(frozen=True)
class SignoffPackageOptions:
    output_dir: str | None = None
    archive: bool = True
    include_debug: bool = False
    allow_incomplete: bool = False
    materialize: bool = True
    refresh_analysis: bool = False


@dataclass
class SignoffPackageResult:
    ok: bool
    package_dir: str
    archive_path: str | None = None
    manifest_path: str | None = None
    summary_path: str | None = None
    copied: list[dict] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    issues: list["SignoffPackageIssue"] = field(default_factory=list)


@dataclass(frozen=True)
class SignoffPackageIssue:
    kind: str
    label: str
    location: str
    reason: str
    required: bool
    destination: str


class SignoffPackageCollector:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

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

        parameters = self._read_json(workspace_dir / "home" / "parameters.json")
        design = (
            self.workspace.design.name
            or parameters.get("Design", "")
            or self._design_from_outputs(workspace_dir)
        )
        top_module = self.workspace.design.top_module or parameters.get("Top module", "") or design
        pdk_name = getattr(self.workspace.pdk, "name", "") or parameters.get("PDK", "")
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
            role: str, source: Path | None, destination: str, *, required: bool = False
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
            )

        flow_path = workspace_dir / "home" / "flow.json"
        checklist_path = workspace_dir / "home" / "checklist.json"
        flow_data = self.workspace.flow.data or self._read_json(flow_path)
        checklist_data = self._read_json(checklist_path)

        required_steps = self._required_step_states(flow_data)
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
            "db_default_config.json",
            "flow_config.json",
            "rcx.json",
            "sta.json",
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

        db_config = self._read_json(config_dir / "db_default_config.json")
        origin_verilog, origin_verilog_reason = self._find_one(
            workspace_dir / "origin",
            preferred_name=f"{design}.v",
            pattern="*.v",
        )
        if origin_verilog is None:
            missing_required.append("origin Verilog")
            issues.append(
                SignoffPackageIssue(
                    kind="resource",
                    label="Origin Verilog",
                    location=f"origin/{design}.v",
                    reason=origin_verilog_reason,
                    required=True,
                    destination=f"initial/{design}.v",
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

        if origin_verilog is not None:
            add_file("initial.verilog", origin_verilog, f"initial/{design}.v", required=True)
        if origin_sdc is not None:
            add_file("initial.sdc", origin_sdc, f"initial/{design}.sdc", required=True)
        add_file(
            "initial.parameters",
            workspace_dir / "home" / "parameters.json",
            "initial/parameters.json",
            required=True,
        )

        add_file(
            role="final.design.verilog",
            source=workspace_dir / "filler_ecc" / "output" / f"{design}_filler.v.gz",
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

        sta_config = self._read_json(config_dir / "sta.json")
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
                "verilog": f"initial/{design}.v",
                "sdc": f"initial/{design}.sdc",
                "parameters": "initial/parameters.json",
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
            readme_path.write_text(
                f"# {design} Signoff Package\n\n"
                f"- Workspace: {workspace_dir.resolve()}\n"
                f"- Status: {summary['status']}\n"
                "- Harden outputs are under `harden/`.\n"
                "- Final physical resources are under `final/`.\n"
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
    ) -> None:
        if source is None or not source.is_file() or source.stat().st_size <= 0:
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
            shutil.copy2(source, target)
            size_bytes = target.stat().st_size
            sha256 = self._sha256(target)
        else:
            size_bytes = source.stat().st_size
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

    def _read_json(self, path: Path) -> dict:
        try:
            with open(path, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _path_from_config(self, workspace_dir: Path, path_text: str) -> Path | None:
        if not path_text:
            return None
        path = Path(path_text)
        if not path.is_absolute():
            path = workspace_dir / path
        return path if path.is_file() else None

    def _source_path(self, workspace_dir: Path, source: Path) -> str:
        try:
            return source.relative_to(workspace_dir).as_posix()
        except ValueError:
            return str(source)

    def _review_source_path(
        self,
        workspace_dir: Path,
        source: Path | None,
        fallback: str,
    ) -> str:
        if source is None:
            return fallback
        try:
            return source.relative_to(workspace_dir).as_posix()
        except ValueError:
            return source.name

    def _find_one(
        self,
        directory: Path,
        preferred_name: str,
        pattern: str,
    ) -> tuple[Path | None, str]:
        preferred = directory / preferred_name
        if preferred.is_file():
            return preferred, ""
        matches = sorted(directory.glob(pattern)) if directory.is_dir() else []
        if len(matches) == 1:
            return matches[0], ""
        if len(matches) > 1:
            return None, "Multiple matching files found"
        return None, "Required file is missing or empty"

    def _design_from_outputs(self, workspace_dir: Path) -> str:
        for pattern, suffix in (
            ("Harden_ecc/output/*_Harden.gds", "_Harden.gds"),
            ("filler_ecc/output/*_filler.v.gz", "_filler.v.gz"),
        ):
            matches = sorted(workspace_dir.glob(pattern))
            if matches:
                name = matches[0].name
                if name.endswith(suffix):
                    return name[: -len(suffix)]
        return ""

    def _required_step_states(self, flow_data: dict) -> dict:
        required = [
            StepEnum.HARDEN.value,
            StepEnum.RCX.value,
            StepEnum.STA.value,
            StepEnum.DRC.value,
            StepEnum.FILLER.value,
            StepEnum.ROUTING.value,
        ]
        state_by_step = {
            step.get("name"): step.get("state", "")
            for step in flow_data.get("steps", [])
            if isinstance(step, dict)
        }
        return {step: state_by_step.get(step, "") for step in required}

    def _refresh_workspace_analysis(self, workspace_dir: Path) -> list[SignoffPackageIssue]:
        """Rebuild current V3 analysis and checklist snapshots for completed steps."""
        flow_data = self.workspace.flow.data or self._read_json(
            workspace_dir / "home" / "flow.json"
        )
        issues: list[SignoffPackageIssue] = []
        previous_step = None

        for flow_step in flow_data.get("steps", []):
            if not isinstance(flow_step, dict):
                continue
            step_name = str(flow_step.get("name", ""))
            tool = str(flow_step.get("tool", ""))
            if not step_name or not tool:
                continue

            try:
                workspace_step = self._build_workspace_step(flow_step, previous_step)
            except (ImportError, OSError, TypeError, ValueError):
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

            if (
                previous_step is not None
                and previous_step.name == StepEnum.RCX.value
                and workspace_step.name == StepEnum.STA.value
            ):
                workspace_step.output.spef = previous_step.output.spef

            previous_step = workspace_step
            if flow_step.get("state") != StateEnum.Success.value:
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

    def _build_workspace_step(self, flow_step: dict, previous_step):
        step_name = str(flow_step.get("name", ""))
        tool = str(flow_step.get("tool", ""))
        module_alias = {
            "klayout": "klayout_tool",
            "dreamplace": "ecc_dreamplace",
            "sizer": "ecc_sizer",
        }
        try:
            builder = importlib.import_module(
                f"chipcompiler.tools.{module_alias.get(tool, tool)}.builder"
            )
        except ImportError:
            return None

        build_step = getattr(builder, "build_step", None)
        if not callable(build_step):
            return None

        if previous_step is None:
            input_def = self.workspace.design.origin_def
            input_verilog = self.workspace.design.origin_verilog
            input_db = None
        else:
            input_def = previous_step.output.def_
            input_verilog = previous_step.output.verilog
            input_db = previous_step.output.db
        return build_step(
            workspace=self.workspace,
            step_name=step_name,
            input_def=input_def,
            input_verilog=input_verilog,
            input_db=input_db,
        )

    def _refresh_step_analysis(self, step) -> None:
        if step.tool == "yosys":
            from chipcompiler.tools.yosys.checklist import YosysChecklist
            from chipcompiler.tools.yosys.metrics import build_step_metrics

            checker_class = YosysChecklist
        elif step.tool == "dreamplace":
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
            if summary.get("schema_version") != 3:
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=required,
                        reason=(
                            "qor_summary.json is missing or does not use the current V3 contract"
                        ),
                        kind="freshness",
                    )
                )
                continue

            if not summary.get("analysis_revision"):
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=required,
                        reason="qor_summary.json has no current analysis revision",
                        kind="freshness",
                    )
                )

            blocking_issues = summary.get("blocking_issues", [])
            for blocking_issue in blocking_issues if isinstance(blocking_issues, list) else []:
                if not isinstance(blocking_issue, dict):
                    continue
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

            hard_gates = summary.get("hard_gates", [])
            for gate in hard_gates if isinstance(hard_gates, list) else []:
                if not isinstance(gate, dict) or gate.get("passed") is not False:
                    continue
                gate_id = str(gate.get("id", "QoR hard gate"))
                reason = (
                    f"{gate.get('metric', gate_id)} actual={gate.get('actual')} "
                    f"does not satisfy {gate.get('threshold')}"
                )
                issues.append(
                    self._analysis_issue(
                        step_name=step_name,
                        required=required,
                        label=gate_id,
                        reason=reason,
                        kind="analysis",
                    )
                )

            missing_metrics = summary.get("missing_metrics", [])
            for missing_metric in missing_metrics if isinstance(missing_metrics, list) else []:
                if not isinstance(missing_metric, dict):
                    continue
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

    def _step_dirs(self) -> dict[str, str]:
        return {
            StepEnum.SYNTHESIS.value: "Synthesis_yosys",
            StepEnum.FLOORPLAN.value: "Floorplan_ecc",
            StepEnum.NETLIST_OPT.value: "fixFanout_ecc",
            StepEnum.PLACEMENT.value: "place_dreamplace",
            StepEnum.CTS.value: "CTS_ecc",
            StepEnum.LEGALIZATION.value: "legalization_dreamplace",
            StepEnum.ROUTING.value: "route_ecc",
            StepEnum.DRC.value: "drc_ecc",
            StepEnum.FILLER.value: "filler_ecc",
            StepEnum.RCX.value: "RCX_ecc",
            StepEnum.STA.value: "sta_ecc",
            StepEnum.HARDEN.value: "Harden_ecc",
        }
