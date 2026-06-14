#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc.builder import build_step
from chipcompiler.tools.ecc.module import ECCToolsModule


class FakeEcc:
    def __init__(self):
        self.calls = []

    def init_rcx(self, **kwargs):
        self.calls.append(kwargs)
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


def test_view_json_save_passes_output_dir():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    assert module.view_json_save(output_dir="/tmp/view_json") is True

    assert module.ecc.calls == [
        ("view_json_save", {"output_dir": "/tmp/view_json"}),
    ]


def test_view_json_apply_edits_passes_edits_path():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()

    assert module.view_json_apply_edits(edits_path="/tmp/view_json/edits/layout_edits.json") is True

    assert module.ecc.calls == [
        ("view_json_apply_edits", {"edits_path": "/tmp/view_json/edits/layout_edits.json"}),
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
