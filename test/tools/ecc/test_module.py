#!/usr/bin/env python

import json
from pathlib import Path
from types import SimpleNamespace

import chipcompiler.utility as chipcompiler_utility
import pytest
from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc import metrics as ecc_metrics
from chipcompiler.tools.ecc import plot as ecc_plot
from chipcompiler.tools.ecc import service as ecc_service
from chipcompiler.tools.ecc.builder import build_step, build_step_space
from chipcompiler.tools.ecc.metrics import (
    build_metrics_cts,
    build_metrics_drc,
    build_metrics_legalization,
    build_metrics_net_opt,
    build_metrics_placement,
    build_metrics_routing,
)
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.subflow import EccSubFlow


class FakeEcc:
    def __init__(self):
        self.calls = []
        self.generated_timing_lib_name = "gcd_max.lib"
        self.generated_timing_lib_contents = "library (gcd_max) {}\n"
        self.structured_timing_filenames = (
            "qor_summary.json",
            "timing_paths.json",
        )

    def flow_init(self, **kwargs):
        self.calls.append(("flow_init", kwargs))
        return True

    def init_rcx(self, **kwargs):
        self.calls.append(kwargs)
        return True

    def db_init(self, **kwargs):
        self.calls.append(("db_init", kwargs))
        return True

    def tech_lef_init(self, tech_lef_path):
        self.calls.append(("tech_lef_init", tech_lef_path))
        return True

    def lef_init(self, **kwargs):
        self.calls.append(("lef_init", kwargs))
        return True

    def init_sta(self, **kwargs):
        self.calls.append(("init_sta", kwargs))
        return True

    def run_sta(self):
        self.calls.append(("run_sta", (), {}))
        config_dict = None
        for call in reversed(self.calls):
            if len(call) == 2 and call[0] == "init_sta":
                config_dict = call[1]["config_dict"]
                break
        assert config_dict is not None
        report_dir = Path(config_dict["-temp_directory_path"]) / "timing_reporter"
        report_dir.mkdir(parents=True, exist_ok=True)
        if config_dict.get("-output_timing_reports") == "1":
            (report_dir / "qor_summary.rpt").write_text("report\n", encoding="utf-8")
        if config_dict.get("-output_timing_features") == "1":
            for filename in self.structured_timing_filenames:
                (report_dir / filename).write_text("{}\n", encoding="utf-8")
        return True

    def cts_timing_feature(self):
        self.calls.append(("cts_timing_feature", (), {}))
        return {
            "schema_version": 1,
            "analysis_stage": "cts_fast_sta_post_optimization",
            "availability": "unavailable",
            "clock_count": 0,
            "clocks": [],
        }

    def read_liberty(self, lib_paths):
        self.calls.append(("read_liberty", lib_paths))
        return True

    def read_sdc(self, sdc_path):
        self.calls.append(("read_sdc", sdc_path))
        return True

    def idb_init(self, config_path):
        self.calls.append(("idb_init", config_path))
        return True

    def extract_lib(self):
        self.calls.append(("extract_lib", (), {}))
        for call in reversed(self.calls):
            if len(call) != 2:
                continue
            call_name, payload = call
            if call_name != "init_sta":
                continue
            temp_dir = payload.get("config_dict", {}).get("-temp_directory_path")
            if not temp_dir:
                return True
            lib_path = Path(temp_dir) / "timing_characterizer" / self.generated_timing_lib_name
            lib_path.parent.mkdir(parents=True, exist_ok=True)
            lib_path.write_text(self.generated_timing_lib_contents, encoding="utf-8")
            return True
        return True

    def view_json_save(self, **kwargs):
        self.calls.append(("view_json_save", kwargs))
        return True

    def view_json_apply_edits(self, **kwargs):
        self.calls.append(("view_json_apply_edits", kwargs))
        return True

    def __getattr__(self, name):
        def record_call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return True

        return record_call


