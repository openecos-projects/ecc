from pathlib import Path
from unittest.mock import Mock

import pytest

from chipcompiler.data import OriginDesign, Workspace
from chipcompiler.tools import eda, lec_layout
from chipcompiler.tools.registry import load_builder


@pytest.mark.parametrize("tool", ["kepler_formal"])
def test_checked_layout_is_owned_by_each_lec_step_and_does_not_change_flow_inputs(
    tmp_path, tool, monkeypatch
):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))
    source = tmp_path / "filler_ecc/output/gcd_filler.def.gz"
    step = load_builder(tool).build_step(workspace, "post_route_lec", source, None)
    assert step.input.def_ == source
    assert step.output.def_ is None  # Still a checker, not a new physical-chain producer.
    module = Mock()

    def save(*, output_dir, thumbnail_path):
        assert Path(output_dir) == step.directory / "output/geometry"
        assert Path(thumbnail_path) == step.output.image
        Path(output_dir).mkdir(parents=True)
        (Path(output_dir) / "geometry.manifest").write_text("saved")
        return True

    module.geometry_snapshot_save.side_effect = save
    monkeypatch.setattr(eda, "_run_step", lambda *_: True)
    assert eda.run_step(workspace, step, module)
    module.def_save.assert_called_once_with(
        def_path=step.directory / "output/gcd_post_route_lec.def.gz"
    )
    module.close.assert_not_called()


def test_no_physical_input_and_export_failure_do_not_change_proof(tmp_path, monkeypatch):
    logger = Mock()
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"), logger=logger)
    builder = load_builder("kepler_formal")
    create = Mock()
    monkeypatch.setattr(lec_layout, "create_db_engine", create)
    step = builder.build_step(workspace, "post_route_lec", None, None)
    assert not lec_layout.save_checked_layout(workspace, step)
    create.assert_not_called()
    step = builder.build_step(workspace, "post_route_lec", tmp_path / "input.def", None)
    create.return_value.geometry_snapshot_save.return_value = False
    assert not lec_layout.save_checked_layout(workspace, step)
    create.return_value.close.assert_called_once()
    logger.warning.assert_called_once()
