from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from chipcompiler.data import StepEnum, Workspace
from chipcompiler.utility import json_read

STA_TEXT_REPORT_FILENAMES = (
    "qor_summary.rpt",
    "timing_max_in2out.rpt",
    "timing_max_in2reg.rpt",
    "timing_max_reg2out.rpt",
    "timing_max_reg2reg.rpt",
    "timing_min_in2out.rpt",
    "timing_min_in2reg.rpt",
    "timing_min_reg2out.rpt",
    "timing_min_reg2reg.rpt",
)
STA_QOR_SUMMARY_FILENAME = "qor_summary.json"
STA_TIMING_PATHS_FILENAME = "timing_paths.json"
STA_REPORT_FILENAMES = STA_TEXT_REPORT_FILENAMES


@dataclass(frozen=True)
class StaQorSummary:
    corner: str
    path: Path
    setup_wns: float
    setup_tns: float
    setup_nvp: int
    frequency_mhz: float
    hold_wns: float
    hold_tns: float
    hold_nvp: int


@dataclass(frozen=True)
class StaTimingPaths:
    corner: str
    path: Path
    path_limit: int
    paths: tuple[dict, ...]


def temperature_token(temperature) -> str:
    try:
        numeric = float(temperature)
        if numeric.is_integer():
            temperature = int(numeric)
    except (TypeError, ValueError):
        pass
    return str(temperature).replace("-", "m").replace(".", "p")


def _artifact_root(root) -> Path | None:
    if root is None or root == "":
        return None
    try:
        return Path(root)
    except TypeError:
        return None


def _safe_dir_name(name: str) -> str:
    value = "".join(
        character if character.isalnum() or character in ("-", "_", ".") else "_"
        for character in name.strip()
    )
    return value or "unknown"


def sta_artifact_directory(
    root,
    corner_name: str,
    temperature,
    rcx_corner_name: str,
) -> Path | None:
    artifact_root = _artifact_root(root)
    if artifact_root is None:
        return None
    report_corner_dir = f"{corner_name}_{temperature_token(temperature)}"
    return artifact_root / _safe_dir_name(report_corner_dir) / _safe_dir_name(rcx_corner_name)


def configured_sta_artifact_directories(workspace: Workspace,
                                        root) -> list[tuple[str, Path]]:
    sta_data = json_read(workspace.config.get(StepEnum.STA.value, ""))
    if not isinstance(sta_data, dict):
        return []

    artifact_root = _artifact_root(root)
    if artifact_root is None:
        return []

    liberty_by_corner = {
        liberty.get("corner"): liberty
        for liberty in sta_data.get("liberty", [])
        if isinstance(liberty, dict) and isinstance(liberty.get("corner"), str)
    }
    report_directories = []
    seen_paths = set()
    for signoff_group in sta_data.get("signoff", []):
        if not isinstance(signoff_group, dict):
            continue
        for corner_name, rcx_corner_names in signoff_group.items():
            liberty = liberty_by_corner.get(corner_name)
            if liberty is None:
                continue

            if isinstance(rcx_corner_names, str):
                rcx_corner_names = [rcx_corner_names]
            if not isinstance(rcx_corner_names, list):
                continue

            for rcx_corner_name in rcx_corner_names:
                if not isinstance(rcx_corner_name, str):
                    continue
                artifact_dir = sta_artifact_directory(
                    artifact_root,
                    corner_name,
                    liberty.get("temperature"),
                    rcx_corner_name,
                )
                if artifact_dir is None or artifact_dir in seen_paths:
                    continue
                seen_paths.add(artifact_dir)
                report_directories.append((
                    artifact_dir.relative_to(artifact_root).as_posix(),
                    artifact_dir,
                ))

    return report_directories


def _artifact_paths(workspace: Workspace, root, filename: str) -> list[tuple[str, Path]]:
    directories = configured_sta_artifact_directories(workspace, root)
    if directories:
        return [(corner, artifact_dir / filename) for corner, artifact_dir in directories]

    artifact_root = _artifact_root(root)
    if artifact_root is None or not artifact_root.is_dir():
        return []

    paths = []
    for path in sorted(artifact_root.rglob(filename)):
        try:
            corner = path.parent.relative_to(artifact_root).as_posix()
        except ValueError:
            corner = path.parent.name
        paths.append((corner, path))
    return paths


