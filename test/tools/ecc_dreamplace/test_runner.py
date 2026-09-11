from chipcompiler.data import EccStep, StateEnum, StepEnum, Workspace
from chipcompiler.tools.ecc_dreamplace import runner as dreamplace_runner


class FakeSubFlow:
    def __init__(self, **_kwargs):
        self.updates = []

    def update_step(self, **kwargs):
        self.updates.append(kwargs)


def test_macro_placement_step_runs_and_saves_outputs(monkeypatch, tmp_path):
    calls = []
    subflow = FakeSubFlow()

    class FakeDreamplaceModule:
        def __init__(self, **kwargs):
            assert kwargs["step"].name == StepEnum.MACRO_PLACEMENT.value
            calls.append("init")

        def run_macro_placement(self):
            calls.append("run")
            return True

    class FakeEccModule:
        def tcl_save(self, output_path):
            calls.append(("tcl_save", output_path))
            return True

    macro_location = tmp_path / "macro_localtion.tcl"
    module = FakeEccModule()
    step = EccStep(name=StepEnum.MACRO_PLACEMENT.value)

    monkeypatch.setattr(dreamplace_runner, "EccSubFlow", lambda **_kwargs: subflow)
    monkeypatch.setattr(
        dreamplace_runner.ecc_runner,
        "get_eda_instance",
        lambda **_kwargs: module,
    )
    monkeypatch.setattr(
        dreamplace_runner.ecc_runner,
        "save_data",
        lambda **kwargs: calls.append(("save", kwargs["step"].name)) or True,
    )
    monkeypatch.setattr(dreamplace_runner, "DreamplaceModule", FakeDreamplaceModule)

    assert (
        dreamplace_runner.run_macro_placement(
            Workspace(config={"macro_location": macro_location}), step
        )
        is True
    )
    assert calls == [
        "init",
        "run",
        ("tcl_save", macro_location),
        ("save", StepEnum.MACRO_PLACEMENT.value),
    ]
    assert [update["step_name"] for update in subflow.updates] == [
        "load data",
        "macro placement",
        "save data",
    ]
    assert subflow.updates[1]["state"] is StateEnum.Success


def test_macro_placement_stops_when_tcl_handoff_fails(monkeypatch, tmp_path):
    calls = []
    subflow = FakeSubFlow()

    class FakeDreamplaceModule:
        def __init__(self, **_kwargs):
            pass

        def run_macro_placement(self):
            calls.append("run")
            return True

    class FakeEccModule:
        def tcl_save(self, output_path):
            calls.append(("tcl_save", output_path))
            return False

    macro_location = tmp_path / "macro_localtion.tcl"
    step = EccStep(name=StepEnum.MACRO_PLACEMENT.value)

    monkeypatch.setattr(dreamplace_runner, "EccSubFlow", lambda **_kwargs: subflow)
    monkeypatch.setattr(
        dreamplace_runner.ecc_runner,
        "get_eda_instance",
        lambda **_kwargs: FakeEccModule(),
    )
    monkeypatch.setattr(
        dreamplace_runner.ecc_runner,
        "save_data",
        lambda **_kwargs: calls.append("save") or True,
    )
    monkeypatch.setattr(dreamplace_runner, "DreamplaceModule", FakeDreamplaceModule)

    assert (
        dreamplace_runner.run_macro_placement(
            Workspace(config={"macro_location": macro_location}), step
        )
        is False
    )
    assert calls == ["run", ("tcl_save", macro_location)]
    assert [update["step_name"] for update in subflow.updates] == ["load data", "macro placement"]
    assert subflow.updates[-1]["state"] is StateEnum.Imcomplete


def test_run_step_dispatches_macro_placement(monkeypatch):
    monkeypatch.setattr(dreamplace_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(dreamplace_runner, "run_macro_placement", lambda **_kwargs: True)

    assert (
        dreamplace_runner.run_step(Workspace(), EccStep(name=StepEnum.MACRO_PLACEMENT.value))
        is True
    )
