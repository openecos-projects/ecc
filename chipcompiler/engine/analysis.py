"""Workspace artifact index and bounded projections for the Engineering Snapshot.

The Snapshot never inlines payload content and never hashes artifact files:
the artifact index carries identity and availability only, and overview data
is projected into bounded top-N shapes. Authoritative content always remains
in the workspace files.
"""

import hashlib
import math
from pathlib import Path
from typing import Any, TypeGuard

from chipcompiler.data import LEC_STEP_TOOLS
from chipcompiler.data.step import STEP_DIRECTORIES, flow_step_directory, step_storage_name
from chipcompiler.engine.qor import collect_metric_records
from chipcompiler.tools.ecc.power_artifacts import (
    workspace_power_report_path,
    workspace_power_summary_path,
)
from chipcompiler.tools.ecc.sta_qor import STA_REPORT_FILENAMES
from chipcompiler.utility import JsonReadError, json_read_strict

_ANALYSIS_FILES = (
    ("qor_metrics", "qor_metrics.json"),
    ("qor_summary", "qor_summary.json"),
    ("qor_hotspots", "qor_hotspots.json"),
)
_TIMING_ISSUES_KIND = "sta_timing_issues"
_TIMING_ISSUES_FILENAME = "sta_timing_issues.json"
_TIMING_PREVIEW_ISSUE_LIMIT = 5
_HOTSPOT_PREVIEW_LIMIT = 5
_HOTSPOT_SEVERITY_RANK = {"critical": 0, "warning": 1}
_STA_CORNER_LIMIT = 32
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