def _assert_no_path_values(value):
    if isinstance(value, Path):
        raise AssertionError(f"native ECC boundary received Path: {value!r}")
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_path_values(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _assert_no_path_values(item)


def test_ecc_tools_module_imports_installed_native_extension():
    module = ECCToolsModule()
    assert module.get_ecc() is not None


def test_close_resets_native_data_without_flow_exit():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    module.close()

    assert module.ecc.calls == [("reset_data", (), {})]


def test_init_rcx_passes_pdk_when_configured():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    assert module.init_rcx(config="/tmp/rcx.json", pdk="ics55") is True

    assert module.ecc.calls == [{"config": "/tmp/rcx.json", "pdk": "ics55"}]


def test_init_rcx_defaults_to_ics55_pdk():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    assert module.init_rcx(config="/tmp/rcx.json") is True

    assert module.ecc.calls == [{"config": "/tmp/rcx.json", "pdk": "ics55"}]


def test_init_rcx_omits_explicit_empty_pdk_for_backward_compatibility():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    assert module.init_rcx(config="/tmp/rcx.json", pdk="") is True

    assert module.ecc.calls == [{"config": "/tmp/rcx.json"}]


def test_view_json_save_passes_output_options():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    assert (
        module.view_json_save(
            output_dir=Path("/tmp/view_json"),
            json_format="compact",
            compress=True,
        )
        is True
    )

    assert module.ecc.calls == [
        (
            "view_json_save",
            {
                "output_dir": "/tmp/view_json",
                "json_format": "compact",
                "compress": True,
            },
        ),
    ]


def test_view_json_apply_edits_passes_compress_option():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    assert (
        module.view_json_apply_edits(
            edits_path=Path("/tmp/view_json/edits/layout_edits.json.gz"),
            compress=True,
        )
        is True
    )

    assert module.ecc.calls == [
        (
            "view_json_apply_edits",
            {
                "edits_path": "/tmp/view_json/edits/layout_edits.json.gz",
                "compress": True,
            },
        ),
    ]


def test_ecc_binding_wrappers_stringify_path_arguments(tmp_path):
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    module.init_config(
        flow_config=Path("/ws/config/flow.json"),
        db_config=Path("/ws/config/db.json"),
        output_dir=Path("/ws/output"),
        feature_dir=Path("/ws/feature"),
    )
    module.update_step_paths(
        output_dir=Path("/ws/output"),
        feature_dir=Path("/ws/feature"),
    )
    module.init_techlef(Path("/pdk/tech.lef"))
    module.init_lefs([Path("/pdk/std.lef")])
    module.idb_init(Path("/ws/config/db.json"))
    module.update_sta_data_config(
        db_config=Path("/ws/config/db.json"),
        output_dir=Path("/ws/out"),
        lib_paths=[Path("/pdk/lib.lib")],
        sdc_path=Path("/ws/design.sdc"),
    )
    module.run_timing(
        config=Path("/ws/config/sta.json"),
        work_dir=tmp_path / "sta_work",
        report_dir=tmp_path / "sta_report",
        feature_dir=tmp_path / "sta_feature",
        lib_paths=[Path("/pdk/lib.lib")],
        sdc_path=Path("/ws/design.sdc"),
        spef_path=Path("/ws/design.spef"),
        corner="MAX_125/RCworst",
    )

    assert module.ecc.calls == [
        ("flow_init", {"flow_config": "/ws/config/flow.json"}),
        (
            "db_init",
            {
                "config_path": "/ws/config/db.json",
                "output_path": "/ws/output",
                "feature_path": "/ws/feature",
            },
        ),
        (
            "db_init",
            {
                "output_path": "/ws/output",
                "feature_path": "/ws/feature",
            },
        ),
        ("tech_lef_init", "/pdk/tech.lef"),
        ("lef_init", {"lef_paths": ["/pdk/std.lef"]}),
        ("idb_init", "/ws/config/db.json"),
        (
            "db_init",
            {
                "config_path": "/ws/config/db.json",
                "output_path": "/ws/out",
                "lib_paths": ["/pdk/lib.lib"],
                "sdc_path": "/ws/design.sdc",
            },
        ),
        ("lib_init", (), {"lib_paths": ["/pdk/lib.lib"]}),
        ("sdc_init", ("/ws/design.sdc",), {}),
        ("spef_init", ("/ws/design.spef",), {}),
        (
            "init_sta",
            {
                "config": "/ws/config/sta.json",
                "config_dict": {
                    "-temp_directory_path": str(tmp_path / "sta_work"),
                    "-output_timing_reports": "1",
                    "-output_timing_features": "1",
                    "-timing_path_limit": "20",
                    "-timing_corner": "MAX_125/RCworst",
                },
            },
        ),
        ("run_sta", (), {}),
        ("destroy_sta", (), {}),
    ]


def test_run_timing_splits_text_reports_and_structured_artifacts(tmp_path):
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()
    report_dir = tmp_path / "report" / "MAX_125" / "RCworst"
    feature_dir = tmp_path / "feature" / "MAX_125" / "RCworst"

    module.run_timing(
        work_dir=tmp_path / "data" / "sta",
        report_dir=report_dir,
        feature_dir=feature_dir,
        output_modes=("structured", "report"),
        max_paths_per_analysis=7,
        corner="MAX_125/RCworst",
    )

    assert (report_dir / "qor_summary.rpt").is_file()
    assert (feature_dir / "qor_summary.json").is_file()
    assert (feature_dir / "timing_paths.json").is_file()
    init_config = next(
        call[1]
        for call in module.ecc.calls
        if len(call) == 2 and call[0] == "init_sta"
    )
    assert init_config["config_dict"] == {
        "-temp_directory_path": str(tmp_path / "data" / "sta"),
        "-output_timing_reports": "1",
        "-output_timing_features": "1",
        "-timing_path_limit": "7",
        "-timing_corner": "MAX_125/RCworst",
    }


def test_run_timing_accepts_qor_summary_without_timing_paths(tmp_path):
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()
    module.ecc.structured_timing_filenames = ("qor_summary.json",)
    feature_dir = tmp_path / "feature" / "MAX_125" / "RCworst"

    module.run_timing(
        work_dir=tmp_path / "data" / "sta",
        feature_dir=feature_dir,
        output_modes=("structured",),
        corner="MAX_125/RCworst",
    )

    assert (feature_dir / "qor_summary.json").is_file()
    assert not (feature_dir / "timing_paths.json").exists()


def test_run_timing_rejects_invalid_output_modes(tmp_path):
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    with pytest.raises(ValueError, match="Unsupported STA output modes"):
        module.run_timing(
            work_dir=tmp_path / "data" / "sta",
            feature_dir=tmp_path / "feature",
            output_modes=("structured", "raw"),
        )

    assert module.ecc.calls == []


def test_ecc_runtime_wrappers_stringify_path_arguments(tmp_path):
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()
    timing_output = tmp_path / "output" / "gcd.lib"
    timing_work_dir = tmp_path / "sta"

    module.read_def(Path("/ws/input.def"))
    module.read_verilog(Path("/ws/input.v"), "gcd")
    module.def_save(Path("/ws/output/gcd.def.gz"))
    module.gds_save(Path("/ws/output/gcd.gds.gz"), is_harden=True)
    module.tcl_save(Path("/ws/script/out.tcl"))
    module.verilog_save(Path("/ws/output/gcd.v.gz"))
    module.json_save(Path("/ws/output/gcd.json"))
    module.save_data(Path("/ws/output/db"))
    module.load_data(Path("/ws/input/db"))
    module.write_soc_json(Path("/ws/output/soc.json"))
    module.feature_sammry(Path("/ws/feature/db.json"))
    module.feature_step("placement", Path("/ws/feature/step.json"))
    module.feature_eval_map(Path("/ws/feature/eval.json"), 4, 4)
    module.feature_eval_summary(Path("/ws/feature/eval_summary.json"), 8)
    module.feature_timing_eval_summary(Path("/ws/feature/timing.json"))
    module.feature_net_eval(Path("/ws/feature/net.json"))
    module.feature_cong_map("routing", Path("/ws/feature/cong"))
    module.report_wirelength(Path("/ws/report/wire.rpt"))
    module.report_summary(Path("/ws/report/db.rpt"))
    module.report_congestion(Path("/ws/report/cong.rpt"))
    module.report_dangling_net(Path("/ws/report/dangling.rpt"))
    module.report_route(path=Path("/ws/report/route.rpt"))
    module.report_drc(Path("/ws/report/drc.rpt"))
    module.run_cts(Path("/ws/config/cts.json"), Path("/ws/data/cts"))
    module.report_cts(Path("/ws/report/cts"))
    module.feature_cts_timing()
    module.feature_cts_map(Path("/ws/feature/cts_map.json"))
    module.init_drc(Path("/ws/data/drc"))
    module.run_drc(Path("/ws/config/drc.json"), Path("/ws/report/drc.rpt"))
    module.save_drc(Path("/ws/feature/drc.json"))
    module.pnp(Path("/ws/config/pnp.json"))
    module.run_placement(Path("/ws/config/place.json"))
    module.init_pl(Path("/ws/config/place.json"))
    module.feature_placement_map(Path("/ws/feature/place_map.json"))
    module.run_incremental_flow(Path("/ws/config/incremental.json"))
    module.run_legalize(Path("/ws/config/legalize.json"))
    module.run_filler(Path("/ws/config/filler.json"))
    module.run_macro_placement(Path("/ws/config/macro.json"), Path("/ws/script/macro.tcl"))
    module.run_refinement(Path("/ws/script/refine.tcl"))
    module.run_routing(Path("/ws/config/route.json"))
    module.feature_route_read(Path("/ws/feature/route_read.json"))
    module.feature_route(Path("/ws/feature/route.json"))
    module.run_sta(Path("/ws/data/sta"))
    module.report_sta(Path("/ws/report/sta.rpt"))
    module.init_log(Path("/ws/log"))
    module.set_design_workspace(Path("/ws/design"))
    module.read_lef_def([Path("/pdk/tech.lef")], Path("/ws/design.def"))
    module.read_netlist(Path("/ws/design.v"))
    module.read_spef(Path("/ws/design.spef"))
    module.write_abstract_lef(Path("/ws/output/abstract.lef"))
    module.write_timing_model(
        timing_output,
        config=Path("/ws/config/sta.json"),
        output_dir=timing_work_dir,
        lib_paths=[Path("/pdk/lib.lib")],
        sdc_path=Path("/ws/design.sdc"),
        spef_path=Path("/ws/design.spef"),
        design_name="gcd",
    )
    module.run_to(Path("/ws/config/to.json"))
    module.run_timing_opt_drv(Path("/ws/config/drv.json"))
    module.run_timing_opt_hold(Path("/ws/config/hold.json"))
    module.run_timing_opt_setup(Path("/ws/config/setup.json"))
    module.layout_patchs(Path("/ws/layout/patches.json"))
    module.layout_graph(Path("/ws/layout/graph.json"))
    module.generate_vectors(Path("/ws/vectors"))
    module.vectors_nets_to_def(Path("/ws/vectors"))
    module.vectors_nets_patterns_to_def(Path("/ws/vectors/patterns.json"))
    module.get_timing_wire_graph(Path("/ws/graph/wire.json"))
    module.get_timing_instance_graph(Path("/ws/graph/inst.json"))
    module.cell_density(save_path=Path("/ws/eval/cell.csv"))
    module.pin_density(save_path=Path("/ws/eval/pin.csv"))
    module.net_density(save_path=Path("/ws/eval/net.csv"))
    module.rudy_congestion(save_path=Path("/ws/eval/rudy.csv"))
    module.lut_rudy_congestion(save_path=Path("/ws/eval/lutrudy.csv"))
    module.egr_congestion(save_path=Path("/ws/eval/egr.csv"))
    module.eval_cell_hierarchy(Path("/ws/eval/cell.png"), 1, 1)
    module.eval_macro_hierarchy(Path("/ws/eval/macro.png"), 1, 1)
    module.eval_macro_connection(Path("/ws/eval/macro_conn.png"), 1, 1)
    module.eval_macro_pin_connection(Path("/ws/eval/macro_pin.png"), 1, 1)
    module.eval_macro_io_pin_connection(Path("/ws/eval/macro_io.png"), 1, 1)
    module.run_net_opt(Path("/ws/config/fixfanout.json"))

    _assert_no_path_values(module.ecc.calls)
    assert timing_output.read_text(encoding="utf-8") == module.ecc.generated_timing_lib_contents
    assert [
        call[0]
        for call in module.ecc.calls
        if call[0] in {
            "lib_init",
            "sdc_init",
            "spef_init",
            "init_sta",
            "extract_lib",
            "destroy_sta",
        }
    ] == ["lib_init", "sdc_init", "spef_init", "init_sta", "extract_lib", "destroy_sta"]


def test_ecc_metrics_accept_path_feature_paths(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.NETLIST_OPT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)

    metrics = build_metrics_net_opt(workspace, step)

    assert metrics.report == [
        (str(step.feature["step"]).replace(".json", ".png"), f"{step.name} step metrics:\n")
    ]


def test_ecc_metrics_write_standard_qor_metrics_json(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    workspace.parameters.data["Max fanout"] = 20
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.NETLIST_OPT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["db"].write_text(
        json.dumps(
            {
                "Design Layout": {
                    "die_area": 2259.861,
                    "core_area": 1778.432,
                    "die_bounding_width": 47.538,
                    "die_bounding_height": 47.538,
                    "die_usage": 0.34,
                    "core_usage": 0.42,
                },
                "Design Statis": {
                    "num_iopins": 58,
                    "num_instances": 615,
                    "num_nets": 361,
                },
            }
        ),
        encoding="utf-8",
    )

    metrics = build_metrics_net_opt(workspace, step)

    assert metrics is not None
    assert step.analysis["qor_metrics"].exists()
    qor_metrics = json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))
    assert qor_metrics["schema_version"] == 3
    assert qor_metrics["tool"] == "ecc"
    assert qor_metrics["step"] == StepEnum.NETLIST_OPT.value
    assert qor_metrics["design"] == "gcd"

    records = {record["id"]: record for record in qor_metrics["metrics"]}
    assert records["fanout_max"] == {
        "id": "fanout_max",
        "display_name": "Max Fanout",
        "value": 20,
        "unit": "count",
        "category": "routability_physical",
        "direction": "lower_is_better",
        "scope": "fanout_repair",
        "corner": None,
        "project_role": "trend",
        "step_role": "primary",
        "analysis_group": "fixfanout_metrics",
        "rating": {"gate": False, "score": True, "trend": True},
        "confidence": "high",
        "source": {
            "kind": "feature",
            "path": "feature/fixFanout.db.json",
            "selector": "/Pins/max_fanout",
        },
    }
    assert records["core_utilization"]["value"] == 0.42
    assert records["core_utilization"]["direction"] == "target_range"
    assert records["core_area"]["value"] == 1778.432
    assert records["die_area"]["unit"] == "um^2"


def test_ecc_metrics_uses_actual_db_max_fanout_before_configured_target(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    workspace.parameters.data["Max fanout"] = 20
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.NETLIST_OPT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["db"].write_text(
        json.dumps({"Pins": {"max_fanout": 37}}),
        encoding="utf-8",
    )

    metrics = build_metrics_net_opt(workspace, step)

    assert metrics.data["Max fanout"] == 37
    records = {
        record["id"]: record
        for record in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))[
            "metrics"
        ]
    }
    assert records["fanout_max"]["value"] == 37


