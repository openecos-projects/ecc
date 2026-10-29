"""Clock-tree visualization capture policy shared by ECC stage handlers."""

import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

from chipcompiler.data import StepEnum
from chipcompiler.data.workspace.flow_options import clock_tree_requested

CLOCK_TREE_STAGE_BY_STEP = {
    StepEnum.POST_FLOORPLAN.value: "postFloorplan",
    StepEnum.CTS.value: "CTS",
    StepEnum.FILLER.value: "filler",
}

FILLER_RC_CORNER = "TYPICAL"
FILLER_LIBERTY_CORNER = "TYP"
FILLER_TEMPERATURE_C = 25.0


class ClockTreeCaptureError(RuntimeError):
    """Raised when the filler clock analysis cannot produce a valid graph."""


def clock_tree_stage_for_step(workspace, step_name: str) -> str | None:
    """Return the native snapshot stage, or None when capture is disabled."""
    if not clock_tree_requested(workspace):
        return None
    return CLOCK_TREE_STAGE_BY_STEP.get(step_name)


def _clock_tree_dir(workspace, step) -> Path:
    if step.directory is not None:
        return Path(step.directory) / "data" / "clock_tree"
    filler_dir = (step.data.steps or {}).get(StepEnum.FILLER.value)
    if filler_dir is not None:
        return Path(filler_dir).parent / "clock_tree"
    return Path(workspace.directory) / "filler_ecc" / "data" / "clock_tree"


def _sta_config_path(workspace) -> Path:
    configured = (workspace.config or {}).get(StepEnum.STA.value)
    if configured is not None:
        return Path(configured)
    from chipcompiler.data.workspace import workspace_config_key_path

    resolved = workspace_config_key_path(workspace.directory, StepEnum.STA.value)
    if resolved is None:
        raise ClockTreeCaptureError("STA config is not available")
    return resolved