def collect_workspace_projections(workspace: Any, workspace_id: str) -> dict[str, Any]:
    """Build the pure artifact index and the bounded metrics/timing/hotspot projections.

    Metrics and previews are collected from Success steps only, so a failed or
    reset step never contributes stale records to the committed projection.
    """
    root = Path(workspace.directory).resolve()
    flow = getattr(getattr(workspace, "flow", None), "data", {})
    raw_steps = flow.get("steps", []) if isinstance(flow, dict) else []
    design = str(getattr(getattr(workspace, "design", None), "name", "")).strip()
    artifacts: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    hotspots: list[dict[str, Any]] = []
    timing_preview = _empty_timing_preview()
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            continue
        step_id = raw_step.get("name")
        tool_id = raw_step.get("tool")
        if not _safe_segment(step_id) or not _safe_segment(tool_id):
            continue
        identity = "".join(character for character in step_id.casefold() if character.isalnum())
        if identity == "fixfanout":
            continue
        if tool_id in LEC_STEP_TOOLS:
            step_dir = root / flow_step_directory(raw_steps, step_id)
        else:
            step_dir = root / STEP_DIRECTORIES.get(
                step_id, f"{step_storage_name(step_id, tool_id)}_{tool_id}"
            )
        analysis_dir = step_dir / "analysis"
        for kind, filename in _ANALYSIS_FILES:
            artifacts.append(
                _artifact_ref(
                    analysis_dir / filename,
                    workspace_id=workspace_id,
                    step_id=step_id,
                    kind=kind,
                    root=root,
                )
            )
        succeeded = str(raw_step.get("state", "")) == "Success"
        if succeeded:
            metrics.extend(
                collect_metric_records(_read_analysis_json(analysis_dir / "qor_metrics.json", root))
            )
            hotspots.extend(
                _step_hotspots(
                    step_id, _read_analysis_json(analysis_dir / "qor_hotspots.json", root)
                )
            )
        if step_id.lower() == "sta":
            timing_path = analysis_dir / _TIMING_ISSUES_FILENAME
            artifacts.append(
                _artifact_ref(
                    timing_path,
                    workspace_id=workspace_id,
                    step_id=step_id,
                    kind=_TIMING_ISSUES_KIND,
                    root=root,
                )
            )
            if succeeded:
                timing_preview = _timing_preview(_read_analysis_json(timing_path, root))
        if tool_id in LEC_STEP_TOOLS and design:
            artifacts.append(
                _artifact_ref(
                    step_dir / "output" / f"{design}_{step_id}_result.json",
                    workspace_id=workspace_id,
                    step_id=step_id,
                    kind="lec_result",
                    root=root,
                )
            )
        if step_id.lower() == "rcx":
            artifacts.append(
                _artifact_ref(
                    step_dir / "feature" / f"{step_id}.step.json",
                    workspace_id=workspace_id,
                    step_id=step_id,
                    kind="rcx_feature_facts",
                    root=root,
                )
            )
        if design:
            artifacts.append(
                _artifact_ref(
                    step_dir / "output" / f"{design}_{step_id}.png",
                    workspace_id=workspace_id,
                    step_id=step_id,
                    kind="layout_image",
                    root=root,
                )
            )
            if step_id.lower() == "harden":
                for suffix in ("gds", "lef", "lib"):
                    artifacts.append(
                        _artifact_ref(
                            step_dir / "output" / f"{design}_{step_id}.{suffix}",
                            workspace_id=workspace_id,
                            step_id=step_id,
                            kind="harden_output",
                            root=root,
                        )
                    )
        artifacts.append(
            _artifact_ref(
                step_dir / "output" / "geometry" / "geometry.manifest",
                workspace_id=workspace_id,
                step_id=step_id,
                kind="layout_geometry",
                root=root,
            )
        )
        artifacts.append(
            _artifact_ref(
                step_dir / "subflow.json",
                workspace_id=workspace_id,
                step_id=step_id,
                kind="subflow",
                root=root,
            )
        )
        report_names = (
            (f"{step_id}_stat.json", f"{step_id}_check.rpt")
            if tool_id.lower() == "yosys"
            else ("run_lec_status.rpt", "equiv_status.rpt")
            if tool_id.lower() == "yosys_lec"
            else (f"{step_id}.db.rpt", f"{step_id}.rpt")
        )
        for report_name in report_names:
            artifacts.append(
                _artifact_ref(
                    step_dir / "report" / report_name,
                    workspace_id=workspace_id,
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
        if step_id.lower() == "sta":
            for relative_corner, feature_dir in _sta_corner_directories(step_dir, root):
                report_dir = step_dir / "report" / relative_corner
                for report_name in STA_REPORT_FILENAMES:
                    artifact = _artifact_ref(
                        report_dir / report_name,
                        workspace_id=workspace_id,
                        step_id=step_id,
                        kind="report_text",
                        root=root,
                    )
                    artifact["name"] = (relative_corner / report_name).as_posix()
                    artifacts.append(artifact)
                timing_files.extend(
                    (
                        ("timing_summary", feature_dir / "qor_summary.json"),
                        ("timing_paths", feature_dir / "timing_paths.json"),
                    )
                )
        if step_id == "powerAnalysis":
            timing_files.extend(
                (
                    ("power_report", workspace_power_report_path(root)),
                    ("power_summary", workspace_power_summary_path(root)),
                )
            )
        for kind, path in timing_files:
            artifact = _artifact_ref(
                path,
                workspace_id=workspace_id,
                step_id=step_id,
                kind=kind,
                root=root,
            )
            if step_id.lower() == "sta":
                artifact["name"] = path.relative_to(step_dir / "feature").as_posix()
            artifacts.append(artifact)
        if step_id.lower() in {"place", "cts"}:
            for directory, filename in _CONGESTION_IMAGES:
                artifacts.append(
                    _artifact_ref(
                        step_dir / "feature" / directory / filename.format(step=step_id),
                        workspace_id=workspace_id,
                        step_id=step_id,
                        kind="congestion_image",
                        root=root,
                    )
                )
    checklist_artifact = _artifact_ref(
        root / "home" / "checklist.json",
        workspace_id=workspace_id,
        step_id="",
        kind="checklist",
        root=root,
    )
    if checklist_artifact["availability"] == "available":
        artifacts.append(checklist_artifact)
    return {
        "artifacts": artifacts,
        "metrics": metrics,
        "timingPreview": timing_preview,
        "hotspotPreview": _hotspot_preview(hotspots),
    }


def _read_analysis_json(path: Path, root: Path) -> dict[str, Any] | None:
    if _has_symlink(path, root):
        return None
    try:
        data = json_read_strict(path)
    except (OSError, JsonReadError):
        return None
    return data if isinstance(data, dict) else None


def _empty_timing_preview() -> dict[str, Any]:
    return {"issues": [], "issueCount": 0, "issuesTruncated": False}


def _timing_preview(data: dict[str, Any] | None) -> dict[str, Any]:
    if data is None or data.get("schema_version") != 1:
        return _empty_timing_preview()
    raw_issues = data.get("issues")
    if not isinstance(raw_issues, list):
        return _empty_timing_preview()
    issues = [issue for issue in raw_issues if isinstance(issue, dict)]
    issues.sort(key=_timing_issue_sort_key)
    return {
        "issues": [_scalar_fields(issue) for issue in issues[:_TIMING_PREVIEW_ISSUE_LIMIT]],
        "issueCount": len(issues),
        "issuesTruncated": len(issues) > _TIMING_PREVIEW_ISSUE_LIMIT,
    }


def _timing_issue_sort_key(issue: dict[str, Any]) -> tuple:
    slack = issue.get("slack_ns")
    if isinstance(slack, bool) or not isinstance(slack, (int, float)) or not math.isfinite(slack):
        slack = math.inf
    return (
        slack,
        str(issue.get("corner", "")),
        str(issue.get("analysis_type", "")),
        str(issue.get("issue_id", "")),
    )


def _step_hotspots(step_id: str, data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if data is None or data.get("schema_version") != 3:
        return []
    raw_hotspots = data.get("hotspots")
    if not isinstance(raw_hotspots, list):
        return []
    return [
        {"stepId": step_id, **_scalar_fields(hotspot)}
        for hotspot in raw_hotspots
        if isinstance(hotspot, dict)
    ]


def _hotspot_preview(hotspots: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        hotspots,
        key=lambda hotspot: _HOTSPOT_SEVERITY_RANK.get(
            str(hotspot.get("severity")), len(_HOTSPOT_SEVERITY_RANK)
        ),
    )
    return {
        "hotspots": ranked[:_HOTSPOT_PREVIEW_LIMIT],
        "hotspotCount": len(ranked),
        "hotspotsTruncated": len(ranked) > _HOTSPOT_PREVIEW_LIMIT,
    }


def _scalar_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }


def _artifact_ref(
    path: Path,
    *,
    workspace_id: str,
    step_id: str,
    kind: str,
    root: Path,
) -> dict[str, Any]:
    reference = path.relative_to(root).as_posix()
    artifact: dict[str, Any] = {
        "artifactId": _artifact_id(workspace_id, reference),
        "kind": kind,
        "name": path.name,
        "stepId": step_id,
        "reference": reference,
        "availability": "missing",
    }
    try:
        if path.is_file() and not _has_symlink(path, root):
            artifact["availability"] = "available"
    except OSError:
        pass
    return artifact


def _sta_corner_directories(step_dir: Path, root: Path) -> list[tuple[Path, Path]]:
    feature_root = step_dir / "feature"
    if not feature_root.is_dir() or _has_symlink(feature_root, root):
        return []
    try:
        process_directories = sorted(feature_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return []
    corners: list[tuple[Path, Path]] = []
    for process_dir in process_directories:
        if (
            len(corners) >= _STA_CORNER_LIMIT
            or not _safe_segment(process_dir.name)
            or not process_dir.is_dir()
            or _has_symlink(process_dir, root)
        ):
            continue
        try:
            rc_directories = sorted(process_dir.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for rc_dir in rc_directories:
            if not _safe_segment(rc_dir.name) or not rc_dir.is_dir() or _has_symlink(rc_dir, root):
                continue
            if not any(
                (rc_dir / filename).is_file()
                for filename in ("qor_summary.json", "timing_paths.json")
            ):
                continue
            corners.append((Path(process_dir.name) / rc_dir.name, rc_dir))
            if len(corners) >= _STA_CORNER_LIMIT:
                return corners
    return corners


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
