#!/usr/bin/env python

import json
from pathlib import Path
from types import SimpleNamespace

import chipcompiler.utility as chipcompiler_utility
from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc import plot as ecc_plot
from chipcompiler.tools.ecc import service as ecc_service
from chipcompiler.tools.ecc.builder import build_step, build_step_space
from chipcompiler.tools.ecc.metrics import build_metrics_net_opt
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.subflow import EccSubFlow


class FakeEcc:
    def __init__(self):
        self.calls = []
        self.generated_timing_lib_name = "gcd_max.lib"
        self.generated_timing_lib_contents = "library (gcd_max) {}\n"

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


def test_ecc_binding_wrappers_stringify_path_arguments():
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
        work_dir=Path("/ws/sta_work"),
        output_dir=Path("/ws/sta_report"),
        lib_paths=[Path("/pdk/lib.lib")],
        sdc_path=Path("/ws/design.sdc"),
        spef_path=Path("/ws/design.spef"),
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
                "config_dict": {"-temp_directory_path": "/ws/sta_work"},
            },
        ),
        ("run_sta", (), {}),
        ("destroy_sta", (), {}),
    ]


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
        "statis": str(step.analysis["statis_csv"]),
        "data summary": str(step.feature["db"]),
        "step feature": str(step.feature["step"]),
        "step report": str(step.report["db"]),
    }
    assert ecc_service.get_step_info(workspace, step, "sta") == {
        key: str(value)
        for key, value in step.report["sta"].items()
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
