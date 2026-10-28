"""Catalog performance slots bind to qor_metrics / SDC / host aggregates."""

from __future__ import annotations

import json
from pathlib import Path

from chipcompiler.data.step import STEP_DIRECTORIES
from chipcompiler.data.types import StepEnum
from chipcompiler.runtime.signoff.catalog import SIGNOFF_ITEM_CATALOG
from chipcompiler.runtime.signoff.performance import (
    PERFORMANCE_BINDINGS,
    collect_performance_items,
    load_qor_metrics_values,
)
from chipcompiler.runtime.signoff.readiness import classify_signoff_readiness


class _Flow:
    def __init__(self, steps):
        self._steps = steps

    def steps(self):
        return self._steps


class _Workspace:
    def __init__(self, directory: Path, *, flow=None, sdc: Path | None = None):
        self.directory = directory
        self.flow = flow or _Flow([])
        self.pdk = type("PDK", (), {"sdc": sdc})()
        self.design = type("Design", (), {"name": "demo"})()


def _write_metrics(workspace: Path, step: str, metrics: list[dict]) -> Path:
    directory = STEP_DIRECTORIES[step]
    path = workspace / directory / "analysis" / "qor_metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "step": step,
                "status": "success",
                "metrics": metrics,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_performance_bindings_cover_catalog_slots():
    catalog_ids = {item.id for item in SIGNOFF_ITEM_CATALOG if item.category == "performance"}
    bound_ids = {binding.item_id for binding in PERFORMANCE_BINDINGS}
    assert catalog_ids == bound_ids


def test_load_qor_metrics_values_reads_finite_ids(tmp_path: Path):
    path = _write_metrics(
        tmp_path,
        StepEnum.STA.value,
        [
            {"id": "sta_setup_wns", "value": 8.151},
            {"id": "sta_hold_wns", "value": 0.113},
            {"id": "skip_me", "value": "nan"},
        ],
    )
    values = load_qor_metrics_values(path)
    assert values["sta_setup_wns"] == 8.151
    assert values["sta_hold_wns"] == 0.113
    assert "skip_me" not in values


def test_collect_performance_items_pass_and_warning(tmp_path: Path):
    _write_metrics(
        tmp_path,
        StepEnum.STA.value,
        [
            {"id": "sta_setup_wns", "value": 1.25, "unit": "ns"},
            {"id": "sta_setup_tns", "value": 0.0},
            {"id": "sta_hold_wns", "value": 0.2},
            {"id": "sta_hold_tns", "value": 0.0},
            {"id": "sta_frequency_mhz", "value": 100.0},
            {"id": "runtime_seconds", "value": 10.0},
            {"id": "peak_memory_mb", "value": 512.0},
        ],
    )
    _write_metrics(
        tmp_path,
        StepEnum.SYNTHESIS.value,
        [
            {"id": "synthesis_cell_area", "value": 100.0},
            {"id": "synthesis_cell_count", "value": 42},
            {"id": "synthesis_power_dynamic_uw", "value": 12.5},
            {"id": "synthesis_power_leakage_uw", "value": 3.0},
            {"id": "runtime_seconds", "value": 5.0},
            {"id": "peak_memory_mb", "value": 256.0},
        ],
    )
    _write_metrics(
        tmp_path,
        StepEnum.PLACEMENT.value,
        [
            {"id": "place_hpwl", "value": 1000.0},
            {"id": "place_congestion_egr_overflow_total", "value": 0.0},
            {"id": "runtime_seconds", "value": 2.0},
            {"id": "peak_memory_mb", "value": 128.0},
        ],
    )
    _write_metrics(
        tmp_path,
        StepEnum.ROUTING.value,
        [
            {"id": "route_wirelength", "value": 2000.0},
            {"id": "route_via_count", "value": 50},
            {"id": "runtime_seconds", "value": 3.0},
            {"id": "peak_memory_mb", "value": 200.0},
        ],
    )
    sdc = tmp_path / "origin" / "demo.sdc"
    sdc.parent.mkdir(parents=True)
    sdc.write_text("create_clock -name clk -period 10 [get_ports clk]\n", encoding="utf-8")

    items = collect_performance_items(_Workspace(tmp_path, sdc=sdc))
    by_id = {item["id"]: item for item in items}

    assert by_id["performance.sta.setup_wns"]["state"] == "pass"
    assert "1.25" in by_id["performance.sta.setup_wns"]["summary"]
    assert by_id["performance.synthesis.cell_count"]["state"] == "pass"
    assert by_id["performance.sdc.clock_count"]["state"] == "pass"
    assert by_id["performance.sdc.clock_count"]["summary"].startswith("1")
    assert by_id["performance.host.latency"]["state"] == "pass"
    assert by_id["performance.host.compile_peak_memory"]["state"] == "pass"
    # CTS metrics absent → warning (optional), not unavailable
    assert by_id["performance.cts.skew"]["state"] == "warning"
    assert by_id["performance.cts.skew"]["blocked"] is False

    checklist = {
        "schema_version": 3,
        "kind": "signoff_checklist",
        "status": "attention",
        "checklist": list(by_id.values()),
    }
    assert classify_signoff_readiness(checklist) == "WARN"