def sta_qor_summary_paths(workspace: Workspace, feature_root) -> list[tuple[str, Path]]:
    return _artifact_paths(workspace, feature_root, STA_QOR_SUMMARY_FILENAME)


def sta_timing_paths_paths(workspace: Workspace,
                           feature_root) -> list[tuple[str, Path]]:
    return _artifact_paths(workspace, feature_root, STA_TIMING_PATHS_FILENAME)


def sta_report_artifact_paths(workspace: Workspace,
                              report_root) -> list[tuple[str, Path]]:
    report_directories = configured_sta_artifact_directories(workspace, report_root)
    return [
        (corner, artifact_dir / report_name)
        for corner, artifact_dir in report_directories
        for report_name in STA_REPORT_FILENAMES
    ]


def _finite_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _nonnegative_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def read_sta_qor_summary(corner: str, path: Path) -> StaQorSummary | None:
    if not path.is_file() or path.stat().st_size <= 0:
        return None

    data = json_read(path)
    if not isinstance(data, dict) or not isinstance(data.get("path_groups"), list):
        return None

    summary = data.get("summary")
    if not isinstance(summary, dict):
        return None
    setup = summary.get("setup")
    hold = summary.get("hold")
    if not isinstance(setup, dict) or not isinstance(hold, dict):
        return None

    setup_wns = _finite_number(setup.get("wns"))
    setup_tns = _finite_number(setup.get("tns"))
    setup_nvp = _nonnegative_int(setup.get("nvp"))
    frequency_mhz = _finite_number(setup.get("frequency_mhz"))
    hold_wns = _finite_number(hold.get("wns"))
    hold_tns = _finite_number(hold.get("tns"))
    hold_nvp = _nonnegative_int(hold.get("nvp"))
    if (
        setup_wns is None
        or setup_tns is None
        or setup_nvp is None
        or frequency_mhz is None
        or frequency_mhz <= 0
        or hold_wns is None
        or hold_tns is None
        or hold_nvp is None
    ):
        return None

    return StaQorSummary(
        corner=corner,
        path=path,
        setup_wns=setup_wns,
        setup_tns=setup_tns,
        setup_nvp=setup_nvp,
        frequency_mhz=frequency_mhz,
        hold_wns=hold_wns,
        hold_tns=hold_tns,
        hold_nvp=hold_nvp,
    )


def _is_valid_timing_path_number(value) -> bool:
    return value is None or _finite_number(value) is not None


def read_sta_timing_paths(corner: str, path: Path) -> StaTimingPaths | None:
    if not path.is_file() or path.stat().st_size <= 0:
        return None

    data = json_read(path)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return None
    if data.get("corner") != corner:
        return None
    path_limit = data.get("path_limit")
    if isinstance(path_limit, bool) or not isinstance(path_limit, int) or path_limit < 0:
        return None
    paths = data.get("paths")
    if not isinstance(paths, list):
        return None

    required_strings = (
        "path_id",
        "path_group",
        "start_point",
        "end_point",
        "launch_clock",
        "capture_clock",
        "check_type",
    )
    seen_ids = set()
    valid_paths = []
    for timing_path in paths:
        if not isinstance(timing_path, dict):
            return None
        if timing_path.get("analysis_type") not in ("setup", "hold"):
            return None
        if any(
            not isinstance(timing_path.get(field), str) or not timing_path[field]
            for field in required_strings
        ):
            return None
        path_id = timing_path["path_id"]
        if path_id in seen_ids:
            return None
        seen_ids.add(path_id)
        if not all(
            _is_valid_timing_path_number(timing_path.get(field))
            for field in (
                "slack_ns",
                "arrival_ns",
                "required_ns",
                "cppr_ns",
                "launch_clock_network_delay_ns",
                "capture_clock_network_delay_ns",
            )
        ):
            return None
        if _finite_number(timing_path.get("slack_ns")) is None:
            return None
        stages = timing_path.get("stages")
        if not isinstance(stages, list):
            return None
        for stage in stages:
            if not isinstance(stage, dict):
                return None
            if any(
                not isinstance(stage.get(field), str)
                for field in ("kind", "pin", "instance", "cell", "transition")
            ):
                return None
            if not all(
                _is_valid_timing_path_number(stage.get(field))
                for field in ("incremental_delay_ns", "arrival_ns")
            ):
                return None
        valid_paths.append(timing_path)

    return StaTimingPaths(
        corner=corner,
        path=path,
        path_limit=path_limit,
        paths=tuple(valid_paths),
    )
