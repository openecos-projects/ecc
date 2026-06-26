#!/usr/bin/env python

from pathlib import Path

from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc.builder import build_step
from chipcompiler.tools.ecc.module import ECCToolsModule


class FakeEcc:
    def __init__(self):
        self.calls = []

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

    module.init_techlef(Path("/pdk/tech.lef"))
    module.init_lefs([Path("/pdk/std.lef")])
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
        ("tech_lef_init", "/pdk/tech.lef"),
        ("lef_init", {"lef_paths": ["/pdk/std.lef"]}),
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


def test_ecc_builder_constructs_view_json_paths(tmp_path):
    workspace = Workspace(
        directory=str(tmp_path),
        design=OriginDesign(name="gcd", top_module="gcd"),
    )

    step = build_step(
        workspace=workspace,
        step_name=StepEnum.PLACEMENT.value,
        input_def="/tmp/input.def",
        input_verilog="/tmp/input.v",
    )

    expected_dir = f"{step.directory}/output/gcd_{StepEnum.PLACEMENT.value}_view"
    assert step.output["view_json"] == expected_dir
    assert step.output["view_json_edits"] == f"{expected_dir}/edits/layout_edits.json"


def test_ecc_builder_uses_explicit_step_directory(tmp_path):
    workspace = Workspace(
        directory=str(tmp_path),
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step_directory = str(tmp_path / "timing_optimization_sizer")

    step = build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="/tmp/input.def",
        input_verilog="/tmp/input.v",
        tool="sizer",
        step_directory=step_directory,
    )

    assert step.name == StepEnum.TIMING_OPT.value
    assert step.directory == step_directory
    assert step.output["dir"] == f"{step_directory}/output"
    assert step.data[StepEnum.TIMING_OPT.value] == f"{step_directory}/data/to"
    assert step.log["file"] == f"{step_directory}/log/{StepEnum.TIMING_OPT.value}.log"