def test_ecc_metrics_write_standard_qor_summary_json(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    workspace.parameters.data["Max fanout"] = 20
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.NETLIST_OPT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["db"].write_text(
        json.dumps(
            {
                "Design Layout": {
                    "die_area": 2259.861,
                    "die_bounding_width": 47.538,
                    "die_bounding_height": 47.538,
                    "die_usage": 0.34,
                    "core_usage": 0.42,
                },
                "Design Statis": {
                    "num_iopins": 58,
                    "num_instances": 615,
                    "num_nets": 361,
                },
            }
        ),
        encoding="utf-8",
    )

    metrics = build_metrics_net_opt(workspace, step)

    assert metrics is not None
    assert step.analysis["qor_summary"].exists()
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    qor_metrics = json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))
    assert summary["schema_version"] == 4
    assert summary["tool"] == "ecc"
    assert summary["step"] == StepEnum.NETLIST_OPT.value
    assert summary["design"] == "gcd"
    assert summary["analysis_status"] == "valid"
    assert summary["quality_status"] == "pass"
    assert summary["metric_count"] == len(qor_metrics["metrics"])
    assert summary["metrics_file"] == "qor_metrics.json"
    assert summary["gates"] == []
    assert summary["missing_metrics"] == []
    assert summary["dimensions"]["routability_physical"]["metric_count"] >= 1


