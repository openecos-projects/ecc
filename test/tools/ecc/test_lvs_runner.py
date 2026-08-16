from pathlib import Path

from chipcompiler.data import (
    EccData,
    EccFeature,
    EccStep,
    OriginDesign,
    StepEnum,
    StepInput,
    Workspace,
)
from chipcompiler.tools.ecc import runner as ecc_runner


class FakeLvsModule:
    def __init__(self, *, netlist_loaded=True):
        self.netlist_loaded = netlist_loaded
        self.calls = []

    def read_lvs_verilog(self, path, top_module):
        self.calls.append(("read_lvs_verilog", path, top_module))
        return self.netlist_loaded

    def update_step_paths(self, **kwargs):
        self.calls.append(("update_step_paths", kwargs))

    def init_lvs(self, **kwargs):
        self.calls.append(("init_lvs", kwargs))

    def run_lvs(self):
        self.calls.append(("run_lvs", {}))

    def destroy_lvs(self):
        self.calls.append(("destroy_lvs", {}))


class FakeLogger:
    def __init__(self):
        self.errors = []

    def error(self, message, *args):
        self.errors.append((message, args))


class FakeSubFlow:
    def __init__(self, **_kwargs):
        pass

    def update_step(self, **_kwargs):
        pass


def _lvs_step(tmp_path: Path, design_verilog: Path) -> EccStep:
    return EccStep(
        name=StepEnum.LVS.value,
        input=StepInput(verilog=design_verilog),
        data=EccData(dir=tmp_path / "lvs" / "data", steps={StepEnum.LVS.value: tmp_path / "lvs"}),
        feature=EccFeature(dir=tmp_path / "lvs" / "feature"),
    )


def test_run_lvs_loads_netlist_into_reused_engine(tmp_path, monkeypatch):
    design_verilog = tmp_path / "drc" / "gcd.v.gz"
    design_verilog.parent.mkdir(parents=True)
    design_verilog.write_bytes(b"gzip netlist")
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    module = FakeLvsModule()
    monkeypatch.setattr(ecc_runner, "EccSubFlow", FakeSubFlow)
    monkeypatch.setattr(ecc_runner, "save_data", lambda **_kwargs: True)
    monkeypatch.setattr(ecc_runner, "copy_lvs_outputs", lambda **_kwargs: None)
    monkeypatch.setattr(ecc_runner, "run_analysis", lambda **_kwargs: None)

    assert ecc_runner.run_lvs(workspace, _lvs_step(tmp_path, design_verilog), module) is True
    assert [call[0] for call in module.calls] == [
        "update_step_paths",
        "read_lvs_verilog",
        "init_lvs",
        "run_lvs",
        "destroy_lvs",
    ]
    assert module.calls[1] == ("read_lvs_verilog", str(design_verilog), "gcd")


def test_run_lvs_stops_before_native_init_when_netlist_load_fails(tmp_path, monkeypatch):
    design_verilog = tmp_path / "drc" / "gcd.v.gz"
    design_verilog.parent.mkdir(parents=True)
    design_verilog.write_bytes(b"gzip netlist")
    logger = FakeLogger()
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        logger=logger,
    )
    module = FakeLvsModule(netlist_loaded=False)
    monkeypatch.setattr(ecc_runner, "EccSubFlow", FakeSubFlow)

    assert ecc_runner.run_lvs(workspace, _lvs_step(tmp_path, design_verilog), module) is False
    assert [call[0] for call in module.calls] == ["update_step_paths", "read_lvs_verilog"]
    assert module.calls[1] == ("read_lvs_verilog", str(design_verilog), "gcd")
    assert logger.errors == [("Failed to load LVS netlist: %s", (str(design_verilog),))]
