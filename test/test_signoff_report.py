import json
import os
from types import SimpleNamespace

from chipcompiler.engine.signoff import SignoffPackageCollector, generate_text_report
from chipcompiler.engine.signoff.report import (
    DesignReportData,
    StepMetricStore,
    canonicalize_stage_name,
    collect_workspace_report,
    extract_design_report_data,
    format_duration,
    parse_power_rpt,
    parse_qor_summary_rpt,
    parse_runtime_seconds,
)
from chipcompiler.engine.signoff.report_text import format_text_report


class TestParsers:
    def test_parse_runtime_seconds(self):
        assert parse_runtime_seconds("0:00:18") == 18.0
        assert parse_runtime_seconds("1:02:03") == 3723.0
        assert parse_runtime_seconds("2:30") == 150.0
        assert parse_runtime_seconds(12) == 12.0
        assert parse_runtime_seconds("") is None
        assert parse_runtime_seconds(None) is None
        assert parse_runtime_seconds("x:yy") is None

    def test_format_duration(self):
        assert format_duration(18.0) == "18s"
        assert format_duration(3723.0) == "1h 2m 3s"
        assert format_duration(None) is None

    def test_canonicalize_stage_name(self):
        assert canonicalize_stage_name("Synthesis_yosys") == "Synth"
        assert canonicalize_stage_name("legalization_dreamplace") == "Legal"
        assert canonicalize_stage_name("custom_step") == "custom_step"

    def test_parse_power_rpt(self):
        text = (
            "Global Operating Voltage = 1.08\n"
            "Cell Internal Power = 2.5 mW\n"
            "Net Switching Power = 750.0 uW\n"
            "Total Dynamic Power = 3.25 mW\n"
            "Cell Leakage Power = 12.5 uW\n"
            "Total  2.5 mW  750.0 uW  12.5 uW  3.2625 mW\n"
        )
        parsed = parse_power_rpt(text)
        assert parsed.voltage_v == 1.08
        assert parsed.internal_power_mw == 2.5
        assert parsed.switching_power_mw == 0.75
        assert parsed.dynamic_power_mw == 3.25
        assert parsed.leakage_power_mw == 0.0125
        assert parsed.total_power_mw == 3.2625

    def test_parse_power_rpt_empty(self):
        parsed = parse_power_rpt(None)
        assert parsed.total_power_mw is None

    def test_parse_qor_summary_rpt(self):
        parsed = parse_qor_summary_rpt("clk -0.12 -1.2 3 450.0MHz 0.05 0.0 0\n")
        assert parsed.wns == -0.12
        assert parsed.tns == -1.2
        assert parsed.nvp == 3.0
        assert parsed.frequency_mhz == 450.0
        assert parsed.hold_wns == 0.05

    def test_parse_qor_summary_rpt_garbage(self):
        assert parse_qor_summary_rpt("nothing here").wns is None


class TestStepMetricStore:
    def test_query_schema3_metrics_array(self):
        store = StepMetricStore()
        store.add("route_ecc", {"metrics": [{"id": "route_dr_total_via_count", "value": 42}]})
        value, stage, key = store.query(
            "Routing", "Via Count", ["Route"], ["route_dr_total_via_count"]
        )
        assert value == 42.0
        assert key == "route_dr_total_via_count"

    def test_query_dotted_path_and_normalized_key(self):
        store = StepMetricStore()
        store.add("Floorplan_ecc", {"Design Layout": {"die_area": 1234.5}})
        value, _, _ = store.query("Physical", "Die Area", ["Floor"], ["Design Layout.die_area"])
        assert value == 1234.5
        store.add("route_ecc", {"RouteDrTotalViaCount": 7})
        assert store.query("Routing", "Via", ["Route"], ["route_dr_total_via_count"])[0] == 7.0

    def test_query_miss_returns_none(self):
        store = StepMetricStore()
        assert store.query("Physical", "Die Area", ["Floor"], ["die_area"])[0] is None


