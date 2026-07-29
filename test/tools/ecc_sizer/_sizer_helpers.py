"""Shared helpers for the ecc_sizer tool tests.

Kept local to this tool's test directory and imported by both the
builder/config tests (`test_module.py`) and the runner/flow tests
(`test_runner.py`): `_workspace` builds a sizer-ready workspace,
`_subflow_states` reads a step's persisted subflow state map, and
`_sizer_runtime` lays down a fake sizer runtime tree.
"""

import json
from pathlib import Path

from chipcompiler.data import PDK, OriginDesign, Parameters, Workspace


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
        parameters=Parameters(data={"Bottom layer": "M2", "Top layer": "M7"}),
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
