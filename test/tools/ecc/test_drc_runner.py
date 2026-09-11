from chipcompiler.data import EccData, EccFeature, EccStep, StepEnum, Workspace
from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.tools.ecc.module import ECCToolsModule, PathArg


class FakeDrcModule(ECCToolsModule):
    def __init__(self):
        self.calls = []

    def update_step_paths(self, output_dir: PathArg, feature_dir: PathArg):
        self.calls.append(
            ("update_step_paths", {"output_dir": output_dir, "feature_dir": feature_dir})
        )

    def init_drc(self, output_dir: PathArg, therad_number: int = 128):
        self.calls.append(("init_drc", {"output_dir": output_dir}))

    def run_drc(self) -> bool:
        self.calls.append(("run_drc", {}))
        return True

    def destroy_drc(self) -> bool:
        self.calls.append(("destroy_drc", {}))
        return True


class FakeSubFlow:
    def __init__(self, **_kwargs):
        pass

    def update_step(self, **_kwargs):
        pass


def test_run_drc_releases_native_resources_before_saving_outputs(tmp_path, monkeypatch):
    data_dir = tmp_path / "drc_ecc" / "data" / "drc"
    step = EccStep(
        name=StepEnum.DRC.value,
        data=EccData(
            dir=tmp_path / "drc_ecc" / "data",
            steps={StepEnum.DRC.value: data_dir},
        ),
        feature=EccFeature(dir=tmp_path / "drc_ecc" / "feature"),
    )
    workspace = Workspace(directory=tmp_path)
    module = FakeDrcModule()
    monkeypatch.setattr(ecc_runner, "EccSubFlow", FakeSubFlow)
    monkeypatch.setattr(
        ecc_runner,
        "save_data",
        lambda **_kwargs: module.calls.append(("save_data", {})) or True,
    )
    monkeypatch.setattr(
        ecc_runner,
        "save_drc_feature",
        lambda _step: module.calls.append(("save_drc_feature", {})) or True,
    )
    monkeypatch.setattr(
        ecc_runner,
        "run_analysis",
        lambda **_kwargs: module.calls.append(("run_analysis", {})),
    )

    assert ecc_runner.run_drc(workspace, step, module) is True
    assert [call[0] for call in module.calls] == [
        "update_step_paths",
        "init_drc",
        "run_drc",
        "destroy_drc",
        "save_data",
        "save_drc_feature",
        "run_analysis",
    ]
    assert module.calls[1] == (
        "init_drc",
        {"output_dir": data_dir},
    )
