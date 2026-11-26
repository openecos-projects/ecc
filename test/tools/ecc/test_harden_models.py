"""Harden publishes models from each scenario's real inputs, not renamed TT models."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from chipcompiler.data import PDK, OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc import harden, runner
from chipcompiler.tools.ecc.builder import build_step, build_step_space
from chipcompiler.tools.ecc.module import ECCToolsModule


@pytest.fixture
def model_export(tmp_path, monkeypatch):
    config = tmp_path / "config/sta_ecc.json"
    config.parent.mkdir()
    config.write_text("{}")
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="project", top_module="core"),
        pdk=PDK(mapping_file=tmp_path / "layers.map"),
    )
    step = build_step(workspace, StepEnum.HARDEN.value, input_def=None, input_verilog=None)
    build_step_space(step)
    items = [
        {
            "corner": "TYP",
            "temperature": 25,
            "rcx_corner": "TYPICAL",
            "liberty_files": ["tt.lib"],
            "spef_file": "tt.spef",
        },
        {
            "corner": "MIN",
            "temperature": -40,
            "rcx_corner": "Cbest",
            "liberty_files": ["ff.lib"],
            "spef_file": "cbest.spef",
        },
    ]
    native = Mock(spec=ECCToolsModule)

    def write_model(**kwargs):
        path = kwargs["output_lib_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"libraries": kwargs["lib_paths"], "spef": kwargs["spef_path"]}))

    native.write_timing_model.side_effect = write_model
    monkeypatch.setattr(runner, "EccSubFlow", Mock())
    monkeypatch.setattr(runner, "collect_sta_signoff_items", lambda *_: items)
    monkeypatch.setattr(runner, "get_eda_instance", lambda **_: native)
    monkeypatch.setattr(runner, "run_analysis", Mock())
    monkeypatch.setattr(
        harden, "step_tcl_path", lambda _ws, _step, *, corner, rc: tmp_path / f"{corner}_{rc}.tcl"
    )
    return workspace, step, items, native


def test_harden_extracts_each_scenario_and_keeps_typical_entry(model_export):
    workspace, step, items, native = model_export
    assert runner.run_harden(workspace, step)
    default_lib = Path(step.output.lib)
    root = default_lib.parent / "timing_models"
    manifest = json.loads((root / "manifest.json").read_text())
    expected = []
    for item, call in zip(items, native.write_timing_model.call_args_list, strict=True):
        scenario = (
            f"{item['corner']}_{str(item['temperature']).replace('-', 'm')}/{item['rcx_corner']}"
        )
        model = root / scenario / "core.lib"
        sdc = workspace.directory / f"{item['corner']}_{item['rcx_corner']}.tcl"
        assert call.kwargs == {
            "output_lib_path": model,
            "config": str(workspace.directory / "config/sta_ecc.json"),
            "output_dir": Path(step.data.steps["sta"]) / scenario,
            "lib_paths": item["liberty_files"],
            "sdc_path": sdc,
            "spef_path": item["spef_file"],
            "design_name": "core",
        }
        expected.append(
            {
                "corner": item["corner"],
                "temperature": item["temperature"],
                "rc_corner": item["rcx_corner"],
                "analysis_mode": "max",
                "path": f"{scenario}/core.lib",
                "source_libraries": item["liberty_files"],
                "sdc": str(sdc),
                "spef": item["spef_file"],
            }
        )
    assert manifest == {"schema_version": 1, "models": expected}
    assert default_lib.read_bytes() == (root / "TYP_25/TYPICAL/core.lib").read_bytes()
    assert default_lib.read_bytes() != (root / "MIN_m40/Cbest/core.lib").read_bytes()


def test_failed_model_rerun_does_not_publish_old_catalog(model_export):
    workspace, step, _items, native = model_export
    assert runner.run_harden(workspace, step)
    default_lib = Path(step.output.lib)
    native.write_timing_model.side_effect = RuntimeError("extraction failed")
    with pytest.raises(RuntimeError, match="extraction failed"):
        runner.run_harden(workspace, step)
    assert not default_lib.exists()
    assert not (default_lib.parent / "timing_models/manifest.json").exists()


def test_narrowed_rerun_removes_unselected_models(model_export):
    workspace, step, items, _native = model_export
    assert runner.run_harden(workspace, step)
    items.pop()
    assert runner.run_harden(workspace, step)
    root = Path(step.output.lib).parent / "timing_models"
    assert sorted(path.relative_to(root).as_posix() for path in root.rglob("*.lib")) == [
        "TYP_25/TYPICAL/core.lib"
    ]


def test_harden_manifest_failure_is_not_success(model_export, monkeypatch):
    workspace, step, _items, _native = model_export
    monkeypatch.setattr(harden, "json_write", lambda *_: False)
    with pytest.raises(RuntimeError, match="Failed to publish Harden timing-model manifest"):
        runner.run_harden(workspace, step)
