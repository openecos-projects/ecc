"""Optional snapshots leave physical results intact, including in worker-built steps."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.data.parameter import Parameters
from chipcompiler.engine import EngineFlow
from chipcompiler.tools import eda
from chipcompiler.tools.ecc import ECCToolsModule, runner
from chipcompiler.tools.ecc.builder import build_step, build_step_space
from chipcompiler.tools.ecc.clock_tree import clock_tree_stage_for_step
from chipcompiler.tools.ecc.defview import run_defview
from chipcompiler.utility import json_write


@pytest.fixture
def native_snapshot():
    module = Mock(spec=ECCToolsModule)
    module.def_save.side_effect = lambda def_path: Path(def_path).write_text("DEF\n")
    module.verilog_save.side_effect = lambda output_verilog: Path(output_verilog).write_text(
        "module gcd(); endmodule\n"
    )
    module.feature_sammry.side_effect = lambda json_path: json_write(json_path, {})

    def save_geometry(output_dir, **_kwargs):
        directory = Path(output_dir)
        directory.mkdir(parents=True)
        (directory / "geometry.manifest").write_text("schema=ecc.geometry.v1\n")
        return True

    module.geometry_snapshot_save.side_effect = save_geometry
    return module


@pytest.mark.parametrize("enabled", [None, True, False], ids=["existing-workspace", "on", "off"])
def test_snapshot_policy_preserves_physical_results(tmp_path, native_snapshot, enabled):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        parameters=Parameters(data={} if enabled is None else {"geometry": {"snapshot": enabled}}),
    )
    step = build_step(workspace, StepEnum.ROUTING.value, None, None)
    build_step_space(step)
    assert runner.save_data(workspace, step, native_snapshot)
    capture = enabled is not False
    assert (
        step.output.geometry is not None,
        step.output.geometry_manifest is not None,
        step.output.image is not None,
        native_snapshot.geometry_snapshot_save.called,
    ) == (capture, capture, capture, capture)
    native_snapshot.def_save.assert_called_once_with(def_path=step.output.def_)
    native_snapshot.verilog_save.assert_called_once_with(output_verilog=step.output.verilog)
    native_snapshot.feature_step.assert_called_once_with(
        step=step.name, json_path=step.feature.step
    )
    native_snapshot.report_summary.assert_called_once_with(path=step.report.db)
    for path in (step.output.gds, step.feature.step, step.report.step):
        assert path is not None
        path.write_text("result\n")
    assert EngineFlow(workspace).check_step_result(step)


@pytest.mark.parametrize(
    "step_name", [StepEnum.POST_FLOORPLAN.value, StepEnum.CTS.value, StepEnum.FILLER.value]
)
def test_disabled_snapshot_also_disables_clock_tree_capture(tmp_path, step_name):
    workspace = Workspace(
        directory=tmp_path,
        parameters=Parameters(data={"geometry": {"snapshot": False, "clock_tree": True}}),
    )
    assert clock_tree_stage_for_step(workspace, step_name) is None
    workspace.parameters.data["geometry"]["snapshot"] = True
    assert clock_tree_stage_for_step(workspace, step_name) == step_name


def test_explicit_defview_still_exports_geometry(tmp_path, native_snapshot, monkeypatch):
    workspace = Workspace(
        directory=tmp_path,
        parameters=Parameters(data={"geometry": {"snapshot": False}}),
    )
    step = build_step(workspace, StepEnum.DEFVIEW.value, None, None)
    build_step_space(step)
    monkeypatch.setattr(
        "chipcompiler.tools.ecc.defview.get_eda_instance", lambda **_: native_snapshot
    )
    assert run_defview(workspace, step)
    native_snapshot.geometry_snapshot_save.assert_called_once_with(
        output_dir=step.output.geometry, thumbnail_path=step.output.image
    )
    assert EngineFlow(workspace).check_step_result(step)


def test_disabled_layout_image_does_not_load_renderer(tmp_path, monkeypatch):
    workspace = Workspace(
        directory=tmp_path,
        parameters=Parameters(data={"geometry": {"snapshot": False}}),
    )
    step = build_step(workspace, StepEnum.ROUTING.value, None, None)
    load_tool = Mock()
    monkeypatch.setattr(eda, "load_tool", load_tool)
    assert eda.save_layout_image(workspace, step)
    load_tool.assert_not_called()