def test_ecc_metrics_qor_summary_marks_blocking_drc_violations(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.DRC.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["step"].write_text(
        json.dumps({"drc": {"number": 3}}),
        encoding="utf-8",
    )

    metrics = build_metrics_drc(workspace, step)

    assert metrics is not None
    assert step.analysis["qor_summary"].exists()
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["quality_status"] == "blocked"
    assert summary["gates"] == [
        {
            "id": "qor.drc.clean",
            "title": "Final DRC clean",
            "state": "failed",
            "blocking": True,
            "metrics": [
                {
                    "id": "drc_count",
                    "actual": 3,
                    "operator": "==",
                    "expected": 0,
                    "source": {
                        "kind": "feature",
                        "path": "feature/drc.step.json",
                        "selector": "/drc/number",
                    },
                }
            ],
            "evidence": [
                {
                    "kind": "feature",
                    "path": "feature/drc.step.json",
                    "selector": "/drc/number",
                }
            ],
        }
    ]
    hotspots = json.loads(step.analysis["qor_hotspots"].read_text(encoding="utf-8"))
    assert hotspots["hotspots"] == []


def test_ecc_metrics_emits_bounded_drc_rule_layer_qor_hotspots(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.DRC.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["step"].write_text(
        json.dumps(
            {
                "drc": {
                    "number": 99,
                    "distribution": {
                        "Antenna": {"layers": {"M1": {"number": 12}}},
                        "MinimumSpacing": {
                            "layers": {
                                "M3": {
                                    "number": 12,
                                    "violation_detail": [{"bbox": [1, 2, 3, 4]}],
                                },
                                "M4": {"number": 12},
                            }
                        },
                        "MinimumWidth": {"layers": {"M2": {"number": 11}}},
                        "Rule05": {"layers": {"M5": {"number": 10}}},
                        "Rule06": {"layers": {"M6": {"number": 9}}},
                        "Rule07": {"layers": {"M7": {"number": 8}}},
                        "Rule08": {"layers": {"M8": {"number": 7}}},
                        "Rule09": {"layers": {"M9": {"number": 6}}},
                        "Rule10": {"layers": {"M10": {"number": 5}}},
                        "Rule11": {"layers": {"M11": {"number": 4}}},
                        "Zero": {"layers": {"M12": {"number": 0}}},
                        "Invalid": {"layers": {"M13": {"number": "invalid"}}},
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    metrics = build_metrics_drc(workspace, step)

    assert metrics.data["drc_num"] == 99
    hotspots = json.loads(step.analysis["qor_hotspots"].read_text(encoding="utf-8"))
    records = hotspots["hotspots"]
    assert [(record["metric_id"], record["value"]) for record in records] == [
        ("drc:Antenna:M1", 12),
        ("drc:MinimumSpacing:M3", 12),
        ("drc:MinimumSpacing:M4", 12),
        ("drc:MinimumWidth:M2", 11),
        ("drc:Rule05:M5", 10),
        ("drc:Rule06:M6", 9),
        ("drc:Rule07:M7", 8),
        ("drc:Rule08:M8", 7),
        ("drc:Rule09:M9", 6),
        ("drc:Rule10:M10", 5),
    ]
    assert records[1] == {
        "kind": "drc_rule_layer",
        "severity": "critical",
        "metric_id": "drc:MinimumSpacing:M3",
        "display_name": "Minimum Spacing · M3",
        "value": 12,
        "unit": "count",
        "category": "clock_robustness_dfm",
        "source": {
            "kind": "feature",
            "path": "feature/drc.step.json",
            "selector": "/drc/distribution/MinimumSpacing/layers/M3",
        },
        "description": "12 DRC violations: Minimum Spacing on M3.",
    }
    assert all("violation_detail" not in record and "bbox" not in record for record in records)
    qor_metrics = json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))
    details = {detail["id"]: detail for detail in qor_metrics["details"]}
    assert details["drc_rule_layer_summary"] == {
        "id": "drc_rule_layer_summary",
        "presentation": "rule_layer_table",
        "summary": {
            "top_violations": [
                {
                    "metric_id": "drc:Antenna:M1",
                    "display_name": "Antenna · M1",
                    "value": 12,
                    "unit": "count",
                },
                {
                    "metric_id": "drc:MinimumSpacing:M3",
                    "display_name": "Minimum Spacing · M3",
                    "value": 12,
                    "unit": "count",
                },
                {
                    "metric_id": "drc:MinimumSpacing:M4",
                    "display_name": "Minimum Spacing · M4",
                    "value": 12,
                    "unit": "count",
                },
                {
                    "metric_id": "drc:MinimumWidth:M2",
                    "display_name": "Minimum Width · M2",
                    "value": 11,
                    "unit": "count",
                },
                {
                    "metric_id": "drc:Rule05:M5",
                    "display_name": "Rule05 · M5",
                    "value": 10,
                    "unit": "count",
                },
                {
                    "metric_id": "drc:Rule06:M6",
                    "display_name": "Rule06 · M6",
                    "value": 9,
                    "unit": "count",
                },
                {
                    "metric_id": "drc:Rule07:M7",
                    "display_name": "Rule07 · M7",
                    "value": 8,
                    "unit": "count",
                },
                {
                    "metric_id": "drc:Rule08:M8",
                    "display_name": "Rule08 · M8",
                    "value": 7,
                    "unit": "count",
                },
                {
                    "metric_id": "drc:Rule09:M9",
                    "display_name": "Rule09 · M9",
                    "value": 6,
                    "unit": "count",
                },
                {
                    "metric_id": "drc:Rule10:M10",
                    "display_name": "Rule10 · M10",
                    "value": 5,
                    "unit": "count",
                },
            ],
        },
        "feature_source": {
            "kind": "feature",
            "path": "feature/drc.step.json",
            "selector": "/drc/distribution",
        },
    }


def test_ecc_metrics_omits_missing_drc_and_legalization_values(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    drc_step = build_step(
        workspace=workspace,
        step_name=StepEnum.DRC.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(drc_step)
    drc_step.feature["step"].write_text(json.dumps({"drc": {}}), encoding="utf-8")

    drc_metrics = build_metrics_drc(workspace, drc_step)

    assert "drc_num" not in drc_metrics.data
    drc_summary = json.loads(drc_step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert drc_summary["missing_metrics"] == [{
        "metric_id": "drc_count",
        "reason": (
            "Required field /drc/number is absent or non-numeric in "
            "feature/drc.step.json; metric drc_count was not produced."
        ),
        "evidence": {
            "source": {
                "kind": "feature",
                "path": "feature/drc.step.json",
                "selector": "/drc/number",
            },
            "diagnosis": (
                "Required field /drc/number is absent or non-numeric in "
                "feature/drc.step.json; metric drc_count was not produced."
            ),
            "availability": "source_field_missing",
        },
    }]

    legal_step = build_step(
        workspace=workspace,
        step_name=StepEnum.LEGALIZATION.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(legal_step)
    legal_step.feature["step"].write_text(
        json.dumps({"legalization": {}}),
        encoding="utf-8",
    )

    legal_metrics = build_metrics_legalization(workspace, legal_step)

    assert "total_movement" not in legal_metrics.data
    legal_summary = json.loads(
        legal_step.analysis["qor_summary"].read_text(encoding="utf-8")
    )
    assert legal_summary["missing_metrics"] == []


def test_ecc_metrics_extract_place_map_qor_metrics(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.PLACEMENT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    egr_union_csv = tmp_path / "place_egr_union_overflow.csv"
    egr_union_csv.write_text("0,1\n2,3\n", encoding="utf-8")
    cell_density_csv = tmp_path / "place_allcell_density.csv"
    cell_density_csv.write_text("0,0.5\n1,invalid\n", encoding="utf-8")
    pin_density_csv = tmp_path / "place_allcell_pin_density.csv"
    pin_density_csv.write_text("0,2\n4,6\n", encoding="utf-8")
    margin_union_csv = tmp_path / "place_union_margin.csv"
    margin_union_csv.write_text("10,20\n30,40\n", encoding="utf-8")
    step.feature["map"].write_text(
        json.dumps(
            {
                "Wirelength": {
                    "HPWL": 3880214,
                    "GRWL": 4509000,
                    "FLUTE": 4562638,
                },
                "Congestion": {
                    "map": {
                        "egr": {"union": str(egr_union_csv)},
                    },
                    "overflow": {
                        "total": {"union": 13},
                        "max": {"union": 3},
                    },
                    "utilization": {
                        "rudy": {"max": {"union": 0.004728000145405531}},
                        "lutrudy": {"max": {"union": 0.005274999886751175}},
                    },
                },
                "Density": {
                    "cell": {"allcell_density": str(cell_density_csv)},
                    "pin": {"allcell_pin_density": str(pin_density_csv)},
                    "margin": {"union": str(margin_union_csv)},
                },
            }
        ),
        encoding="utf-8",
    )

    metrics = build_metrics_placement(workspace, step)

    assert metrics.data["HPWL"] == 3880.214
    assert metrics.data["GRWL"] == 4509
    assert metrics.data["FLUTE"] == 4562.638
    assert metrics.data["place_congestion_egr_overflow_total"] == 13
    assert metrics.data["place_congestion_egr_overflow_max"] == 3
    assert metrics.data["place_rudy_utilization_max"] == 0.004728000145405531
    assert metrics.data["place_lutrudy_utilization_max"] == 0.005274999886751175
    map_records = {
        (record["group"], record["metric"], record.get("direction")): record
        for record in metrics.data["place_map_metrics"]["maps"]
    }
    assert metrics.data["place_map_metrics"]["source_file"] == str(step.feature["map"])
    assert map_records[("congestion", "egr", "union")] == {
        "group": "congestion",
        "metric": "egr",
        "direction": "union",
        "source_file": str(egr_union_csv),
        "available": True,
        "row_count": 2,
        "column_count": 2,
        "value_count": 4,
        "nonzero_count": 3,
        "nonzero_ratio": 0.75,
        "max": 3,
        "top_5_percent_average": 3,
        "high_bin_threshold": 2.7,
        "high_bin_count": 1,
        "high_bin_ratio": 0.25,
    }
    assert map_records[("cell", "allcell_density", None)]["value_count"] == 3
    assert map_records[("cell", "allcell_density", None)]["max"] == 1
    assert map_records[("pin", "allcell_pin_density", None)]["high_bin_count"] == 1
    assert map_records[("margin", "union", None)]["top_5_percent_average"] == 40

    records = {
        record["id"]: record
        for record in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))[
            "metrics"
        ]
    }
    assert records["place_hpwl"]["value"] == 3880.214
    assert records["place_grwl"]["value"] == 4509
    assert records["place_congestion_egr_overflow_total"]["value"] == 13
    assert records["place_lutrudy_utilization_max"]["value"] == 0.005274999886751175
    assert "place_map_metrics" not in records
    details = {
        detail["id"]: detail
        for detail in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))["details"]
    }
    assert details["place_map_metrics"]["presentation"] == "place_map_summary"
    assert details["place_map_metrics"]["feature_source"]["path"] == "feature/place.map.json"
    hotspots = json.loads(step.analysis["qor_hotspots"].read_text(encoding="utf-8"))
    assert hotspots["schema_version"] == 3
    assert hotspots["tool"] == "ecc"
    assert hotspots["step"] == StepEnum.PLACEMENT.value
    hotspot_records = {record["metric_id"]: record for record in hotspots["hotspots"]}
    assert hotspot_records["place_congestion_egr_overflow_total"] == {
        "kind": "congestion",
        "severity": "warning",
        "metric_id": "place_congestion_egr_overflow_total",
        "display_name": "Place EGR Overflow Total",
        "value": 13,
        "unit": "count",
        "category": "routability_physical",
        "source": {
            "kind": "feature",
            "path": "feature/place.map.json",
            "selector": "/Congestion/overflow/total/union",
        },
        "description": "Placement EGR overflow is present.",
    }
    assert hotspot_records["place_congestion_egr_overflow_max"]["value"] == 3


def test_ecc_metrics_extract_cts_extended_qor_metrics(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.CTS.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["step"].write_text(
        json.dumps(
            {
                "CTS": {
                    "buffer_area": 8.4,
                    "buffer_num": 3,
                    "clock_path_max_buffer": 2,
                    "clock_path_min_buffer": 2,
                    "max_clock_wirelength": 97514,
                    "max_level_of_clock_tree": 2,
                    "total_clock_wirelength": 261677,
                    "timing_quality": {
                        "schema_version": 1,
                        "analysis_stage": "cts_fast_sta_post_optimization",
                        "availability": "available",
                        "clock_count": 2,
                        "target_unmet_count": 1,
                        "worst_optimized_skew_ns": 0.11,
                        "worst_max_insertion_latency_ns": 0.42,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    legacy_metrics = step.analysis["dir"] / "CTS_metrics.json"
    legacy_preview = step.analysis["dir"] / "CTS_metrics.png"
    legacy_metrics.write_text("{}", encoding="utf-8")
    legacy_preview.write_text("legacy", encoding="utf-8")

    metrics = build_metrics_cts(workspace, step)

    assert metrics.data["max_clock_wirelength"] == 97514
    assert metrics.data["max_level_of_clock_tree"] == 2
    assert not legacy_metrics.exists()
    assert not legacy_preview.exists()
    records = {
        record["id"]: record
        for record in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))[
            "metrics"
        ]
    }
    assert records["cts_clock_wirelength_max"]["value"] == 97514
    assert records["cts_clock_tree_max_level"]["value"] == 2
    assert records["cts_worst_optimized_skew_ns"] == {
        "id": "cts_worst_optimized_skew_ns",
        "display_name": "CTS Worst Optimized Skew Estimate",
        "value": 0.11,
        "unit": "ns",
        "category": "clock_robustness_dfm",
        "direction": "lower_is_better",
        "scope": "cts",
        "corner": None,
        "project_role": "trend",
        "step_role": "primary",
        "analysis_group": "cts_metrics",
        "rating": {"gate": False, "score": True, "trend": True},
        "confidence": "medium",
        "source": {
            "kind": "feature",
            "path": "feature/CTS.step.json",
            "selector": "/CTS/timing_quality/worst_optimized_skew_ns",
        },
    }
    assert records["cts_worst_max_insertion_latency_ns"] == {
        "id": "cts_worst_max_insertion_latency_ns",
        "display_name": "CTS Worst Max Insertion Latency Estimate",
        "value": 0.42,
        "unit": "ns",
        "category": "clock_robustness_dfm",
        "direction": "lower_is_better",
        "scope": "cts",
        "corner": None,
        "project_role": "trend",
        "step_role": "primary",
        "analysis_group": "cts_metrics",
        "rating": {"gate": False, "score": True, "trend": True},
        "confidence": "medium",
        "source": {
            "kind": "feature",
            "path": "feature/CTS.step.json",
            "selector": "/CTS/timing_quality/worst_max_insertion_latency_ns",
        },
    }
    details = {
        detail["id"]: detail
        for detail in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))["details"]
    }
    assert details["cts_clock_skew_metrics"] == {
        "id": "cts_clock_skew_metrics",
        "presentation": "cts_clock_skew_table",
        "summary": {
            "schema_version": 1,
            "clock_count": 2,
            "target_unmet_count": 1,
            "worst_optimized_skew_ns": 0.11,
            "worst_max_insertion_latency_ns": 0.42,
        },
        "feature_source": {
            "kind": "feature",
            "path": "feature/CTS.step.json",
            "selector": "/CTS/timing_quality",
        },
    }
    assert records["clock_path_max_buffer"]["source"] == {
        "kind": "feature",
        "path": "feature/CTS.step.json",
        "selector": "/CTS/clock_path_max_buffer",
    }
    assert records["clock_path_min_buffer"]["source"] == {
        "kind": "feature",
        "path": "feature/CTS.step.json",
        "selector": "/CTS/clock_path_min_buffer",
    }


def test_ecc_metrics_persists_structured_cts_timing_without_log(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.CTS.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["step"].write_text(json.dumps({"CTS": {}}), encoding="utf-8")
    timing_quality = {
        "schema_version": 1,
        "analysis_stage": "cts_fast_sta_post_optimization",
        "availability": "available",
        "clock_count": 2,
        "clocks": [
            {
                "clock": "clk_a",
                "sink_count": 10,
                "target_skew_ns": 0.08,
                "initial_skew_ns": 0.12,
                "optimized_skew_ns": 0.06,
                "min_insertion_latency_ns": 0.11,
                "max_insertion_latency_ns": 0.31,
                "mean_insertion_latency_ns": 0.2,
                "target_met": True,
            },
            {
                "clock": "clk_b",
                "sink_count": 12,
                "target_skew_ns": 0.05,
                "initial_skew_ns": 0.04,
                "optimized_skew_ns": 0.07,
                "min_insertion_latency_ns": 0.13,
                "max_insertion_latency_ns": 0.42,
                "mean_insertion_latency_ns": 0.25,
                "target_met": False,
            },
        ],
        "worst_optimized_skew_ns": 0.07,
        "worst_max_insertion_latency_ns": 0.42,
        "target_unmet_count": 1,
    }

    assert ecc_metrics.save_cts_timing_feature_facts(step, timing_quality)
    metrics = build_metrics_cts(workspace, step)

    assert metrics.data["cts_worst_optimized_skew_ns"] == 0.07
    assert metrics.data["cts_worst_max_insertion_latency_ns"] == 0.42
    assert metrics.data["cts_skew_target_unmet_count"] == 1
    feature = json.loads(step.feature["step"].read_text(encoding="utf-8"))
    assert feature["CTS"]["timing_quality"] == timing_quality


def test_ecc_metrics_excludes_cts_metrics_without_feature_provenance(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.CTS.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    untraceable_feature = tmp_path / "untraceable_cts.step.json"
    untraceable_feature.write_text(
        json.dumps({"CTS": {"buffer_num": 3}}),
        encoding="utf-8",
    )
    step.feature["step"] = untraceable_feature

    metrics = build_metrics_cts(workspace, step)

    assert metrics.data["buffer_num"] == 3
    payload = json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))
    assert payload["metrics"] == []
    assert payload["integrity"] == {
        "status": "incomplete",
        "invalid_metric_source_ids": ["cts_buffer_count"],
        "invalid_detail_ids": [],
    }
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["analysis_status"] == "incomplete"
    assert summary["quality_status"] == "pass"
    assert {
        "metric_id": "cts_buffer_count",
        "reason": (
            "Metric cts_buffer_count resolved outside the current step feature "
            "directory and was rejected."
        ),
        "evidence": {
            "diagnosis": (
                "Metric cts_buffer_count resolved outside the current step feature "
                "directory and was rejected."
            ),
            "availability": "invalid_source",
        },
    } in summary["missing_metrics"]


def test_ecc_metrics_extract_route_step_qor_metrics(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.ROUTING.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["step"].write_text(
        json.dumps(
            {
                "route": {
                    "LA": {
                        "cut_via_num_map": {"1": 100, "2": 200},
                        "routing_demand_map": {"1": 500, "2": 750},
                        "routing_overflow_map": {"1": 2, "2": 0},
                        "routing_wire_length_map": {"1": 125.5, "2": 240.25},
                        "total_demand": 10431,
                        "total_overflow": 2,
                    },
                    "DR": [
                        {
                            "cut_via_num_map": {"1": 101, "2": 201},
                            "iter": 1,
                            "routing_patch_num_map": {"1": 4, "2": 5},
                            "routing_violation_num_map": {"1": 3, "2": 2},
                            "routing_wire_length_map": {"1": 130, "2": 245},
                            "total_patch_num": 48,
                            "total_via_num": 1477,
                            "total_violation_num": 5,
                            "total_wire_length": 5200.535,
                        },
                        {
                            "cut_via_num_map": {"1": 99, "2": 198},
                            "iter": 3,
                            "routing_patch_num_map": {"1": 1, "2": 3},
                            "routing_violation_num_map": {"1": 0, "2": 0},
                            "routing_wire_length_map": {"1": 126.5, "2": 241.75},
                            "total_patch_num": 46,
                            "total_via_num": 1470,
                            "total_violation_num": 0,
                            "total_wire_length": 5198.943,
                        },
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    metrics = build_metrics_routing(workspace, step)

    assert metrics.data["route_la_total_overflow"] == 2
    assert metrics.data["route_la_total_demand"] == 10431
    assert metrics.data["route_dr_total_violation_count"] == 0
    assert metrics.data["route_dr_total_patch_count"] == 46
    assert metrics.data["route_dr_total_wirelength"] == 5198.943
    assert metrics.data["route_dr_total_via_count"] == 1470
    assert metrics.data["route_layer_metrics"] == {
        "schema_version": 1,
        "source_file": str(step.feature["step"]),
        "final_dr_iteration": 3,
        "layers": [
            {
                "layer": "1",
                "layer_index": 1,
                "la": {
                    "demand": 500,
                    "overflow": 2,
                    "wirelength": 125.5,
                    "via_count": 100,
                },
                "dr": {
                    "wirelength": 126.5,
                    "via_count": 99,
                    "violation_count": 0,
                    "patch_count": 1,
                },
            },
            {
                "layer": "2",
                "layer_index": 2,
                "la": {
                    "demand": 750,
                    "overflow": 0,
                    "wirelength": 240.25,
                    "via_count": 200,
                },
                "dr": {
                    "wirelength": 241.75,
                    "via_count": 198,
                    "violation_count": 0,
                    "patch_count": 3,
                },
            },
        ],
    }

    records = {
        record["id"]: record
        for record in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))[
            "metrics"
        ]
    }
    assert records["route_la_total_overflow"]["value"] == 2
    assert records["route_dr_total_violation_count"]["value"] == 0
    assert records["route_dr_total_wirelength"]["value"] == 5198.943
    assert "route_layer_metrics" not in records
    details = {
        detail["id"]: detail
        for detail in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))["details"]
    }
    assert details["route_layer_metrics"]["presentation"] == "layer_table"
    assert details["route_layer_metrics"]["feature_source"]["path"] == "feature/route.step.json"
    hotspots = json.loads(step.analysis["qor_hotspots"].read_text(encoding="utf-8"))
    hotspot_records = {record["metric_id"]: record for record in hotspots["hotspots"]}
    assert hotspot_records["route_la_total_overflow"] == {
        "kind": "routing_overflow",
        "severity": "critical",
        "metric_id": "route_la_total_overflow",
        "display_name": "Route LA Overflow",
        "value": 2,
        "unit": "count",
        "category": "routability_physical",
        "source": {
            "kind": "feature",
            "path": "feature/route.step.json",
            "selector": "/route/LA",
        },
        "description": "Route layer assignment overflow is present.",
    }
    assert "route_dr_total_violation_count" not in hotspot_records


def test_ecc_metrics_qor_summary_lists_missing_supported_route_metrics(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.ROUTING.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["db"].write_text(
        json.dumps({"Nets": {"wire_len": 5198.943, "num_via": 1470}}),
        encoding="utf-8",
    )

    metrics = build_metrics_routing(workspace, step)

    assert metrics is not None
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert [item["metric_id"] for item in summary["missing_metrics"]] == [
        "route_dr_total_violation_count",
        "route_dr_total_patch_count",
        "route_dr_total_wirelength",
        "route_dr_total_via_count",
        "route_la_total_overflow",
        "route_la_total_demand",
    ]


def test_ecc_metrics_extract_rcx_output_completeness(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.RCX.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    existing_spef = [
        step.output["dir"] / "gcd_Cbest_125C.spef",
        step.output["dir"] / "gcd_Cworst_125C.spef",
    ]
    missing_spef = step.output["dir"] / "gcd_TYPICAL_25C.spef"
    existing_spef[0].write_text(
        """*SPEF \"IEEE 1481-1998\"
*C_UNIT 1.0 PF
*R_UNIT 1.0 KOHM
*D_NET net_a 0.75
*CAP
1 net_a:1 0.25
2 net_a:1 net_a:2 0.50
*RES
1 net_a:1 net_a:2 2.0
*END
""",
        encoding="utf-8",
    )
    existing_spef[1].write_text(
        """*SPEF \"IEEE 1481-1998\"
*C_UNIT 1.0 FF
*R_UNIT 1.0 OHM
*D_NET net_b 15.0
*CAP
1 net_b:1 5.0
2 net_b:1 net_b:2 10.0
*RES
1 net_b:1 net_b:2 20.0
*END
""",
        encoding="utf-8",
    )
    step.output["spef"] = [*existing_spef, missing_spef]
    step.output["def"].write_text("def", encoding="utf-8")
    step.output["gds"].write_text("gds", encoding="utf-8")

    assert ecc_metrics.save_rcx_spef_feature_facts(workspace, step)
    for spef_path in existing_spef:
        spef_path.unlink()
    metrics = ecc_metrics.build_metrics_rcx(workspace, step)

    assert metrics.data["rcx_spef_file_count"] == 2
    assert metrics.data["rcx_expected_corner_count"] == 3
    assert metrics.data["rcx_missing_corner_count"] == 1
    assert metrics.data["rcx_spef_parse_failure_count"] == 0
    assert metrics.data["rcx_worst_total_capacitance_ff"] == 750
    assert metrics.data["rcx_worst_coupling_capacitance_ff"] == 500
    assert metrics.data["rcx_worst_total_resistance_ohm"] == 2000
    assert metrics.data["rcx_output_def_exists"] == 1
    assert metrics.data["rcx_output_gds_exists"] == 1
    records = {
        record["id"]: record
        for record in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))[
            "metrics"
        ]
    }
    assert records["rcx_spef_file_count"]["value"] == 2
    assert records["rcx_missing_corner_count"]["value"] == 1
    assert records["rcx_output_def_exists"]["analysis_group"] == "rcx_output_artifacts"
    assert records["rcx_output_def_exists"]["rating"] == {
        "gate": False,
        "score": False,
        "trend": True,
    }
    assert records["rcx_output_gds_exists"]["rating"]["score"] is False
    assert records["rcx_worst_total_capacitance_ff"]["source"] == {
        "kind": "feature",
        "path": "feature/RCX.step.json",
        "selector": "/rcx/signoff_metrics/parasitic_envelope/worst_total_capacitance_ff",
    }
    details = {
        detail["id"]: detail
        for detail in json.loads(
            step.analysis["qor_metrics"].read_text(encoding="utf-8")
        )["details"]
    }
    rcx_detail = details["rcx_electrical_corner_metrics"]
    assert rcx_detail["presentation"] == "rcx_spef_corner_table"
    assert rcx_detail["feature_source"] == {
        "kind": "feature",
        "path": "feature/RCX.step.json",
        "selector": "/rcx/signoff_metrics",
    }
    assert rcx_detail["summary"]["coverage"] == {
        "status": "incomplete",
        "expected_count": 3,
        "available_count": 2,
        "missing_count": 1,
        "unparseable_count": 0,
        "missing_corners": ["TYPICAL_25C"],
        "unparseable_corners": [],
    }
    assert records["rcx_missing_corner_count"]["source"] == {
        "kind": "feature",
        "path": "feature/RCX.step.json",
        "selector": "/rcx/signoff_metrics/coverage/missing_count",
    }
    rcx_feature = json.loads(step.feature["step"].read_text(encoding="utf-8"))
    assert rcx_feature["rcx"]["electrical_summary"] == {
        "schema_version": 1,
        "parsed_corner_count": 2,
        "parse_failure_count": 0,
        "corners": [
            {
                "corner": "Cbest_125C",
                "net_count": 1,
                "ground_capacitance_count": 1,
                "ground_capacitance_ff": 250,
                "coupling_capacitance_count": 1,
                "coupling_capacitance_ff": 500,
                "total_capacitance_ff": 750,
                "resistance_count": 1,
                "total_resistance_ohm": 2000,
            },
            {
                "corner": "Cworst_125C",
                "net_count": 1,
                "ground_capacitance_count": 1,
                "ground_capacitance_ff": 5,
                "coupling_capacitance_count": 1,
                "coupling_capacitance_ff": 10,
                "total_capacitance_ff": 15,
                "resistance_count": 1,
                "total_resistance_ohm": 20,
            },
        ],
        "parse_failures": [],
        "worst_total_capacitance_ff": 750,
        "worst_coupling_capacitance_ff": 500,
        "worst_total_resistance_ohm": 2000,
    }


def test_ecc_metrics_blocks_invalid_rcx_spef_electrical_data(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.RCX.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    spef_path = step.output["dir"] / "gcd_Cbest_125C.spef"
    spef_path.write_text(
        """*SPEF \"IEEE 1481-1998\"
*C_UNIT 1.0 FF
*R_UNIT 1.0 OHM
*D_NET net_a 1.0
*CAP
invalid cap record
*END
""",
        encoding="utf-8",
    )
    step.output["spef"] = [spef_path]

    assert ecc_metrics.save_rcx_spef_feature_facts(workspace, step)
    metrics = ecc_metrics.build_metrics_rcx(workspace, step)

    assert metrics.data["rcx_spef_parse_failure_count"] == 1
    assert "rcx_worst_total_capacitance_ff" not in metrics.data
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["quality_status"] == "blocked"
    assert {gate["id"]: gate["state"] for gate in summary["gates"]} == {
        "qor.rcx.corner_coverage": "failed",
        "qor.rcx.spef_parse_health": "failed",
    }


def test_ecc_metrics_extract_sta_multi_corner_summary(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.STA.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)

    reports = {
        step.feature["dir"] / "MAX_125" / "RCworst" / "qor_summary.json": {
            "path_groups": [
                {
                    "name": "core",
                    "setup": {"wns": -0.2, "tns": -1.2, "nvp": 3, "frequency_mhz": 750},
                    "hold": {"wns": 0.1, "tns": 0.0, "nvp": 0},
                },
                {
                    "name": "io",
                    "setup": {"wns": -0.1, "tns": -0.4, "nvp": 1, "frequency_mhz": 800},
                    "hold": {"wns": -0.2, "tns": -0.2, "nvp": 2},
                },
            ],
            "summary": {
                "setup": {"wns": -0.2, "tns": -1.2, "nvp": 3, "frequency_mhz": 750},
                "hold": {"wns": 0.1, "tns": 0.0, "nvp": 0},
            },
            "design_statistics": {},
        },
        step.feature["dir"] / "MIN_m40" / "Cbest" / "qor_summary.json": {
            "path_groups": [
                {
                    "name": "core",
                    "setup": {"wns": 0.3, "tns": 0.0, "nvp": 0, "frequency_mhz": 900},
                    "hold": {"wns": -0.05, "tns": -0.1, "nvp": 1},
                },
                {
                    "name": "io",
                    "setup": {"wns": 0.2, "tns": -0.1, "nvp": 0, "frequency_mhz": 880},
                    "hold": {"wns": 0.2, "tns": 0.0, "nvp": 0},
                },
            ],
            "summary": {
                "setup": {"wns": 0.3, "tns": 0.0, "nvp": 0, "frequency_mhz": 900},
                "hold": {"wns": -0.05, "tns": -0.1, "nvp": 1},
            },
            "design_statistics": {},
        },
    }
    for report_path, payload in reports.items():
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload), encoding="utf-8")
    timing_paths = {
        "MAX_125/RCworst": {
            "schema_version": 1,
            "corner": "MAX_125/RCworst",
            "path_limit": 20,
            "paths": [{
                "path_id": "setup_path",
                "analysis_type": "setup",
                "path_group": "core",
                "start_point": "u_launch:CK",
                "end_point": "u_capture:D",
                "launch_clock": "clk",
                "capture_clock": "clk",
                "check_type": "setup",
                "slack_ns": -0.2,
                "arrival_ns": 1.2,
                "required_ns": 1.0,
                "cppr_ns": 0.0,
                "launch_clock_network_delay_ns": 0.12,
                "capture_clock_network_delay_ns": 0.18,
                "stages": [{
                    "kind": "cell_arc",
                    "pin": "u_buf:Y",
                    "instance": "u_buf",
                    "cell": "BUFX3",
                    "incremental_delay_ns": 0.12,
                    "arrival_ns": 1.2,
                    "transition": "rise",
                }],
            }],
        },
        "MIN_m40/Cbest": {
            "schema_version": 1,
            "corner": "MIN_m40/Cbest",
            "path_limit": 20,
            "paths": [{
                "path_id": "hold_path",
                "analysis_type": "hold",
                "path_group": "core",
                "start_point": "u_launch:CK",
                "end_point": "u_capture:D",
                "launch_clock": "clk",
                "capture_clock": "clk",
                "check_type": "hold",
                "slack_ns": -0.05,
                "arrival_ns": 0.25,
                "required_ns": 0.2,
                "cppr_ns": 0.0,
                "launch_clock_network_delay_ns": 0.08,
                "capture_clock_network_delay_ns": 0.04,
                "stages": [{
                    "kind": "net_arc",
                    "pin": "u_net:Y",
                    "instance": "u_net",
                    "cell": "",
                    "incremental_delay_ns": 0.08,
                    "arrival_ns": 0.25,
                    "transition": "fall",
                }],
            }],
        },
    }
    for corner, payload in timing_paths.items():
        path = step.feature["dir"] / corner / "timing_paths.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

    metrics = ecc_metrics.build_metrics_sta(workspace, step)

    assert metrics.data["max_WNS"] == -0.2
    assert metrics.data["max_TNS"] == -1.2
    assert metrics.data["min_WNS"] == -0.05
    assert metrics.data["min_TNS"] == -0.1
    assert metrics.data["Frequency [MHz]"] == 750
    assert metrics.data["sta_corner_count"] == 2
    assert metrics.data["sta_expected_corner_count"] == 2
    assert metrics.data["sta_missing_corner_count"] == 0
    assert metrics.data["setup_violation_count"] == 3
    assert metrics.data["hold_violation_count"] == 1
    assert metrics.data["sta_worst_setup_corner"] == "MAX_125/RCworst"
    assert metrics.data["sta_worst_hold_corner"] == "MIN_m40/Cbest"
    assert step.analysis["metrics"].name == "qor_metrics.json"
    sta_path_group_metrics = metrics.data["sta_path_group_metrics"]
    assert len(sta_path_group_metrics["records"]) == 4
    core_group = next(
        group for group in sta_path_group_metrics["path_groups"]
        if group["path_group"] == "core"
    )
    assert core_group == {
        "path_group": "core",
        "corner_count": 2,
        "setup": {
            "worst_wns": -0.2,
            "worst_wns_corner": "MAX_125/RCworst",
            "worst_tns": -1.2,
            "worst_tns_corner": "MAX_125/RCworst",
            "minimum_frequency_mhz": 750,
            "minimum_frequency_mhz_corner": "MAX_125/RCworst",
            "nvp_total": 3,
        },
        "hold": {
            "worst_wns": -0.05,
            "worst_wns_corner": "MIN_m40/Cbest",
            "worst_tns": -0.1,
            "worst_tns_corner": "MIN_m40/Cbest",
            "nvp_total": 1,
        },
    }
    io_record = next(
        record for record in sta_path_group_metrics["records"]
        if record["path_group"] == "io" and record["corner"] == "MAX_125/RCworst"
    )
    assert io_record["setup"] == {
        "wns": -0.1,
        "tns": -0.4,
        "nvp": 1,
        "frequency_mhz": 800,
    }
    assert io_record["hold"] == {"wns": -0.2, "tns": -0.2, "nvp": 2}
    records = {
        record["id"]: record
        for record in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))[
            "metrics"
        ]
    }
    assert records["sta_setup_wns"]["value"] == -0.2
    assert records["sta_hold_wns"]["value"] == -0.05
    assert records["sta_frequency_mhz"]["value"] == 750
    assert records["sta_corner_count"]["value"] == 2
    assert records["sta_setup_violation_count"]["value"] == 3
    assert records["sta_hold_violation_count"]["value"] == 1
    assert records["sta_setup_wns"]["corner"] == "MAX_125/RCworst"
    assert records["sta_hold_wns"]["corner"] == "MIN_m40/Cbest"
    assert records["sta_setup_wns"]["source"] == {
        "kind": "feature",
        "path": "feature/MAX_125/RCworst/qor_summary.json",
        "selector": "/summary/setup/wns",
    }
    assert records["sta_hold_wns"]["source"] == {
        "kind": "feature",
        "path": "feature/MIN_m40/Cbest/qor_summary.json",
        "selector": "/summary/hold/wns",
    }
    assert records["sta_setup_violation_count"]["source"] == {
        "kind": "feature",
        "path": "feature/sta.step.json",
        "selector": "/sta/signoff_metrics/setup/violation_count",
    }
    assert records["sta_corner_count"]["source"] == {
        "kind": "feature",
        "path": "feature/sta.step.json",
        "selector": "/sta/signoff_metrics/coverage/available_count",
    }
    sta_feature = json.loads(step.feature["step"].read_text(encoding="utf-8"))["sta"]
    assert {
        key: sta_feature[key]
        for key in (
            "corner_count",
            "expected_corner_count",
            "missing_corner_count",
            "setup_violation_count",
            "hold_violation_count",
            "loaded_corners",
            "missing_corners",
        )
    } == {
        "corner_count": 2,
        "expected_corner_count": 2,
        "missing_corner_count": 0,
        "setup_violation_count": 3,
        "hold_violation_count": 1,
        "loaded_corners": ["MAX_125/RCworst", "MIN_m40/Cbest"],
        "missing_corners": [],
    }
    assert sta_feature["signoff_metrics"]["coverage"]["status"] == "unavailable"
    assert "sta_path_group_metrics" not in records
    details = {
        detail["id"]: detail
        for detail in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))["details"]
    }
    assert details["sta_path_group_metrics"]["presentation"] == "path_group_table"
    assert details["sta_path_group_metrics"]["feature_source"]["path"] == (
        "feature/MAX_125/RCworst/qor_summary.json"
    )
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["quality_status"] == "incomplete"
    assert {gate["id"]: gate["state"] for gate in summary["gates"]} == {
        "qor.sta.setup_closed": "unavailable",
        "qor.sta.hold_closed": "unavailable",
    }
    issues = json.loads(step.analysis["sta_timing_issues"].read_text(encoding="utf-8"))
    assert issues["near_fail_slack_ns"] == 0.05
    assert [issue["issue_id"] for issue in issues["issues"]] == [
        "sta_timing:MAX_125/RCworst:setup:setup_path",
        "sta_timing:MIN_m40/Cbest:hold:hold_path",
    ]
    assert issues["issues"][0]["dominant_stages"][0]["pin"] == "u_buf:Y"
    assert issues["issues"][0]["source_file"] == "feature/MAX_125/RCworst/timing_paths.json"
    assert issues["issues"][0]["launch_clock_network_delay_ns"] == 0.12
    assert issues["issues"][0]["capture_clock_network_delay_ns"] == 0.18
    assert issues["issues"][0]["clock_network_delay_delta_ns"] == 0.06
    assert issues["artifact_paths"] == [
        {
            "corner": "MAX_125/RCworst",
            "report_dir": "report/MAX_125/RCworst",
            "feature_dir": "feature/MAX_125/RCworst",
            "qor_summary_file": "feature/MAX_125/RCworst/qor_summary.json",
            "timing_paths_file": "feature/MAX_125/RCworst/timing_paths.json",
        },
        {
            "corner": "MIN_m40/Cbest",
            "report_dir": "report/MIN_m40/Cbest",
            "feature_dir": "feature/MIN_m40/Cbest",
            "qor_summary_file": "feature/MIN_m40/Cbest/qor_summary.json",
            "timing_paths_file": "feature/MIN_m40/Cbest/timing_paths.json",
        },
    ]


def test_ecc_metrics_marks_missing_configured_sta_corner(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.STA.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    sta_config = tmp_path / "config" / "sta.json"
    sta_config.parent.mkdir(parents=True, exist_ok=True)
    sta_config.write_text(
        json.dumps({
            "liberty": [
                {"corner": "MAX", "temperature": 125},
                {"corner": "MIN", "temperature": -40},
            ],
            "signoff": [{"MAX": ["RCworst"], "MIN": ["Cbest"]}],
        }),
        encoding="utf-8",
    )
    workspace.config[StepEnum.STA.value] = sta_config
    feature_path = step.feature["dir"] / "MAX_125" / "RCworst" / "qor_summary.json"
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    feature_path.write_text(
        json.dumps({
            "path_groups": [],
            "summary": {
                "setup": {"wns": 0.1, "tns": 0.0, "nvp": 0, "frequency_mhz": 750},
                "hold": {"wns": 0.1, "tns": 0.0, "nvp": 0},
            },
            "design_statistics": {},
        }),
        encoding="utf-8",
    )

    metrics = ecc_metrics.build_metrics_sta(workspace, step)

    assert metrics.data["sta_corner_count"] == 1
    assert metrics.data["sta_expected_corner_count"] == 2
    assert metrics.data["sta_missing_corner_count"] == 1
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["quality_status"] == "incomplete"
    assert {gate["id"]: gate["state"] for gate in summary["gates"]} == {
        "qor.sta.setup_closed": "unavailable",
        "qor.sta.hold_closed": "unavailable",
    }


def test_ecc_metrics_classifies_configured_sta_pvt_rc_corners(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.STA.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    sta_config = tmp_path / "config" / "sta.json"
    sta_config.parent.mkdir(parents=True, exist_ok=True)
    sta_config.write_text(
        json.dumps({
            "liberty": [
                {
                    "corner": "MAX",
                    "temperature": 125,
                    "path": ["/pdk/lib/design_ss_rcworst_1p08_125.lib"],
                },
                {
                    "corner": "MIN",
                    "temperature": -40,
                    "path": ["/pdk/lib/design_ff_rcbest_1p32_m40.lib"],
                },
            ],
            "signoff": [{"MAX": ["RCworst"], "MIN": ["RCbest"]}],
        }),
        encoding="utf-8",
    )
    workspace.config[StepEnum.STA.value] = sta_config
    for corner, setup, hold in (
        (
            "MAX_125/RCworst",
            {"wns": 0.04, "tns": 0.0, "nvp": 0, "frequency_mhz": 700},
            {"wns": 0.1, "tns": 0.0, "nvp": 0},
        ),
        (
            "MIN_m40/RCbest",
            {"wns": 0.2, "tns": 0.0, "nvp": 0, "frequency_mhz": 800},
            {"wns": 0.03, "tns": 0.0, "nvp": 0},
        ),
    ):
        summary_path = step.feature["dir"] / corner / "qor_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps({
                "path_groups": [],
                "summary": {"setup": setup, "hold": hold},
                "design_statistics": {},
            }),
            encoding="utf-8",
        )

    metrics = ecc_metrics.build_metrics_sta(workspace, step)

    feature = json.loads(step.feature["step"].read_text(encoding="utf-8"))["sta"]
    signoff = feature["signoff_metrics"]
    assert signoff["coverage"] == {
        "status": "pass",
        "expected_count": 2,
        "available_count": 2,
        "missing_count": 0,
        "unparseable_count": 0,
        "missing_corners": [],
        "unparseable_corners": [],
    }
    corners = {corner["sta_corner"]: corner for corner in signoff["corners"]}
    assert corners["MAX_125/RCworst"] == {
        "sta_corner": "MAX_125/RCworst",
        "configured_role": "MAX",
        "process_corner": "SS",
        "voltage_v": 1.08,
        "temperature_c": 125,
        "rc_corner": "RCworst",
        "label": "MAX - SS - 1.08 V - 125 C - RCworst",
        "availability": "available",
        "reason": None,
        "summary_file": "feature/MAX_125/RCworst/qor_summary.json",
    }
    assert corners["MIN_m40/RCbest"]["process_corner"] == "FF"
    assert corners["MIN_m40/RCbest"]["voltage_v"] == 1.32
    records = {
        record["id"]: record
        for record in json.loads(
            step.analysis["qor_metrics"].read_text(encoding="utf-8")
        )["metrics"]
    }
    assert records["sta_setup_wns"]["analysis_group"] == "sta_setup_closure"
    assert records["sta_setup_wns"]["corner_context"] == {
        "configured_role": "MAX",
        "process_corner": "SS",
        "voltage_v": 1.08,
        "temperature_c": 125,
        "rc_corner": "RCworst",
        "label": "MAX - SS - 1.08 V - 125 C - RCworst",
    }
    assert records["sta_setup_wns"]["rating"] == {
        "gate": True,
        "score": True,
        "trend": True,
    }
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["quality_status"] == "pass"
    assert {gate["id"]: gate["state"] for gate in summary["gates"]} == {
        "qor.sta.setup_closed": "pass",
        "qor.sta.hold_closed": "pass",
    }
    assert metrics.data["sta_worst_setup_corner"] == "MAX_125/RCworst"


def test_ecc_metrics_sta_does_not_fallback_to_legacy_report_json(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.STA.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    legacy_path = step.output["dir"] / "MAX_125" / "RCworst" / "gcd.rpt.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps({
            "summary": [{"delay_type": "max", "freq": 750}],
            "slack": [{"delay_type": "max", "WNS": 0.1, "TNS": 0.0}],
        }),
        encoding="utf-8",
    )

    metrics = ecc_metrics.build_metrics_sta(workspace, step)

    assert "max_WNS" not in metrics.data
    assert metrics.data["sta_corner_count"] == 0
    qor_metrics = json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))
    assert qor_metrics["details"] == []
    assert qor_metrics["integrity"] == {
        "status": "pass",
        "invalid_metric_source_ids": [],
        "invalid_detail_ids": [],
    }
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert "sta_setup_wns" in {
        item["metric_id"] for item in summary["missing_metrics"]
    }
    assert summary["analysis_status"] == "incomplete"
    assert summary["quality_status"] == "incomplete"


