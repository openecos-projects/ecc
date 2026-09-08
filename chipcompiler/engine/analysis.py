import hashlib
import math
from pathlib import Path
from typing import Any, TypeGuard

from chipcompiler.data.step_dirs import STEP_DIRECTORIES
from chipcompiler.tools.ecc.sta_qor import STA_POWER_REPORT_FILENAME, STA_REPORT_FILENAMES
from chipcompiler.utility import JsonReadError, file_digest, json_read_strict

_ANALYSIS_FILES = (
    ("metrics", "qor_metrics", "qor_metrics.json", 3),
    ("summary", "qor_summary", "qor_summary.json", 4),
    ("hotspots", "qor_hotspots", "qor_hotspots.json", 3),
)
_TIMING_FILE = ("timingIssues", "sta_timing_issues", "sta_timing_issues.json", 1)
_SUBFLOW_MAX_BYTES = 1024 * 1024
_SUBFLOW_MAX_STEPS = 256
_ARTIFACT_HASH_MAX_BYTES = 16 * 1024 * 1024
_CONGESTION_IMAGES = (
    ("egr_congestion_map", "{step}_egr_horizontal_overflow.png"),
    ("egr_congestion_map", "{step}_egr_vertical_overflow.png"),
    ("egr_congestion_map", "{step}_egr_union_overflow.png"),
    ("RUDY_map", "{step}_rudy_horizontal.png"),
    ("RUDY_map", "{step}_rudy_vertical.png"),
    ("RUDY_map", "{step}_rudy_union.png"),
    ("RUDY_map", "{step}_lut_rudy_horizontal.png"),
    ("RUDY_map", "{step}_lut_rudy_vertical.png"),
    ("RUDY_map", "{step}_lut_rudy_union.png"),
    ("density_map", "{step}_allcell_density.png"),
)


