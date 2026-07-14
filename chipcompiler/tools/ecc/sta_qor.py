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
STA_REPORT_FILENAMES = (*STA_TEXT_REPORT_FILENAMES, STA_QOR_SUMMARY_FILENAME)


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


def temperature_token(temperature) -> str:
    try:
        numeric = float(temperature)
        if numeric.is_integer():
            temperature = int(numeric)
    except (TypeError, ValueError):
        pass
    return str(temperature).replace("-", "m").replace(".", "p")


def _output_root(output_dir) -> Path | None:
    if output_dir is None or output_dir == "":
        return None
    try:
        return Path(output_dir)
    except TypeError:
        return None


def configured_sta_report_directories(workspace: Workspace,
                                      output_dir) -> list[tuple[str, Path]]:
    sta_data = json_read(workspace.config.get(StepEnum.STA.value, ""))
    if not isinstance(sta_data, dict):
        return []

    root = _output_root(output_dir)
    if root is None:
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

            report_corner_dir = "{}_{}".format(
                corner_name,
                temperature_token(liberty.get("temperature")),
            )
            for rcx_corner_name in rcx_corner_names:
                if not isinstance(rcx_corner_name, str):
                    continue
                report_dir = root / report_corner_dir / rcx_corner_name
                if report_dir in seen_paths:
                    continue
                seen_paths.add(report_dir)
                report_directories.append((
                    f"{report_corner_dir}/{rcx_corner_name}",
                    report_dir,
                ))

    return report_directories


def sta_qor_summary_paths(workspace: Workspace,
                           output_dir) -> list[tuple[str, Path]]:
    report_directories = configured_sta_report_directories(workspace, output_dir)
    if report_directories:
        return [
            (corner, report_dir / STA_QOR_SUMMARY_FILENAME)
            for corner, report_dir in report_directories
        ]

    root = _output_root(output_dir)
    if root is None or not root.is_dir():
        return []

    paths = []
    for path in sorted(root.rglob(STA_QOR_SUMMARY_FILENAME)):
        try:
            corner = path.parent.relative_to(root).as_posix()
        except ValueError:
            corner = path.parent.name
        paths.append((corner, path))
    return paths


def sta_report_artifact_paths(workspace: Workspace,
                              output_dir) -> list[tuple[str, Path]]:
    report_directories = configured_sta_report_directories(workspace, output_dir)
    if not report_directories:
        report_directories = [
            (corner, path.parent)
            for corner, path in sta_qor_summary_paths(workspace, output_dir)
        ]

    return [
        (corner, report_dir / report_name)
        for corner, report_dir in report_directories
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