def test_ecc_metrics_extract_harden_artifact_completeness(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.HARDEN.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.output["gds"].write_text("gds", encoding="utf-8")
    step.output["lef"].write_text("lef", encoding="utf-8")
    step.output["lib"].write_text("lib", encoding="utf-8")
    step.output["image"].write_text("png", encoding="utf-8")

    metrics = ecc_metrics.build_metrics_harden(workspace, step)

    assert metrics.data["harden_gds_exists"] == 1
    assert metrics.data["harden_lef_exists"] == 1
    assert metrics.data["harden_lib_exists"] == 1
    assert "harden_preview_exists" not in metrics.data
    assert "harden_lib_check_exists" not in metrics.data
    assert metrics.data["harden_artifact_missing_count"] == 0
    records = {
        record["id"]: record
        for record in json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))[
            "metrics"
        ]
    }
    assert records["harden_artifact_missing_count"]["value"] == 0
    assert records["harden_gds_exists"]["value"] == 1
    assert "harden_preview_exists" not in records
    assert "harden_lib_check_exists" not in records
    assert records["harden_artifact_missing_count"]["source"] == {
        "kind": "feature",
        "path": "feature/Harden.step.json",
        "selector": "/harden/artifact_missing_count",
    }
    harden_feature = json.loads(step.feature["step"].read_text(encoding="utf-8"))
    assert harden_feature["harden"]["artifact_missing_count"] == 0
    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["quality_status"] == "pass"
    assert summary["gates"] == []