class TestExtractDesignReportData:
    def _inputs(self, **overrides):
        inputs = {
            "design_name": "gcd",
            "pdk": "ics55",
            "parameters": {"Design": "gcd", "PDK": "ics55", "Frequency max [MHz]": 200.0},
            "flow": {
                "steps": [
                    {
                        "name": "Synthesis",
                        "tool": "yosys",
                        "state": "Success",
                        "runtime": "0:00:18",
                        "peak memory (mb)": 512,
                    },
                    {"name": "route", "tool": "ecc", "state": "Success", "runtime": "0:01:00"},
                ]
            },
            "step_metrics": {},
            "step_summaries": {},
            "sta_corner_reports": {},
            "version_info": {"ecc": "0.1.0", "ecc_tools": "0.1.0"},
        }
        inputs.update(overrides)
        return inputs

    def test_area_normalization_and_utilization(self):
        data = extract_design_report_data(
            self._inputs(
                step_metrics={
                    "Harden_ecc": {
                        "metrics": [
                            {"id": "Design Layout.die_area", "value": 0.42},
                            {"id": "Design Layout.core_area", "value": 0.30},
                            {"id": "Design Layout.core_usage", "value": 0.62},
                        ]
                    },
                }
            )
        )
        assert data.physical.die_area_um2 == 420000.0
        assert data.physical.die_area_mm2 == 0.42
        assert data.physical.core_utilization_pct == 62.0
        assert data.design.design_name == "gcd"

    def test_frequency_fallback_and_fmax_derivation(self):
        data = extract_design_report_data(
            self._inputs(
                step_summaries={
                    "sta_ecc": {"setup_wns": -0.25},
                }
            )
        )
        assert data.timing.target_frequency_mhz == 200.0
        assert data.timing.target_clock_period_ns == 5.0
        assert data.timing.fmax_mhz == 190.48  # 1000 / (5.0 - (-0.25))
        assert data.timing.critical_path_delay_ns == 5.25

    def test_corner_rollup_min_wns(self):
        data = extract_design_report_data(
            self._inputs(
                sta_corner_reports={
                    "MAX_125/RCworst": {"setup_wns": 0.1, "hold_wns": 0.02},
                    "MIN_m40/Cbest": {"setup_wns": -0.3, "hold_wns": 0.05},
                }
            )
        )
        assert [c.corner for c in data.multi_corner_timing] == ["MAX_125/RCworst", "MIN_m40/Cbest"]
        assert data.multi_corner_timing[0].status == "pass"
        assert data.multi_corner_timing[1].status == "fail"
        assert data.multi_corner_timing[0].temperature_c == 125.0
        assert data.multi_corner_timing[1].temperature_c == -40.0
        assert data.timing.setup_wns_ns == -0.3  # min rollup
        assert data.timing.violating_endpoints_setup == 0.0

    def test_drc_status_from_metrics(self):
        data = extract_design_report_data(
            self._inputs(
                step_metrics={
                    "drc_ecc": {"metrics": [{"id": "drc_count", "value": 0}]},
                }
            )
        )
        assert data.verification.drc_status == "clean"
        data = extract_design_report_data(
            self._inputs(
                step_metrics={
                    "drc_ecc": {"drc_count": 5},
                }
            )
        )
        assert data.verification.drc_status == "violations"
        assert data.verification.drc_count == 5.0

    def test_execution_stages_built_from_flow(self):
        data = extract_design_report_data(self._inputs())
        assert [s.stage for s in data.execution.stages] == ["Synth", "Route"]
        assert data.execution.stages[0].runtime_seconds == 18.0
        assert data.execution.stages[0].runtime_formatted == "18s"
        assert data.execution.stages[0].peak_memory_mb == 512.0
        assert data.execution.total_runtime_seconds == 78.0
        assert data.execution.peak_memory_mb == 512.0

    def test_utilization_out_of_range_warns(self):
        data = extract_design_report_data(
            self._inputs(
                step_metrics={
                    "Harden_ecc": {"metrics": [{"id": "Design Layout.core_usage", "value": 150.0}]},
                }
            )
        )
        assert data.physical.core_utilization_pct == 150.0
        assert data.warnings[0].code == "PHYS_UTIL_OUT_OF_RANGE"


