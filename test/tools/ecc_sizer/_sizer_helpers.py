"""Shared helpers for the ecc_sizer tool tests.

Kept local to this tool's test directory and imported by the
builder/config tests (`test_module.py`) and the runner/flow tests:
`_workspace` builds a sizer-ready workspace, `_subflow_states` reads a
step's persisted subflow state map, and `_sizer_runtime` lays down a
fake sizer runtime tree. Runner tests also share `_write_staging`,
`_fake_sizer_run`, and `_patch_success_legalize`.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import PDK, EccStep, OriginDesign, Parameters, Workspace


def _workspace(tmp_path):
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd", top_module="gcd"),
        pdk=PDK(
            tech=Path("tech.lef"),
            lefs=[Path("std.lef")],
            libs=[Path("slow.lib")],
            sdc=Path("clock.sdc"),
            spef=Path("route.spef"),
        ),
        parameters=Parameters(data={"bottom_layer": "M2", "top_layer": "M7"}),
    )
    workspace.home.init(tmp_path / "home.json")
    return workspace


def _subflow_states(step):
    with open(str(step.subflow.path), encoding="utf-8") as file:
        subflow = json.load(file)
    return {item["name"]: item["state"] for item in subflow["steps"]}


def _sizer_runtime(tmp_path):
    root = tmp_path / "sizer-runtime"
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "submit").mkdir(parents=True, exist_ok=True)
    (root / "src" / "sizer_os.tcl").write_text("# sizer tcl\n", encoding="utf-8")
    (root / "submit" / "env_base_file").write_text("-num_vt 1\n", encoding="utf-8")
    return root


class ExplodingEccModule:
    def __getattribute__(self, name):
        raise AssertionError(f"Sizer runner used ecc_module.{name}")


class FakeLegalizeModule:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _write_staging(step: EccStep) -> None:
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    staging_def = sizer_builder.sizer_staging_def(step)
    staging_verilog = sizer_builder.sizer_staging_verilog(step)
    staging_def.parent.mkdir(parents=True, exist_ok=True)
    staging_def.write_text("def\n", encoding="utf-8")
    staging_verilog.write_text("module gcd; endmodule\n", encoding="utf-8")


def _fake_sizer_run(step: EccStep):
    def fake_run(command, cwd, stdout, stderr, check):
        del command, cwd, stdout, stderr, check
        _write_staging(step)
        return SimpleNamespace(returncode=0)

    return fake_run


def _patch_success_legalize(monkeypatch, sizer_runner, step: EccStep, ecc=None):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    legalize_module = ecc or FakeLegalizeModule()
    seen = []

    def fake_legalize(workspace, owner_step, input_def, input_verilog):
        del workspace
        seen.append((owner_step, Path(input_def), Path(input_verilog)))
        assert owner_step is step
        assert Path(input_def) == sizer_builder.sizer_staging_def(step)
        assert Path(input_verilog) == sizer_builder.sizer_staging_verilog(step)
        return legalize_module

    def fake_save(*, workspace, step, ecc_module, feature_step):
        del workspace, ecc_module, feature_step
        os.makedirs(os.path.dirname(str(step.output.def_)), exist_ok=True)
        Path(step.output.def_).write_text("legal def\n", encoding="utf-8")
        Path(step.output.verilog).write_text("module gcd; endmodule\n", encoding="utf-8")
        if step.output.geometry_manifest is not None:
            Path(step.output.geometry).mkdir(parents=True, exist_ok=True)
            Path(step.output.geometry_manifest).write_text("schema=ecc.geometry.v1\n")
        return True

    monkeypatch.setattr(sizer_runner, "legalize_layout", fake_legalize)
    monkeypatch.setattr(sizer_runner.ecc_runner, "save_data", fake_save)
    legalize_module.seen = seen
    return legalize_module
