"""Contract of each tool's get_step_info for the path-projection ids.

The GUI and the CLI read these dictionaries, so the keys and the empty-field
values are pinned for an unset step and for a fully populated one. ids that read
files (maps, metrics, views for ECC) are covered by the tool's own tests.
"""

from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data import EccStep, OriginDesign, StepEnum, Workspace, YosysStep
from chipcompiler.tools.ecc.service import get_step_info as ecc_info
from chipcompiler.tools.ecc_dreamplace.service import get_step_info as dreamplace_info
from chipcompiler.tools.ecc_sizer.service import get_step_info as sizer_info
from chipcompiler.tools.yosys.service import get_step_info as yosys_info

# (id, expected for an unset step, expected for a populated step; "{r}" is the tmp root)
ECC = [
    ("layout", {"image": "", "json": ""}, {"image": "{r}/output/image", "json": "{r}/output/json"}),
    ("subflow", {"path": ""}, {"path": "{r}/subflow/path"}),
    ("checklist", {"path": ""}, {"path": "{r}/checklist/path"}),
    (
        "analysis",
        {
            "data summary": "",
            "metrics": "",
            "qor_hotspots": "",
            "qor_metrics": "",
            "qor_summary": "",
            "statis": "",
            "step feature": "",
            "step report": "",
        },
        {
            "data summary": "{r}/feature/db",
            "metrics": "{r}/analysis/metrics",
            "qor_hotspots": "{r}/analysis/qor_hotspots",
            "qor_metrics": "{r}/analysis/qor_metrics",
            "qor_summary": "{r}/analysis/qor_summary",
            "statis": "{r}/analysis/statis_csv",
            "step feature": "{r}/feature/step",
            "step report": "{r}/report/db",
        },
    ),
    (
        "sta",
        {"feature_root": "", "qor_summary_root": "", "report_root": "", "timing_paths_root": ""},
        {
            "feature_root": "{r}/feature/dir",
            "qor_summary_root": "{r}/feature/dir",
            "report_root": "{r}/report/dir",
            "timing_paths_root": "{r}/feature/dir",
        },
    ),
]

YOSYS = [
    ("layout", {"image": ""}, {"image": "{r}/output/image"}),
    ("subflow", {"path": ""}, {"path": "{r}/subflow/path"}),
    ("checklist", {"path": ""}, {"path": "{r}/checklist/path"}),
    (
        "analysis",
        {"data summary": "", "metrics": "", "step report": ""},
        {
            "data summary": "{r}/feature/stat",
            "metrics": "{r}/analysis/metrics",
            "step report": "{r}/report/check",
        },
    ),
    (
        "views",
        {"image": "", "information": {}, "metrics": ""},
        {"image": "{r}/output/image", "information": {}, "metrics": "{r}/analysis/metrics"},
    ),
]

# The sizer reports unset input/output fields as None, the other tools as "".
SIZER = [
    ("subflow", {"path": ""}, {"path": "{r}/subflow/path"}),
    ("checklist", {"path": ""}, {"path": "{r}/checklist/path"}),
    (
        "input",
        {"db": None, "def": None, "verilog": None},
        {"db": "{r}/input/db", "def": "{r}/input/def_", "verilog": "{r}/input/verilog"},
    ),
    (
        "output",
        {
            "db": None,
            "def": None,
            "dir": None,
            "gds": None,
            "image": None,
            "json": None,
            "lef": None,
            "lib": None,
            "spef": [],
            "verilog": None,
        },
        {
            "db": "{r}/output/db",
            "def": "{r}/output/def_",
            "dir": "{r}/output/dir",
            "gds": "{r}/output/gds",
            "image": "{r}/output/image",
            "json": "{r}/output/json",
            "lef": "{r}/output/lef",
            "lib": "{r}/output/lib",
            "spef": [],
            "verilog": "{r}/output/verilog",
        },
    ),
]


def _populate(group, root: Path, name: str):
    """Give every unset Path field of a step group (and nested groups) a distinct path."""
    updates = {}
    for field in fields(group):
        value = getattr(group, field.name)
        if is_dataclass(value) and not isinstance(value, type):
            updates[field.name] = _populate(value, root, f"{name}/{field.name}")
        elif value is None or isinstance(value, (str, Path)):
            updates[field.name] = root / name / field.name
    return replace(group, **updates)


def _step(step_type, step_name: str, root: Path, *, populated: bool):
    step = step_type(name=step_name)
    if not populated:
        return step
    groups = {
        field.name: _populate(getattr(step, field.name), root, field.name)
        for field in fields(step)
        if is_dataclass(getattr(step, field.name))
    }
    return replace(step, **groups)


def _workspace(root: Path) -> Workspace:
    workspace = Workspace(
        directory=root,
        design=OriginDesign(name="top"),
        config={"db": root / "cfg/db.json"},
    )
    workspace.logger = SimpleNamespace(log_section=lambda *a, **k: None, info=lambda *a, **k: None)
    return workspace


def _expected(value, root: Path):
    if isinstance(value, dict):
        return {key: _expected(item, root) for key, item in value.items()}
    if isinstance(value, str):
        return value.format(r=root)
    return value


def _check(info, step_type, step_name, table, tmp_path):
    for populated in (False, True):
        step = _step(step_type, step_name, tmp_path, populated=populated)
        for step_id, unset, filled in table:
            expected = _expected(filled if populated else unset, tmp_path)
            assert info(_workspace(tmp_path), step, step_id) == expected, (step_id, populated)


def test_ecc_step_info_projections(tmp_path):
    _check(ecc_info, EccStep, StepEnum.PLACEMENT.value, ECC, tmp_path)


def test_dreamplace_step_info_reuses_the_ecc_projections(tmp_path):
    _check(dreamplace_info, EccStep, StepEnum.PLACEMENT.value, ECC, tmp_path)


def test_yosys_step_info_projections(tmp_path):
    _check(yosys_info, YosysStep, StepEnum.SYNTHESIS.value, YOSYS, tmp_path)


def test_sizer_step_info_projections(tmp_path):
    _check(sizer_info, EccStep, "timingOpt", SIZER, tmp_path)


@pytest.mark.parametrize("info", [ecc_info, yosys_info, sizer_info, dreamplace_info])
def test_unknown_step_info_id_is_empty(info, tmp_path):
    assert info(_workspace(tmp_path), EccStep(name="x"), "no-such-id") == {}


@pytest.mark.parametrize("step_name", [StepEnum.PRE_FLOORPLAN.value, StepEnum.POST_FLOORPLAN.value])
def test_ecc_config_info_maps_both_floorplan_steps_to_one_config(tmp_path, step_name):
    workspace = _workspace(tmp_path)
    workspace.config[StepEnum.FLOORPLAN.value] = tmp_path / "cfg/fp.json"
    info = ecc_info(workspace, EccStep(name=step_name), "config")
    assert info == {"config": str(tmp_path / "cfg/fp.json")}