class TestFormatTextReport:
    def _full_data(self):
        data = extract_design_report_data(
            {
                "design_name": "gcd",
                "pdk": "ics55",
                "parameters": {"Frequency max [MHz]": 200.0},
                "flow": {
                    "steps": [
                        {
                            "name": "Synthesis",
                            "tool": "yosys",
                            "state": "Success",
                            "runtime": "0:00:18",
                        }
                    ]
                },
                "step_metrics": {
                    "Harden_ecc": {
                        "metrics": [
                            {"id": "Design Layout.die_area", "value": 0.42},
                            {"id": "Design Layout.core_usage", "value": 0.62},
                        ]
                    },
                    "drc_ecc": {"drc_count": 0},
                },
                "sta_corner_reports": {"MAX_125/RCworst": {"setup_wns": 0.01, "hold_wns": 0.02}},
                "version_info": {"gui": "1.2.3"},
            }
        )
        return data

    def test_full_report_layout(self):
        report = format_text_report(self._full_data())
        lines = report.splitlines()
        assert lines[0].startswith("===")
        assert "ECOS STUDIO — DESIGN SUMMARY REPORT" in lines[0]
        assert report.endswith("END OF REPORT")
        for header in (
            "1. PHYSICAL & AREA METRICS",
            "2. TIMING CLOSURE & PERFORMANCE",
            "3. CLOCK TREE & QUALITY",
            "4. MULTI-CORNER TIMING",
            "5. ROUTING & CONGESTION",
            "6. POWER ANALYSIS",
            "7. PHYSICAL VERIFICATION",
            "8. FLOW EXECUTION COST",
        ):
            assert f"[ {header} ]" in lines
        assert "MAX_125/RCworst" in report
        assert "CLEAN (0 violations)" in report
        # WIDTH=78 is nominal; the GUI's multi-corner header itself is 82 cols.
        assert all(len(line) <= 84 for line in lines)

    def test_empty_report_collapses_conditional_rows(self):
        report = format_text_report(DesignReportData())
        assert "Macro Count / Area" not in report
        assert "IO Pins" not in report
        assert "UNRUN" in report
        assert "Die Area" in report  # unconditional rows stay with placeholders


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)


def _make_workspace(tmp_path, *, full=True):
    root = tmp_path / "ws"
    _write_json(
        root / "home" / "flow.json",
        {
            "steps": [
                {
                    "name": "Synthesis",
                    "tool": "yosys",
                    "state": "Success",
                    "runtime": "0:00:18",
                    "peak memory (mb)": 256,
                },
            ]
        },
    )
    if full:
        _write_json(root / "home" / "parameters.json", {"Design": "gcd", "PDK": "ics55"})
        _write_json(
            root / "Harden_ecc" / "analysis" / "qor_metrics.json",
            {
                "metrics": [
                    {"id": "Design Layout.die_area", "value": 0.42},
                ]
            },
        )
        _write_json(root / "drc_ecc" / "analysis" / "qor_metrics.json", {"drc_count": 2})
    return SimpleNamespace(
        directory=str(root),
        name="gcd",
        flow=SimpleNamespace(data={}),
        config={},
    )


class TestCollectWorkspaceReport:
    def test_collect_populated_workspace(self, tmp_path):
        data = collect_workspace_report(_make_workspace(tmp_path, full=True))
        assert data.design.design_name == "gcd"
        assert data.design.pdk == "ics55"
        assert data.physical.die_area_um2 == 420000.0
        assert data.verification.drc_count == 2.0
        assert data.execution.stages[0].peak_memory_mb == 256.0

    def test_collect_minimal_workspace_does_not_raise(self, tmp_path):
        data = collect_workspace_report(_make_workspace(tmp_path, full=False))
        assert data.design.design_name == "gcd"
        assert data.physical.die_area_um2 is None
        assert data.verification.drc_status == "unrun"

    def test_collect_uses_loaded_workspace_parameters(self, tmp_path):
        workspace = _make_workspace(tmp_path, full=False)
        workspace.name = ""
        workspace.parameters = SimpleNamespace(data={"design": "from_params", "pdk": "from_pdk"})

        data = collect_workspace_report(workspace)

        assert data.design.design_name == "from_params"
        assert data.design.pdk == "from_pdk"

    def test_generate_text_report_end_to_end(self, tmp_path):
        report = generate_text_report(_make_workspace(tmp_path, full=True))
        assert report.splitlines()[0].startswith("===")
        assert "gcd" in report

    def test_generate_text_report_refresh_option(self, tmp_path, monkeypatch):
        calls = []

        class FakeFlow:
            def __init__(self, workspace):
                self.workspace = workspace

            def collect_signoff_package(self, options):
                calls.append(options)

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", FakeFlow)
        generate_text_report(_make_workspace(tmp_path), refresh_analysis=True)
        assert calls and calls[0].archive is False
        assert calls[0].materialize is False
        assert calls[0].refresh_analysis is True

    def test_collector_text_report_delegates(self, tmp_path, monkeypatch):
        seen = {}

        def fake_generate(workspace):
            seen["workspace"] = workspace
            return "REPORT"

        monkeypatch.setattr("chipcompiler.engine.signoff.generate_text_report", fake_generate)
        workspace = _make_workspace(tmp_path)
        assert SignoffPackageCollector(workspace).text_report() == "REPORT"
        assert seen["workspace"] is workspace