def _select_typ_liberty(sta_config: Path) -> tuple[list[str], str, float]:
    try:
        payload = json.loads(sta_config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClockTreeCaptureError(f"cannot read STA config {sta_config}: {exc}") from exc
    matches = [
        entry
        for entry in payload.get("liberty", [])
        if isinstance(entry, dict)
        and str(entry.get("corner", "")).upper() == FILLER_LIBERTY_CORNER
        and math.isclose(
            float(entry.get("temperature", math.nan)),
            FILLER_TEMPERATURE_C,
            rel_tol=0.0,
            abs_tol=1.0e-6,
        )
    ]
    if len(matches) != 1:
        raise ClockTreeCaptureError(
            f"STA config {sta_config} must contain exactly one {FILLER_LIBERTY_CORNER} "
            f"Liberty at {FILLER_TEMPERATURE_C:g}°C; found {len(matches)}"
        )
    entry = matches[0]
    paths = entry.get("path", [])
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths:
        raise ClockTreeCaptureError(
            f"STA {FILLER_LIBERTY_CORNER} Liberty at {FILLER_TEMPERATURE_C:g}°C has no paths"
        )
    missing = [path for path in paths if not isinstance(path, str) or not Path(path).is_file()]
    if missing:
        raise ClockTreeCaptureError(
            f"STA {FILLER_LIBERTY_CORNER} Liberty is missing: {missing}"
        )
    return list(paths), str(entry.get("corner", FILLER_LIBERTY_CORNER)), float(entry["temperature"])


def _temperature_matches(filename: str, temperature_c: float) -> bool:
    token = f"{temperature_c:g}"
    pattern = rf"(?<![0-9.]){re.escape(token)}(?:\.0+)?(?:C)?(?![0-9.])"
    return re.search(pattern, filename.upper()) is not None


def _select_typical_spef(output_dir: Path, temperature_c: float) -> Path:
    spef_dir = output_dir / "spef_writer"
    candidates = sorted(spef_dir.glob("*.spef"))
    matches = [
        path
        for path in candidates
        if FILLER_RC_CORNER in path.name.upper() and _temperature_matches(path.name, temperature_c)
    ]
    if len(matches) != 1:
        raise ClockTreeCaptureError(
            f"RCX output {spef_dir} must contain exactly one {FILLER_RC_CORNER} "
            f"{temperature_c:g}°C SPEF; found {[path.name for path in matches]}"
        )
    spef = matches[0]
    if not spef.is_file() or spef.stat().st_size <= 0:
        raise ClockTreeCaptureError(f"selected SPEF is empty: {spef}")
    header = "\n".join(spef.read_text(encoding="utf-8", errors="replace").splitlines()[:200])
    if "*SPEF" not in header or "*T_UNIT" not in header:
        raise ClockTreeCaptureError(f"selected SPEF has no SPEF header or time unit: {spef}")
    return spef


def _prepare_rcx_config(clock_tree_dir: Path) -> tuple[Path, Path]:
    rcx_dir = clock_tree_dir / "rcx"
    shutil.rmtree(rcx_dir, ignore_errors=True)
    rcx_dir.mkdir(parents=True, exist_ok=True)
    config_path = clock_tree_dir / "rcx_config.json"
    config_path.write_text(
        json.dumps({"thread_num": 64, "output": str(rcx_dir.resolve())}, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path, rcx_dir


def _run_rcx(workspace, ecc_module, config_path: Path) -> None:
    pdk = workspace.pdk.name or "ics55"
    initialized = False
    try:
        if ecc_module.init_rcx(config=config_path, pdk=pdk) is False:
            raise ClockTreeCaptureError("filler clock-tree RCX initialization failed")
        initialized = True
        if ecc_module.run_rcx() is False:
            raise ClockTreeCaptureError("filler clock-tree RCX extraction failed")
    finally:
        if initialized:
            ecc_module.destroy_rcx()


def _run_ista_clock_graph(
    ecc_module,
    *,
    sta_config: Path,
    liberty_paths: list[str],
    sdc_path: Path,
    spef_path: Path,
    work_dir: Path,
) -> dict[str, Any]:
    ecc = ecc_module.get_ecc()
    if getattr(ecc, "sta_clock_graph", None) is None:
        raise ClockTreeCaptureError("installed ecc-tools does not expose sta_clock_graph")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    if ecc.lib_init(lib_paths=liberty_paths) is not True:
        raise ClockTreeCaptureError("filler clock-tree Liberty initialization failed")
    if ecc.sdc_init(str(sdc_path)) is not True:
        raise ClockTreeCaptureError("filler clock-tree SDC initialization failed")
    if ecc.spef_init(str(spef_path)) is not True:
        raise ClockTreeCaptureError("filler clock-tree SPEF initialization failed")
    config_dict = {
        "-temp_directory_path": str(work_dir.resolve()),
        "-output_timing_reports": "0",
        "-output_timing_features": "0",
        "-timing_corner": FILLER_LIBERTY_CORNER,
        "-thread_number": "64",
    }
    if ecc.init_sta(config=str(sta_config), config_dict=config_dict) is not True:
        raise ClockTreeCaptureError("filler clock-tree STA initialization failed")
    try:
        if ecc.run_sta() is not True:
            raise ClockTreeCaptureError("filler clock-tree STA execution failed")
        graph = ecc.sta_clock_graph()
    finally:
        ecc.destroy_sta()
    if not isinstance(graph, dict):
        raise ClockTreeCaptureError("filler clock-tree STA returned no graph")
    return graph


def capture_filler_clock_tree(workspace, step, ecc_module) -> dict[str, Any] | None:
    """Extract TYPICAL parasitics and export iSTA timing for the filler stage."""
    if clock_tree_stage_for_step(workspace, step.name) != "filler":
        return None

    clock_tree_dir = _clock_tree_dir(workspace, step)
    clock_tree_dir.mkdir(parents=True, exist_ok=True)
    sta_config = _sta_config_path(workspace)
    liberty_paths, liberty_corner, temperature_c = _select_typ_liberty(sta_config)
    sdc_path = Path(workspace.pdk.sdc) if workspace.pdk.sdc else None
    if sdc_path is None or not sdc_path.is_file():
        raise ClockTreeCaptureError(f"filler clock-tree SDC does not exist: {sdc_path}")

    rcx_config, rcx_dir = _prepare_rcx_config(clock_tree_dir)
    _run_rcx(workspace, ecc_module, rcx_config)
    spef_path = _select_typical_spef(rcx_dir, temperature_c)
    graph = _run_ista_clock_graph(
        ecc_module,
        sta_config=sta_config,
        liberty_paths=liberty_paths,
        sdc_path=sdc_path,
        spef_path=spef_path,
        work_dir=clock_tree_dir / "sta",
    )

    diagnostics = list(graph.get("diagnostics", []))
    diagnostics.append(
        f"filler clock timing source: RC={FILLER_RC_CORNER}, Liberty={liberty_corner}, "
        f"temperature={temperature_c:g}°C, SPEF={spef_path.name}"
    )
    graph.update(
        {
            "stage": "filler",
            "analysis_source": "ista_typical",
            "rc_corner": FILLER_RC_CORNER,
            "liberty_corner": liberty_corner,
            "temperature_c": temperature_c,
            "diagnostics": diagnostics,
        }
    )
    return graph
