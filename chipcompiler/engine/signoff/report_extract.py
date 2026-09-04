"""Parsers and alias-based metric lookup for the design-summary report."""

import dataclasses
import re
from pathlib import Path

from chipcompiler.data import StepEnum
from chipcompiler.engine.signoff.report_data import (
    DesignReportData,
    EvidenceProvenanceRecord,
    ParsedPowerMetrics,
    ParsedQorSummaryMetrics,
    canonicalize_stage_name,
)
from chipcompiler.utility.json import json_read

# ---------------------------------------------------------------------------
# Small parsers (direct ports)
# ---------------------------------------------------------------------------


def parse_runtime_seconds(runtime) -> float | None:
    if isinstance(runtime, bool):
        return None
    if isinstance(runtime, (int, float)):
        return float(runtime)
    if not isinstance(runtime, str) or not runtime.strip():
        return None
    parts = runtime.split(":")
    try:
        numbers = [float(part.strip()) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 1:
        return numbers[0]
    return None


def format_duration(seconds: float | None) -> str | None:
    if seconds is None or seconds != seconds or seconds < 0:
        return None
    total = int(round(seconds))
    hrs, mins, secs = total // 3600, (total % 3600) // 60, total % 60
    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def _convert_unit_to_mw(val: float, unit_str: str) -> float:
    unit = unit_str.lower()
    if unit == "w":
        return val * 1000
    if unit == "mw":
        return val
    if unit in ("uw", "µw"):
        return val / 1000
    if unit == "nw":
        return val / 1e6
    if unit == "pw":
        return val / 1e9
    return val


def parse_power_rpt(text: str | None) -> ParsedPowerMetrics:
    parsed = ParsedPowerMetrics()
    if not text:
        return parsed

    voltage = re.search(r"Global Operating Voltage\s*=\s*([\d.]+)", text, re.IGNORECASE)
    if voltage:
        parsed.voltage_v = float(voltage.group(1))

    patterns = (
        ("internal", r"Cell Internal Power\s*=\s*([\d.e+-]+)\s*([uUnNmMgk]?W)"),
        ("switching", r"Net Switching Power\s*=\s*([\d.e+-]+)\s*([uUnNmMgk]?W)"),
        ("dynamic", r"Total Dynamic Power\s*=\s*([\d.e+-]+)\s*([uUnNmMgk]?W)"),
        ("leakage", r"Cell Leakage Power\s*=\s*([\d.e+-]+)\s*([uUnNmMgk]?W)"),
        (
            "total",
            r"Total\s+[\d.e+-]+\s*[a-zA-Z]+\s+[\d.e+-]+\s*[a-zA-Z]+\s+[\d.e+-]+\s*[a-zA-Z]+\s+"
            r"([\d.e+-]+)\s*([uUnNmMgk]?W)",
        ),
    )
    for field, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            setattr(
                parsed,
                f"{field}_power_mw" if field != "total" else "total_power_mw",
                _convert_unit_to_mw(float(match.group(1)), match.group(2)),
            )
    if parsed.total_power_mw is None and (
        parsed.dynamic_power_mw is not None or parsed.leakage_power_mw is not None
    ):
        parsed.total_power_mw = round(
            (parsed.dynamic_power_mw or 0) + (parsed.leakage_power_mw or 0), 4
        )
    return parsed


def parse_qor_summary_rpt(text: str | None) -> ParsedQorSummaryMetrics:
    if not text:
        return ParsedQorSummaryMetrics()
    for line in text.splitlines():
        trimmed = line.strip()
        if not (trimmed.startswith("Summary") or trimmed.startswith("clk")):
            continue
        parts = trimmed.split()
        if len(parts) < 8:
            continue
        try:
            values = (
                float(parts[1]),
                float(parts[2]),
                float(parts[3]),
                float(re.sub(r"mhz", "", parts[4], flags=re.IGNORECASE)),
                float(parts[5]),
                float(parts[6]),
                float(parts[7]),
            )
        except ValueError:
            continue
        return ParsedQorSummaryMetrics(*values)
    return ParsedQorSummaryMetrics()


# ---------------------------------------------------------------------------
# Alias-based metric lookup (port of findMetricInRecord + queryMetric)
# ---------------------------------------------------------------------------


def _is_record(val) -> bool:
    return isinstance(val, dict)


def _norm_key(key: str) -> str:
    return re.sub(r"[\s_-]", "", key.lower())


def _get_nested_value(obj: dict, path_str: str):
    current = obj
    for part in path_str.split("."):
        if not _is_record(current):
            return None
        if part in current and current[part] is not None:
            current = current[part]
            continue
        norm_part = _norm_key(part)
        for key in current:
            if _norm_key(key) == norm_part:
                current = current[key]
                break
        else:
            return None
    return current


def _find_metric_in_record(metrics_record, aliases, stage_name):
    if not _is_record(metrics_record):
        return None

    metrics = metrics_record.get("metrics")
    if isinstance(metrics, list):  # schema 3 array format
        for item in metrics:
            if not _is_record(item):
                continue
            item_id = _norm_key(item.get("id", "") or "")
            display_name = _norm_key(item.get("display_name", "") or "")
            for alias in aliases:
                norm_alias = _norm_key(alias)
                if (item_id == norm_alias or display_name == norm_alias) and item.get(
                    "value"
                ) is not None:
                    return item.get("value"), item.get("id") or alias, stage_name

    for alias in aliases:  # direct root keys
        if metrics_record.get(alias) is not None:
            return metrics_record[alias], alias, stage_name

    for alias in aliases:  # dotted paths
        if "." in alias:
            nested = _get_nested_value(metrics_record, alias)
            if nested is not None:
                return nested, alias, stage_name

    for key, val in metrics_record.items():  # one-level nested objects
        if _is_record(val):
            for alias in aliases:
                if val.get(alias) is not None:
                    return val[alias], f"{key}.{alias}", stage_name

    for alias in aliases:  # normalized root keys
        norm_alias = _norm_key(alias)
        for key, val in metrics_record.items():
            if _norm_key(key) == norm_alias and val is not None:
                return val, key, stage_name

    return None


def _parse_number(val) -> float | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if _is_record(val) and "value" in val:
        return _parse_number(val["value"])
    if isinstance(val, str) and val.strip():
        try:
            return float(val.replace(",", "").strip())
        except ValueError:
            return None
    return None


class StepMetricStore:
    """Merged per-stage metric payloads with provenance-tracking queries."""

    def __init__(self) -> None:
        self._stages: dict[str, dict] = {}

    def add(self, stage: str, payload: dict) -> None:
        if not _is_record(payload):
            return
        for key in (stage, canonicalize_stage_name(stage)):
            self._stages.setdefault(key, {}).update(payload)

    def stage(self, name: str) -> dict | None:
        return self._stages.get(name)

    def query(self, category, display_name, stage_priority, aliases, unit="", provenance=None):
        """Return (value, stage, source_key); falls back to parameters/home."""
        for stage in stage_priority:
            step_data = self._stages.get(stage)
            if not step_data:
                continue
            finding = _find_metric_in_record(step_data, aliases, stage)
            if finding is not None:
                number = _parse_number(finding[0])
                if number is not None:
                    if provenance is not None:
                        provenance.append(
                            EvidenceProvenanceRecord(
                                category=category,
                                metric=display_name,
                                value=number,
                                unit=unit,
                                status="VERIFIED",
                                stage=finding[2],
                                corner=None,
                                tool=stage,
                                source_metric_id=finding[1],
                                run_id=self.run_id or "run_latest",
                                timestamp=self.timestamp,
                            )
                        )
                    return number, finding[2], finding[1]
        return None, "", ""

    run_id: str | None = None
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _first_str(*candidates):
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _query(
    store, params, home, provenance, category, display_name, stage_priority, aliases, unit=""
):
    """queryMetric: stage sweep, then parameters/home fallback (CONFIGURED)."""
    value, stage, source_key = store.query(
        category, display_name, stage_priority, aliases, unit, provenance
    )
    if value is not None:
        return value, stage, source_key
    for alias in aliases:
        for source, source_name in ((params, "Parameters"), (home, "Home")):
            if _is_record(source) and source.get(alias) is not None:
                number = _parse_number(source[alias])
                if number is not None:
                    if provenance is not None and source_name == "Parameters":
                        provenance.append(
                            EvidenceProvenanceRecord(
                                category=category,
                                metric=display_name,
                                value=number,
                                unit=unit,
                                status="CONFIGURED",
                                stage="Parameters",
                                corner=None,
                                tool="Configuration",
                                source_metric_id=alias,
                                run_id=store.run_id or "run_latest",
                                timestamp=store.timestamp,
                            )
                        )
                    return number, source_name, alias
    return None, "", ""


def _parse_corner_attributes(name: str):
    process = temperature = voltage = rc_corner = None
    for part in re.split(r"[/_]", name):
        trimmed = part.strip()
        if re.fullmatch(r"(?i)MAX|MIN|ML|TYP|WCL|ss|ff|tt|fs|sf", trimmed):
            process = trimmed.upper()
        temp_match = re.match(r"(?i)^(?:m(\d+)|(-?\d+)C?)$", trimmed)
        if temp_match:
            temperature = (
                -float(temp_match.group(1)) if temp_match.group(1) else float(temp_match.group(2))
            )
        volt_match = re.search(r"(?i)(\d+)v(\d+)", trimmed)
        if volt_match:
            voltage = float(f"{volt_match.group(1)}.{volt_match.group(2)}")
        if re.fullmatch(r"(?i)Cworst|RCworst|Cbest|RCbest|TYPICAL|typical|best|worst", trimmed):
            rc_corner = trimmed
    return process, temperature, voltage, rc_corner


# Mirrors SignoffPackageCollector._step_dirs() in engine/signoff.py; kept
# local to avoid an import cycle between the two signoff modules.
STEP_DIRS = {
    StepEnum.SYNTHESIS.value: "Synthesis_yosys",
    StepEnum.LEC.value: "lec_yosys_lec",
    StepEnum.FLOORPLAN.value: "Floorplan_ecc",
    StepEnum.PLACEMENT.value: "place_dreamplace",
    StepEnum.CTS.value: "CTS_ecc",
    StepEnum.LEGALIZATION.value: "legalization_dreamplace",
    StepEnum.ROUTING.value: "route_ecc",
    StepEnum.DRC.value: "drc_ecc",
    StepEnum.LVS.value: "lvs_ecc",
    StepEnum.FILLER.value: "filler_ecc",
    StepEnum.POST_ROUTE_LEC.value: "postRouteLec_yosys_lec",
    StepEnum.RCX.value: "RCX_ecc",
    StepEnum.STA.value: "sta_ecc",
    StepEnum.HARDEN.value: "Harden_ecc",
}

# ---------------------------------------------------------------------------
# Workspace collection
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace") if path.is_file() else None
    except OSError:
        return None


def _step_metric_payloads(step_dir: Path) -> list[dict]:
    payloads = []
    analysis = step_dir / "analysis"
    for name in ("qor_metrics.json", "qor_summary.json"):
        payloads.append(json_read(analysis / name))
    feature = step_dir / "feature"
    for candidate in feature.glob("*.json"):
        payloads.append(json_read(candidate))
    return [payload for payload in payloads if payload]


def _sta_corner_reports(workspace, workspace_root: Path) -> tuple[dict, dict | None]:
    """Return ({corner_label: payload}, power_payload) from configured STA dirs."""
    from chipcompiler.tools.ecc import sta_qor

    corners: dict[str, dict] = {}
    power_payload = None
    feature_root = workspace_root / STEP_DIRS[StepEnum.STA.value] / "feature"
    report_root = workspace_root / STEP_DIRS[StepEnum.STA.value] / "report"
    for label, feature_dir in sta_qor.configured_sta_artifact_directories(workspace, feature_root):
        payload = json_read(feature_dir / "qor_summary.json")
        report_dir = report_root / label
        rpt = parse_qor_summary_rpt(_read_text(report_dir / "qor_summary.rpt"))
        if rpt.wns is not None:
            payload.setdefault("setup_wns", rpt.wns)
            payload.setdefault("setup_tns", rpt.tns)
            payload.setdefault("violating_endpoints_setup", rpt.nvp)
            payload.setdefault("frequency_mhz", rpt.frequency_mhz)
        if rpt.hold_wns is not None:
            payload.setdefault("hold_wns", rpt.hold_wns)
            payload.setdefault("hold_tns", rpt.hold_tns)
            payload.setdefault("violating_endpoints_hold", rpt.hold_nvp)
        if payload:
            corners[label] = payload
        power_rpt = parse_power_rpt(_read_text(report_dir / "power.rpt"))
        if power_rpt.total_power_mw is not None and power_payload is None:
            power_payload = dataclasses.asdict(power_rpt)

    if not corners:
        # syn_sta-style workspace: post-synthesis STA lives in Synthesis_yosys.
        synth_report = workspace_root / STEP_DIRS[StepEnum.SYNTHESIS.value] / "report"
        rpt = parse_qor_summary_rpt(_read_text(synth_report / "qor_summary.rpt"))
        power_rpt = parse_power_rpt(_read_text(synth_report / "power.rpt"))
        if rpt.wns is not None or power_rpt.total_power_mw is not None:
            corners["POST_SYNTHESIS"] = {
                "setup_wns": rpt.wns,
                "setup_tns": rpt.tns,
                "violating_endpoints_setup": rpt.nvp,
                "frequency_mhz": rpt.frequency_mhz,
                "hold_wns": rpt.hold_wns,
                "hold_tns": rpt.hold_tns,
                "violating_endpoints_hold": rpt.hold_nvp,
            }
            if power_rpt.total_power_mw is not None and power_payload is None:
                power_payload = dataclasses.asdict(power_rpt)
    return corners, power_payload


def collect_workspace_report(workspace) -> DesignReportData:
    """Walk an ECC workspace (Workspace or duck-typed stand-in) and extract."""
    workspace_root = Path(workspace.directory or "")
    flow_data = workspace.flow.data if getattr(workspace, "flow", None) else {}
    flow = json_read(workspace_root / "home" / "flow.json") or flow_data
    parameters = getattr(getattr(workspace, "parameters", None), "data", None)
    if not isinstance(parameters, dict):
        parameters = json_read(workspace_root / "home" / "parameters.json")
    if not isinstance(parameters, dict):
        parameters = {}

    step_metrics: dict[str, dict] = {}
    for dir_name in STEP_DIRS.values():
        step_dir = workspace_root / dir_name
        if not step_dir.is_dir():
            continue
        merged: dict = {}
        for payload in _step_metric_payloads(step_dir):
            merged.update(payload)
        if merged:
            step_metrics[dir_name] = merged

    corners, power_payload = _sta_corner_reports(workspace, workspace_root)
    if power_payload:
        step_metrics.setdefault("Power", {}).update(power_payload)

    from chipcompiler.cli.core.version_info import version_payload
    from chipcompiler.engine.signoff.report import extract_design_report_data

    inputs = {
        "design_name": (
            getattr(getattr(workspace, "design", None), "name", "")
            or getattr(workspace, "name", None)
            or parameters.get("design")
            or parameters.get("Design")
        ),
        "workspace_name": getattr(workspace, "name", None),
        "workspace_path": str(workspace_root),
        "pdk": parameters.get("pdk") or parameters.get("PDK"),
        "parameters": parameters,
        "flow": flow,
        "step_metrics": step_metrics,
        "sta_corner_reports": corners,
        "version_info": version_payload(),
    }
    return extract_design_report_data(inputs)
