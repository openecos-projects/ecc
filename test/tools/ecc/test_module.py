#!/usr/bin/env python

import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc import service as ecc_service
from chipcompiler.tools.ecc.builder import build_step, build_step_space
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.subflow import EccSubFlow


class FakeEcc:
    def __init__(self):
        self.calls = []

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

    def view_json_save(self, **kwargs):
        self.calls.append(("view_json_save", kwargs))
        return True

    def view_json_apply_edits(self, **kwargs):
        self.calls.append(("view_json_apply_edits", kwargs))
        return True


def test_ecc_tools_module_imports_installed_native_extension():
    module = ECCToolsModule()
    assert module.get_ecc() is not None


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

    assert module.view_json_save(output_dir="/tmp/view_json", json_format="compact", compress=True) is True

    assert module.ecc.calls == [
        ("view_json_save", {"output_dir": "/tmp/view_json", "json_format": "compact", "compress": True}),
    ]


def test_view_json_apply_edits_passes_compress_option():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    assert module.view_json_apply_edits(edits_path="/tmp/view_json/edits/layout_edits.json.gz", compress=True) is True

    assert module.ecc.calls == [
        ("view_json_apply_edits", {"edits_path": "/tmp/view_json/edits/layout_edits.json.gz", "compress": True}),
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
    module.init_sta(
        output_dir=Path("/ws/sta"),
        top_module="gcd",
        lib_paths=[Path("/pdk/lib.lib")],
        sdc_path=Path("/ws/design.sdc"),
    )
    module.read_liberty([Path("/pdk/lib.lib")])
    module.read_sdc(Path("/ws/design.sdc"))

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
        ("init_sta", {"output": "/ws/sta"}),
        ("read_liberty", ["/pdk/lib.lib"]),
        ("read_sdc", "/ws/design.sdc"),
    ]


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