def build_workspace_analysis(
    workspace: Any, workspace_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = Path(workspace.directory).resolve()
    flow = getattr(getattr(workspace, "flow", None), "data", {})
    raw_steps = flow.get("steps", []) if isinstance(flow, dict) else []
    design = str(getattr(getattr(workspace, "design", None), "name", "")).strip()
    steps: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for order, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            continue
        step_id = raw_step.get("name")
        tool_id = raw_step.get("tool")
        if not _safe_segment(step_id) or not _safe_segment(tool_id):
            continue
        identity = "".join(character for character in step_id.casefold() if character.isalnum())
        if identity == "fixfanout":
            continue
        step_dir = root / STEP_DIRECTORIES.get(step_id, f"{step_id}_{tool_id}")
        step: dict[str, Any] = {
            "stepId": step_id,
            "toolId": tool_id,
            "order": order,
            "flowState": str(raw_step.get("state", "")),
        }
        declared = list(_ANALYSIS_FILES)
        if step_id.lower() == "sta":
            declared.append(_TIMING_FILE)
        for field, kind, filename, schema_version in declared:
            path = step_dir / "analysis" / filename
            reference = path.relative_to(root).as_posix()
            artifact = _artifact_ref(
                path,
                workspace_id=workspace_id,
                reference=reference,
                step_id=step_id,
                kind=kind,
                root=root,
            )
            artifacts.append(artifact)
            step[field] = _analysis_file(path, artifact["artifactId"], schema_version, root)
        if "timingIssues" not in step:
            step["timingIssues"] = None
        if tool_id.lower() == "yosys_lec" and design:
            result = step_dir / "output" / f"{design}_{step_id}_result.json"
            artifact = _artifact_ref(
                result,
                workspace_id=workspace_id,
                reference=result.relative_to(root).as_posix(),
                step_id=step_id,
                kind="lec_result",
                root=root,
            )
            artifacts.append(artifact)
            step["lecResult"] = _lec_result_file(result, artifact["artifactId"], root)
        step["subflow"] = _subflow_summary(step_dir / "subflow.json", root)
        if design:
            layout = step_dir / "output" / f"{design}_{step_id}.png"
            artifacts.append(
                _artifact_ref(
                    layout,
                    workspace_id=workspace_id,
                    reference=layout.relative_to(root).as_posix(),
                    step_id=step_id,
                    kind="layout_image",
                    root=root,
                )
            )
            if step_id.lower() == "harden":
                for suffix in ("gds", "lef", "lib"):
                    output = step_dir / "output" / f"{design}_{step_id}.{suffix}"
                    artifacts.append(
                        _artifact_ref(
                            output,
                            workspace_id=workspace_id,
                            reference=output.relative_to(root).as_posix(),
                            step_id=step_id,
                            kind="harden_output",
                            root=root,
                        )
                    )
        geometry = step_dir / "output" / "geometry" / "geometry.manifest"
        artifacts.append(
            _artifact_ref(
                geometry,
                workspace_id=workspace_id,
                reference=geometry.relative_to(root).as_posix(),
                step_id=step_id,
                kind="layout_geometry",
                root=root,
            )
        )
        report_names = (
            (f"{step_id}_stat.json", f"{step_id}_check.rpt")
            if tool_id.lower() == "yosys"
            else (f"{step_id}.db.rpt", f"{step_id}.rpt")
        )
        for report_name in report_names:
            report = step_dir / "report" / report_name
            artifacts.append(
                _artifact_ref(
                    report,
                    workspace_id=workspace_id,
                    reference=report.relative_to(root).as_posix(),
                    step_id=step_id,
                    kind="report_text",
                    root=root,
                )
            )
        timing_files: list[tuple[str, Path]] = []
        if step_id.lower() == "synthesis":
            timing_root = step_dir / "feature" / "post_synthesis"
            timing_files.extend(
                (
                    ("timing_summary", timing_root / "qor_summary.json"),
                    ("timing_paths", timing_root / "timing_paths.json"),
                )
            )
        timing_data = step.get("timingIssues")
        timing_payload = timing_data.get("data") if isinstance(timing_data, dict) else None
        timing_paths = (
            timing_payload.get("artifact_paths") if isinstance(timing_payload, dict) else None
        )
        if step_id.lower() == "sta":
            for item in timing_paths[:32] if isinstance(timing_paths, list) else []:
                if not isinstance(item, dict):
                    continue
                report_dir = _safe_step_artifact_path(step_dir, item.get("report_dir"), root)
                if report_dir is None:
                    continue
                try:
                    relative_report_dir = report_dir.relative_to(step_dir / "report")
                except ValueError:
                    continue
                report_names = list(STA_REPORT_FILENAMES)
                if (report_dir / STA_POWER_REPORT_FILENAME).is_file():
                    report_names.append(STA_POWER_REPORT_FILENAME)
                for report_name in report_names:
                    report = report_dir / report_name
                    artifact = _artifact_ref(
                        report,
                        workspace_id=workspace_id,
                        reference=report.relative_to(root).as_posix(),
                        step_id=step_id,
                        kind="report_text",
                        root=root,
                    )
                    artifact["name"] = (relative_report_dir / report_name).as_posix()
                    artifacts.append(artifact)
        for item in timing_paths[:32] if isinstance(timing_paths, list) else []:
            if not isinstance(item, dict):
                continue
            for kind, field in (
                ("timing_summary", "qor_summary_file"),
                ("timing_paths", "timing_paths_file"),
            ):
                timing_path = _safe_step_artifact_path(step_dir, item.get(field), root)
                if timing_path is not None:
                    timing_files.append((kind, timing_path))
        for kind, path in timing_files:
            artifacts.append(
                _artifact_ref(
                    path,
                    workspace_id=workspace_id,
                    reference=path.relative_to(root).as_posix(),
                    step_id=step_id,
                    kind=kind,
                    root=root,
                )
            )
        if step_id.lower() in {"place", "cts"}:
            for directory, filename in _CONGESTION_IMAGES:
                image = step_dir / "feature" / directory / filename.format(step=step_id)
                artifacts.append(
                    _artifact_ref(
                        image,
                        workspace_id=workspace_id,
                        reference=image.relative_to(root).as_posix(),
                        step_id=step_id,
                        kind="congestion_image",
                        root=root,
                    )
                )
        steps.append(step)
    return {"steps": steps}, artifacts


def _lec_result_file(path: Path, artifact_id: str, root: Path) -> dict[str, Any]:
    if _has_symlink(path, root):
        return {
            "artifactId": artifact_id,
            "status": "unsafe",
            "reasonCode": "LEC_RESULT_UNSAFE",
            "data": None,
        }
    if not path.is_file():
        return {
            "artifactId": artifact_id,
            "status": "missing",
            "reasonCode": "LEC_RESULT_MISSING",
            "data": None,
        }
    try:
        data = json_read_strict(path)
    except (OSError, JsonReadError):
        return {
            "artifactId": artifact_id,
            "status": "invalid",
            "reasonCode": "LEC_RESULT_INVALID",
            "data": None,
        }
    if not isinstance(data, dict):
        return {
            "artifactId": artifact_id,
            "status": "invalid",
            "reasonCode": "LEC_RESULT_INVALID",
            "data": None,
        }
    result = dict(data)
    result["freshness_status"] = _lec_freshness_status(data, root)
    return {"artifactId": artifact_id, "status": "available", "data": result}


def _lec_freshness_status(data: dict[str, Any], root: Path) -> str:
    if data.get("status") != "proven":
        return "incomplete"
    for role in ("golden", "gate"):
        path = data.get(f"{role}_verilog")
        digest = data.get(f"{role}_sha256")
        size = data.get(f"{role}_size_bytes")
        if not isinstance(path, str) or not isinstance(digest, str) or type(size) is not int:
            return "stale"
        candidate = Path(path).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return "stale"
        actual = file_digest(candidate)
        if actual is None or actual != (digest, size):
            return "stale"
    return "proven"


def _analysis_file(path: Path, artifact_id: str, schema_version: int, root: Path) -> dict[str, Any]:
    if _has_symlink(path, root):
        return {
            "artifactId": artifact_id,
            "status": "unsafe",
            "reasonCode": "ANALYSIS_REFERENCE_UNSAFE",
            "data": None,
        }
    if not path.is_file():
        return {
            "artifactId": artifact_id,
            "status": "missing",
            "reasonCode": "ANALYSIS_FILE_MISSING",
            "data": None,
        }
    try:
        data = json_read_strict(path)
    except (OSError, JsonReadError):
        return {
            "artifactId": artifact_id,
            "status": "invalid",
            "reasonCode": "ANALYSIS_FILE_INVALID",
            "data": None,
        }
    if not isinstance(data, dict):
        return {
            "artifactId": artifact_id,
            "status": "invalid",
            "reasonCode": "ANALYSIS_FILE_INVALID",
            "data": None,
        }
    if data.get("schema_version") != schema_version:
        return {
            "artifactId": artifact_id,
            "status": "unsupported",
            "reasonCode": "ANALYSIS_SCHEMA_UNSUPPORTED",
            "data": None,
        }
    return {"artifactId": artifact_id, "status": "available", "data": data}


def _subflow_summary(path: Path, root: Path) -> dict[str, Any]:
    if _has_symlink(path, root):
        return {"status": "unsafe", "steps": []}
    if not path.is_file():
        return {"status": "missing", "steps": []}
    try:
        if path.stat().st_size > _SUBFLOW_MAX_BYTES:
            return {"status": "oversized", "steps": []}
        data = json_read_strict(path)
    except (OSError, JsonReadError):
        return {"status": "invalid", "steps": []}
    raw_steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(raw_steps, list) or len(raw_steps) > _SUBFLOW_MAX_STEPS:
        return {"status": "invalid", "steps": []}
    steps: list[dict[str, Any]] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            return {"status": "invalid", "steps": []}
        name = item.get("name")
        state = item.get("state")
        if not isinstance(name, str) or not name or not isinstance(state, str):
            return {"status": "invalid", "steps": []}
        runtime = item.get("runtime")
        peak_memory = item.get("peak memory (mb)")
        step: dict[str, Any] = {"name": name, "state": state}
        if isinstance(runtime, str):
            step["runtime"] = runtime
        if (
            isinstance(peak_memory, (int, float))
            and not isinstance(peak_memory, bool)
            and math.isfinite(peak_memory)
        ):
            step["peakMemoryMb"] = peak_memory
        steps.append(step)
    return {"status": "available", "steps": steps}


def _artifact_ref(
    path: Path,
    *,
    workspace_id: str,
    reference: str,
    step_id: str,
    kind: str,
    root: Path,
) -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "artifactId": _artifact_id(workspace_id, reference),
        "kind": kind,
        "name": path.name,
        "stepId": step_id,
        "availability": "missing",
        "reference": reference,
    }
    try:
        if path.is_file() and not _has_symlink(path, root):
            size = path.stat().st_size
            if size <= _ARTIFACT_HASH_MAX_BYTES:
                artifact.update(
                    availability="available",
                    sizeBytes=size,
                    sha256=_sha256(path),
                )
            else:
                artifact.update(availability="stale", sizeBytes=size)
    except OSError:
        pass
    return artifact


def _safe_step_artifact_path(step_dir: Path, value: object, root: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = step_dir / candidate
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _safe_segment(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
    )


def _has_symlink(path: Path, root: Path) -> bool:
    current = path
    while current != root:
        if current.is_symlink():
            return True
        if current.parent == current:
            return True
        current = current.parent
    return False


def _artifact_id(workspace_id: str, reference: str) -> str:
    digest = hashlib.sha256(f"{workspace_id}\0{reference}".encode()).hexdigest()
    return f"artifact-{digest[:32]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
