"""Bind catalog ``performance.*`` slots to on-disk QoR / flow numbers.

Optional warn-policy items: present metrics become ``pass`` with
``"<value> <unit>"`` summaries; missing metrics become ``warning`` (not
``unavailable``) so readiness stays WARN rather than MISS.

In:
    workspace — loaded Workspace with step analysis / flow ledger
Out:
    list[dict] — schema-v3 checklist item rows (category performance)
Entry:
    rebuild_home_checklist()  chipcompiler/tools/ecc/signoff_checklist.py
See:
    SIGNOFF_ITEM_CATALOG (performance.*)  chipcompiler/runtime/signoff/catalog.py
    METRIC_REGISTRY                       chipcompiler/analysis/qor/metric_registry.py
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chipcompiler.analysis.qor.metric_registry import METRIC_REGISTRY
from chipcompiler.data import StepEnum
from chipcompiler.data.step import STEP_DIRECTORIES
from chipcompiler.runtime.signoff.catalog import SIGNOFF_ITEM_CATALOG
from chipcompiler.runtime.signoff.qor_perf_support import (
    analysis_qor_summary_path,
    load_metric_values,
)
from chipcompiler.utility import json_read

_QOR_METRICS_FILENAME = "qor_metrics" + ".json"
_CREATE_CLOCK_RE = re.compile(r"\bcreate_clock\b", re.IGNORECASE)


@dataclass(frozen=True)
class PerformanceBinding:
    """One catalog performance slot → metric wire name(s) and lookup order."""

    item_id: str
    metric_ids: tuple[str, ...]
    step_names: tuple[str, ...]
    unit: str
    kind: str = "qor_metrics"  # qor_metrics | host | sdc


def _unit_for(metric_id: str, fallback: str = "") -> str:
    entry = METRIC_REGISTRY.get(metric_id)
    if entry is None:
        return fallback
    return entry[0] or fallback


# Catalog id → binders. First matching finite metric across step_names wins.
PERFORMANCE_BINDINGS: tuple[PerformanceBinding, ...] = (
    PerformanceBinding(
        "performance.sta.setup_wns",
        ("sta_setup_wns",),
        (StepEnum.STA.value,),
        _unit_for("sta_setup_wns", "ns"),
    ),
    PerformanceBinding(
        "performance.sta.setup_tns",
        ("sta_setup_tns",),
        (StepEnum.STA.value,),
        _unit_for("sta_setup_tns", "ns"),
    ),
    PerformanceBinding(
        "performance.sta.hold_wns",
        ("sta_hold_wns",),
        (StepEnum.STA.value,),
        _unit_for("sta_hold_wns", "ns"),
    ),
    PerformanceBinding(
        "performance.sta.hold_tns",
        ("sta_hold_tns",),
        (StepEnum.STA.value,),
        _unit_for("sta_hold_tns", "ns"),
    ),
    PerformanceBinding(
        "performance.sta.frequency",
        ("sta_frequency_mhz",),
        (StepEnum.STA.value,),
        _unit_for("sta_frequency_mhz", "MHz"),
    ),
    PerformanceBinding(
        "performance.power.dynamic",
        ("power_analysis_dynamic_uw", "synthesis_power_dynamic_uw"),
        (StepEnum.POWER_ANALYSIS.value, StepEnum.SYNTHESIS.value, StepEnum.STA.value),
        "uW",
    ),
    PerformanceBinding(
        "performance.power.leakage",
        ("power_analysis_leakage_uw", "synthesis_power_leakage_uw"),
        (StepEnum.POWER_ANALYSIS.value, StepEnum.SYNTHESIS.value, StepEnum.STA.value),
        "uW",
    ),
    PerformanceBinding(
        "performance.sdc.clock_count",
        ("clock_count",),
        (StepEnum.STA.value, StepEnum.CTS.value, StepEnum.SYNTHESIS.value),
        "count",
        kind="sdc",
    ),
    PerformanceBinding(
        "performance.cts.skew",
        ("cts_worst_optimized_skew_ns",),
        (StepEnum.CTS.value,),
        "ns",
    ),
    PerformanceBinding(
        "performance.cts.insertion_latency",
        ("cts_worst_max_insertion_latency_ns",),
        (StepEnum.CTS.value,),
        "ns",
    ),
    PerformanceBinding(
        "performance.cts.buffer_count",
        ("cts_buffer_count",),
        (StepEnum.CTS.value,),
        _unit_for("cts_buffer_count", "count"),
    ),
    PerformanceBinding(
        "performance.cts.clock_wirelength",
        ("cts_clock_wirelength_max", "clock_wirelength"),
        (StepEnum.CTS.value,),
        "um",
    ),
    PerformanceBinding(
        "performance.cts.tree_max_level",
        ("cts_clock_tree_max_level",),
        (StepEnum.CTS.value,),
        "count",
    ),
    PerformanceBinding(
        "performance.place.hpwl",
        ("place_hpwl",),
        (StepEnum.PLACEMENT.value,),
        _unit_for("place_hpwl", "um"),
    ),
    PerformanceBinding(
        "performance.place.congestion_overflow",
        ("place_congestion_egr_overflow_total",),
        (StepEnum.PLACEMENT.value,),
        _unit_for("place_congestion_egr_overflow_total", "count"),
    ),
    PerformanceBinding(
        "performance.route.wirelength",
        ("route_wirelength",),
        (StepEnum.ROUTING.value,),
        _unit_for("route_wirelength", "um"),
    ),
    PerformanceBinding(
        "performance.route.via_count",
        ("route_via_count",),
        (StepEnum.ROUTING.value,),
        _unit_for("route_via_count", "count"),
    ),
    PerformanceBinding(
        "performance.synthesis.cell_area",
        ("synthesis_cell_area",),
        (StepEnum.SYNTHESIS.value,),
        _unit_for("synthesis_cell_area", "um^2"),
    ),
    PerformanceBinding(
        "performance.synthesis.cell_count",
        ("synthesis_cell_count",),
        (StepEnum.SYNTHESIS.value,),
        _unit_for("synthesis_cell_count", "count"),
    ),
    PerformanceBinding(
        "performance.host.latency",
        ("runtime_seconds",),
        (),
        "s",
        kind="host",
    ),
    PerformanceBinding(
        "performance.host.throughput",
        ("runtime_seconds",),
        (),
        "1/s",
        kind="host",
    ),
    PerformanceBinding(
        "performance.host.peak_memory",
        ("peak_memory_mb",),
        (),
        "MB",
        kind="host",
    ),
    PerformanceBinding(
        "performance.host.avg_memory",
        ("peak_memory_mb",),
        (),
        "MB",
        kind="host",
    ),
    PerformanceBinding(
        "performance.host.compile_peak_memory",
        ("peak_memory_mb",),
        (StepEnum.SYNTHESIS.value,),
        "MB",
        kind="host",
    ),
)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number:  # NaN
        return None
    return number


def load_qor_metrics_values(path: str | Path) -> dict[str, float]:
    """Project schema-v3 ``qor_metrics.json`` metrics to id→value.

    In:
        path — qor_metrics.json filesystem path
    Out:
        dict[str, float] — metric id → finite value
    See:
        collect_performance_items()  chipcompiler/runtime/signoff/performance.py
    """
    payload = json_read(path)
    if not isinstance(payload, dict):
        return {}
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        return {}
    values: dict[str, float] = {}
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        metric_id = metric.get("id")
        if not isinstance(metric_id, str) or not metric_id:
            continue
        actual = _finite(metric.get("value"))
        if actual is None:
            continue
        values[metric_id] = actual
    return values


def analysis_qor_metrics_path(workspace: str | Path, step_directory: str) -> Path:
    """``<workspace>/<step>/analysis/qor_metrics.json``."""
    return Path(workspace) / step_directory / "analysis" / _QOR_METRICS_FILENAME


def _step_directory_name(step_name: str) -> str | None:
    return STEP_DIRECTORIES.get(step_name)


def _metrics_for_step(workspace_dir: Path, step_name: str) -> dict[str, float]:
    directory = _step_directory_name(step_name)
    if not directory:
        return {}
    path = analysis_qor_metrics_path(workspace_dir, directory)
    if not path.is_file():
        # Fall back to gate actuals inside qor_summary when metrics file absent.
        summary_path = analysis_qor_summary_path(workspace_dir, directory)
        if summary_path.is_file():
            try:
                return load_metric_values(summary_path)
            except (OSError, ValueError, KeyError):
                return {}
        return {}
    try:
        return load_qor_metrics_values(path)
    except (OSError, ValueError, TypeError):
        return {}


def _lookup_metric(
    workspace_dir: Path,
    step_names: Iterable[str],
    metric_ids: Iterable[str],
) -> tuple[float | None, str | None, str | None]:
    """Return (value, metric_id, relative evidence path)."""
    for step_name in step_names:
        values = _metrics_for_step(workspace_dir, step_name)
        if not values:
            continue
        directory = _step_directory_name(step_name)
        for metric_id in metric_ids:
            if metric_id not in values:
                continue
            evidence = f"{directory}/analysis/{_QOR_METRICS_FILENAME}" if directory else None
            return values[metric_id], metric_id, evidence
    return None, None, None


def _parse_runtime_to_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _finite(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.isdigit() or re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        hours, minutes, seconds = (int(p) for p in parts)
        return float(hours * 3600 + minutes * 60 + seconds)
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        minutes, seconds = (int(p) for p in parts)
        return float(minutes * 60 + seconds)
    return None


def _host_aggregates(workspace: Any, workspace_dir: Path) -> dict[str, float]:
    """latency / throughput / peak / avg / compile_peak from step metrics + flow."""
    runtimes: list[float] = []
    peaks: list[float] = []
    compile_peak: float | None = None

    for step_name in STEP_DIRECTORIES:
        values = _metrics_for_step(workspace_dir, step_name)
        runtime = values.get("runtime_seconds")
        peak = values.get("peak_memory_mb")
        if runtime is not None:
            runtimes.append(runtime)
        if peak is not None:
            peaks.append(peak)
            if step_name == StepEnum.SYNTHESIS.value:
                compile_peak = peak

    # Fill gaps from flow ledger when analysis metrics omit host fields.
    flow = getattr(workspace, "flow", None)
    steps_fn = getattr(flow, "steps", None)
    raw_steps = steps_fn() if callable(steps_fn) else []
    if isinstance(raw_steps, list):
        for step in raw_steps:
            if not isinstance(step, dict):
                continue
            if not runtimes:
                parsed = _parse_runtime_to_seconds(step.get("runtime"))
                if parsed is not None:
                    runtimes.append(parsed)
            peak = _finite(step.get("peak memory (mb)"))
            if peak is None:
                peak = _finite(step.get("peak_memory_mb"))
            if peak is not None and not peaks:
                peaks.append(peak)

    result: dict[str, float] = {}
    if runtimes:
        latency = float(sum(runtimes))
        result["latency"] = latency
        if latency > 0:
            result["throughput"] = 1.0 / latency
    if peaks:
        result["peak_memory"] = float(max(peaks))
        result["avg_memory"] = float(sum(peaks) / len(peaks))
    if compile_peak is not None:
        result["compile_peak_memory"] = float(compile_peak)
    elif peaks and StepEnum.SYNTHESIS.value in STEP_DIRECTORIES:
        # Already tried synthesis; leave absent when unknown.
        pass
    return result


def _sdc_clock_count(workspace: Any) -> tuple[float | None, str | None]:
    candidates: list[Path] = []
    pdk = getattr(workspace, "pdk", None)
    sdc = getattr(pdk, "sdc", None) if pdk is not None else None
    if sdc:
        candidates.append(Path(sdc))
    workspace_dir = Path(getattr(workspace, "directory", "") or ".")
    candidates.extend(sorted((workspace_dir / "origin").glob("*.sdc")))
    for path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        count = len(_CREATE_CLOCK_RE.findall(text))
        rel = path.name
        with contextlib.suppress(ValueError):
            rel = str(path.relative_to(workspace_dir))
        return float(count), rel
    return None, None


def _format_summary(value: float, unit: str) -> str:
    if abs(value) >= 100 or value == int(value):
        number = f"{value:.0f}" if value == int(value) else f"{value:.3g}"
    else:
        number = f"{value:.6g}"
    return f"{number} {unit}".strip() if unit else number


def _catalog_performance_specs() -> dict[str, Any]:
    return {item.id: item for item in SIGNOFF_ITEM_CATALOG if item.category == "performance"}


def collect_performance_items(workspace: Any) -> list[dict]:
    """Build checklist rows for every catalog ``performance.*`` slot.

    In:
        workspace — Workspace (directory + optional flow/pdk)
    Out:
        list[dict] — checklist items (pass or warning)
    Entry:
        rebuild_home_checklist()  chipcompiler/tools/ecc/signoff_checklist.py
    See:
        PERFORMANCE_BINDINGS  chipcompiler/runtime/signoff/performance.py
    """
    workspace_dir = Path(getattr(workspace, "directory", "") or ".")
    specs = _catalog_performance_specs()
    host = _host_aggregates(workspace, workspace_dir)
    items: list[dict] = []

    for binding in PERFORMANCE_BINDINGS:
        spec = specs.get(binding.item_id)
        if spec is None:
            continue
        value: float | None = None
        evidence_path: str | None = None
        metric_id: str | None = None

        if binding.kind == "host":
            key = binding.item_id.rsplit(".", 1)[-1]
            value = host.get(key)
            evidence_path = "home/flow.json"
        elif binding.kind == "sdc":
            value, evidence_path = _sdc_clock_count(workspace)
            if value is None:
                value, metric_id, evidence_path = _lookup_metric(
                    workspace_dir, binding.step_names, binding.metric_ids
                )
        else:
            value, metric_id, evidence_path = _lookup_metric(
                workspace_dir, binding.step_names, binding.metric_ids
            )

        if value is None:
            items.append(
                {
                    "id": binding.item_id,
                    "step": spec.step,
                    "category": "performance",
                    "owner": "qor",
                    "policy": "warn",
                    "state": "warning",
                    "blocked": False,
                    "title": spec.title,
                    "summary": "metric not present in step analysis",
                    "source": {"kind": "performance", "path": evidence_path or ""},
                    "evidence": [],
                }
            )
            continue

        unit = binding.unit
        if metric_id:
            unit = _unit_for(metric_id, unit)
        evidence = [{"kind": "analysis", "path": evidence_path}] if evidence_path else []
        items.append(
            {
                "id": binding.item_id,
                "step": spec.step,
                "category": "performance",
                "owner": "qor",
                "policy": "warn",
                "state": "pass",
                "blocked": False,
                "title": spec.title,
                "summary": _format_summary(value, unit),
                "source": {
                    "kind": "performance",
                    "path": evidence_path or "",
                    "metric_id": metric_id or binding.metric_ids[0],
                    "value": value,
                    "unit": unit,
                },
                "evidence": evidence,
            }
        )
    return items
