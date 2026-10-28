import logging
from pathlib import Path

from chipcompiler.data import EccStep, StepEnum, Workspace
from chipcompiler.tools.ecc import defview as defview_runner


class FakeModule:
    def __init__(self, *, snapshot_ok=True):
        self.snapshot_ok = snapshot_ok
        self.calls = []

    def def_save(self, def_path):
        self.calls.append(("def_save", def_path))

    def geometry_snapshot_save(self, output_dir, thumbnail_path=None):
        self.calls.append(("geometry_snapshot_save", output_dir, thumbnail_path))
        if self.snapshot_ok:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / "geometry.manifest").write_text("schema_version=1\n")
        return self.snapshot_ok


def _workspace_and_step(tmp_path):
    geometry_dir = tmp_path / "defview_ecc" / "output" / "geometry"
    step = EccStep(name=StepEnum.DEFVIEW.value)
    step.output.geometry = geometry_dir
    step.output.geometry_manifest = geometry_dir / "geometry.manifest"
    step.output.def_ = tmp_path / "defview_ecc" / "output" / "design.def"
    step.output.image = tmp_path / "defview_ecc" / "output" / "design.png"
    workspace = Workspace(directory=tmp_path)
    workspace.logger = logging.getLogger("test-defview")
    return workspace, step


def test_run_defview_saves_def_and_geometry_snapshot(tmp_path, monkeypatch):
    workspace, step = _workspace_and_step(tmp_path)
    module = FakeModule()
    monkeypatch.setattr(defview_runner, "get_eda_instance", lambda **_kwargs: module)

    assert defview_runner.run_defview(workspace, step, None) is True
    assert [call[0] for call in module.calls] == ["def_save", "geometry_snapshot_save"]
    assert step.output.geometry_manifest.is_file()


def test_run_defview_fails_without_design_inputs(tmp_path, monkeypatch):
    workspace, step = _workspace_and_step(tmp_path)
    monkeypatch.setattr(defview_runner, "get_eda_instance", lambda **_kwargs: None)

    assert defview_runner.run_defview(workspace, step, None) is False


def test_run_defview_fails_when_manifest_is_missing(tmp_path, monkeypatch):
    workspace, step = _workspace_and_step(tmp_path)
    monkeypatch.setattr(
        defview_runner,
        "get_eda_instance",
        lambda **_kwargs: FakeModule(snapshot_ok=False),
    )

    assert defview_runner.run_defview(workspace, step, None) is False