def _write_harden_signoff_summary(tmp_path, step_name, *, status="pass", hard_gates=None):
    summary_path = tmp_path / f"{step_name}_ecc" / "analysis" / "qor_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps({
            "schema_version": 3,
            "step": step_name,
            "status": status,
            "hard_gates": hard_gates or [],
            "blocking_issues": [],
            "missing_metrics": [],
        }),
        encoding="utf-8",
    )


def _write_harden_output_artifacts(step):
    for output_key, contents in (
        ("gds", "gds"),
        ("lef", "lef"),
        ("lib", "lib"),
    ):
        step.output[output_key].write_text(contents, encoding="utf-8")


def _green_sta_hard_gates():
    return [
        {"id": gate_id, "passed": True}
        for gate_id in (
            "sta_setup_wns_clean",
            "sta_setup_tns_clean",
            "sta_setup_violation_free",
            "sta_hold_wns_clean",
            "sta_hold_tns_clean",
            "sta_hold_violation_free",
        )
    ]


def test_ecc_metrics_harden_summarizes_completed_signoff_sources(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    workspace.flow.data = {
        "steps": [
            {"name": StepEnum.DRC.value, "state": "Success"},
            {"name": StepEnum.STA.value, "state": "Success"},
            {"name": StepEnum.RCX.value, "state": "Success"},
        ]
    }
    _write_harden_signoff_summary(tmp_path, StepEnum.DRC.value)
    _write_harden_signoff_summary(
        tmp_path,
        StepEnum.STA.value,
        hard_gates=_green_sta_hard_gates(),
    )
    _write_harden_signoff_summary(tmp_path, StepEnum.RCX.value)
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.HARDEN.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    _write_harden_output_artifacts(step)

    ecc_metrics.build_metrics_harden(workspace, step)

    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["schema_version"] == 4
    assert summary["quality_status"] == "pass"
    assert summary["gates"] == []


def test_ecc_metrics_harden_rejects_stale_signoff_summary(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    workspace.flow.data = {
        "steps": [
            {"name": StepEnum.DRC.value, "state": "Incomplete"},
            {"name": StepEnum.STA.value, "state": "Success"},
            {"name": StepEnum.RCX.value, "state": "Success"},
        ]
    }
    _write_harden_signoff_summary(tmp_path, StepEnum.DRC.value)
    _write_harden_signoff_summary(
        tmp_path,
        StepEnum.STA.value,
        hard_gates=_green_sta_hard_gates(),
    )
    _write_harden_signoff_summary(tmp_path, StepEnum.RCX.value)
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.HARDEN.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    _write_harden_output_artifacts(step)

    ecc_metrics.build_metrics_harden(workspace, step)

    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["schema_version"] == 4
    assert summary["quality_status"] == "pass"
    assert summary["gates"] == []


def test_ecc_plot_step_metrics_accepts_path_metrics(tmp_path, monkeypatch):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.NETLIST_OPT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.analysis["metrics"].write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        ecc_plot,
        "plot_metrics",
        lambda metrics, output_path: calls.append((metrics, output_path)) or True,
    )

    assert ecc_plot.ECCToolsPlot(workspace, step).plot_step_metrics() is True
    assert calls == [
        ({}, str(step.analysis["metrics"]).replace(".json", ".png")),
    ]


def test_ecc_plot_instance_distribution_accepts_path_feature_db(tmp_path, monkeypatch):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.NETLIST_OPT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["db"].write_text(
        json.dumps({"Instances": {"stdcell": {"num": 1, "area": 2, "pin_num": 3}}}),
        encoding="utf-8",
    )
    plot_calls = []
    metric_calls = []
    workspace.home = SimpleNamespace(
        set_metrics_inst_dist=lambda image_path: metric_calls.append(image_path),
    )
    monkeypatch.setattr(
        chipcompiler_utility,
        "plot_bar_chart",
        lambda **kwargs: plot_calls.append(kwargs) or True,
    )

    assert ecc_plot.ECCToolsPlot(workspace, step).plot_instance_distribution() is True

    expected_image_path = str(step.feature["db"]).replace(".json", ".inst_dist.png")
    assert plot_calls[0]["output_path"] == expected_image_path
    assert metric_calls == [expected_image_path]


def test_ecc_plot_drc_statis_accepts_path_statis_csv(tmp_path, monkeypatch):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.DRC.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["db"].write_text(
        json.dumps(
            {
                "Layers": {
                    "cut_layers": [],
                    "routing_layers": [
                        {"layer_name": "M1", "layer_order": 1},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    step.feature["step"].write_text(
        json.dumps(
            {
                "drc": {
                    "number": 2,
                    "distribution": {
                        "short": {"layers": {"M1": {"number": 2}}},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    plot_calls = []
    metric_calls = []
    workspace.home = SimpleNamespace(
        set_metrics_drc_dist=lambda image_path: metric_calls.append(image_path),
    )

    def record_bar_chart(**kwargs):
        assert isinstance(kwargs["input_path"], str)
        assert isinstance(kwargs["output_path"], str)
        plot_calls.append(kwargs)
        return True

    monkeypatch.setattr(ecc_plot, "plot_csv_bar_chart", record_bar_chart)

    assert ecc_plot.ECCToolsPlot(workspace, step).plot_drc_statis() is True

    expected_image_path = str(step.analysis["statis_csv"]).replace(".csv", ".png")
    assert plot_calls[0]["input_path"] == str(step.analysis["statis_csv"])
    assert plot_calls[0]["output_path"] == expected_image_path
    assert metric_calls == [expected_image_path]


def test_ecc_builder_constructs_path_objects_without_changing_text(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    input_def = tmp_path / "input.def"
    input_verilog = tmp_path / "input.v"

    step = build_step(
        workspace=workspace,
        step_name=StepEnum.PLACEMENT.value,
        input_def=input_def,
        input_verilog=input_verilog,
    )

    expected_step_dir = tmp_path / f"{StepEnum.PLACEMENT.value}_ecc"
    expected_output_dir = expected_step_dir / "output"
    expected_view_dir = expected_output_dir / f"gcd_{StepEnum.PLACEMENT.value}_view"
    assert step.directory == expected_step_dir
    assert isinstance(step.directory, Path)
    assert step.input["def"] == input_def
    assert step.input["verilog"] == input_verilog
    assert step.output["dir"] == expected_output_dir
    assert step.output["view_json"] == expected_view_dir
    assert step.output["view_json_edits"] == expected_view_dir / "edits" / "layout_edits.json"
    assert step.analysis["qor_metrics"] == expected_step_dir / "analysis" / "qor_metrics.json"
    assert step.analysis["qor_summary"] == expected_step_dir / "analysis" / "qor_summary.json"
    assert step.analysis["qor_hotspots"] == expected_step_dir / "analysis" / "qor_hotspots.json"
    assert step.analysis["sta_timing_issues"] == (
        expected_step_dir / "analysis" / "sta_timing_issues.json"
    )
    assert step.report["sta"] == {"dir": expected_step_dir / "report"}
    assert step.feature["sta"] == {
        "dir": expected_step_dir / "feature",
        "qor_summary_root": expected_step_dir / "feature",
        "timing_paths_root": expected_step_dir / "feature",
    }
    assert str(step.output["view_json"]) == (
        f"{expected_step_dir}/output/gcd_{StepEnum.PLACEMENT.value}_view"
    )
    assert str(step.output["view_json_edits"]) == (
        f"{expected_step_dir}/output/gcd_{StepEnum.PLACEMENT.value}_view/edits/layout_edits.json"
    )


def test_ecc_build_step_space_creates_path_directories(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )

    step = build_step(
        workspace=workspace,
        step_name=StepEnum.FLOORPLAN.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )

    build_step_space(step)

    assert isinstance(step.output["dir"], Path)
    assert step.output["dir"].is_dir()
    assert step.data["dir"].is_dir()
    assert step.feature["dir"].is_dir()
    assert step.report["dir"].is_dir()
    assert step.log["dir"].is_dir()
    assert step.script["dir"].is_dir()
    assert step.analysis["dir"].is_dir()
    assert (step.directory / "data" / "pl" / "density").is_dir()
    assert (step.directory / "data" / "pl" / "report").is_dir()


def test_ecc_subflow_writes_path_payload_as_json_strings(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.PLACEMENT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)

    EccSubFlow(workspace, step)

    with open(step.subflow["path"], encoding="utf-8") as file:
        data = json.load(file)
    assert data["path"] == str(step.subflow["path"])


def test_ecc_step_info_stringifies_path_payloads(tmp_path, monkeypatch):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        config={StepEnum.PLACEMENT.value: tmp_path / "config" / "pl.json"},
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.PLACEMENT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    monkeypatch.setattr(
        ecc_service,
        "build_step_metrics",
        lambda workspace, step: SimpleNamespace(path=tmp_path / "metrics.json"),
    )

    assert ecc_service.get_step_info(workspace, step, "views") == {
        "image": str(step.output["image"]),
        "json": str(step.output["json"]),
        "metrics": str(tmp_path / "metrics.json"),
        "information": {},
    }
    assert ecc_service.get_step_info(workspace, step, "layout") == {
        "image": str(step.output["image"]),
        "json": str(step.output["json"]),
    }
    assert ecc_service.get_step_info(workspace, step, "metrics") == {
        "metrics": str(tmp_path / "metrics.json"),
    }
    assert ecc_service.get_step_info(workspace, step, "subflow") == {
        "path": str(step.subflow["path"])
    }
    assert ecc_service.get_step_info(workspace, step, "config") == {
        "config": str(workspace.config[StepEnum.PLACEMENT.value]),
    }
    assert ecc_service.get_step_info(workspace, step, "analysis") == {
        "metrics": str(step.analysis["metrics"]),
        "qor_metrics": str(step.analysis["qor_metrics"]),
        "qor_summary": str(step.analysis["qor_summary"]),
        "qor_hotspots": str(step.analysis["qor_hotspots"]),
        "statis": str(step.analysis["statis_csv"]),
        "data summary": str(step.feature["db"]),
        "step feature": str(step.feature["step"]),
        "step report": str(step.report["db"]),
    }
    assert ecc_service.get_step_info(workspace, step, "sta") == {
        "report_root": str(step.report["dir"]),
        "feature_root": str(step.feature["dir"]),
        "qor_summary_root": str(step.feature["dir"]),
        "timing_paths_root": str(step.feature["dir"]),
    }


def test_ecc_builder_uses_explicit_step_directory(tmp_path):
    workspace = Workspace(
        directory=str(tmp_path),
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step_directory = tmp_path / "timing_optimization_sizer"

    step = build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
        tool="sizer",
        step_directory=step_directory,
    )

    assert step.name == StepEnum.TIMING_OPT.value
    assert step.directory == step_directory
    assert isinstance(step.directory, Path)
    assert step.output["dir"] == step_directory / "output"
    assert step.data[StepEnum.TIMING_OPT.value] == step_directory / "data" / "to"
    assert step.log["file"] == step_directory / "log" / f"{StepEnum.TIMING_OPT.value}.log"
    assert str(step.output["dir"]) == f"{step_directory}/output"
    assert str(step.data[StepEnum.TIMING_OPT.value]) == f"{step_directory}/data/to"
    assert str(step.log["file"]) == f"{step_directory}/log/{StepEnum.TIMING_OPT.value}.log"
