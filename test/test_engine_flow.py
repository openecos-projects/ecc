from chipcompiler.data import EccOutput, EccStep, StepEnum, Workspace, YosysOutput, YosysStep
from chipcompiler.engine.flow import EngineFlow


def test_engine_flow_missing_path_is_not_initialized():
    engine_flow = EngineFlow(Workspace())

    assert engine_flow.has_init() is False


def test_check_step_result_synthesis_uses_common_verilog(tmp_path):
    verilog = tmp_path / "gcd.v"
    verilog.write_text("module gcd; endmodule\n")
    step = YosysStep(name=StepEnum.SYNTHESIS.value, output=YosysOutput(verilog=verilog))
    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_check_step_result_harden_reads_ecc_only_lef_lib(tmp_path):
    lef = tmp_path / "gcd.lef"
    lib = tmp_path / "gcd.lib"
    lef.write_text("")
    lib.write_text("")
    step = EccStep(name=StepEnum.HARDEN.value, output=EccOutput(lef=lef, lib=lib))
    assert EngineFlow(Workspace()).check_step_result(step) is True
    # missing lib -> not success
    step_missing = EccStep(
        name=StepEnum.HARDEN.value,
        output=EccOutput(lef=lef, lib=tmp_path / "missing.lib"),
    )
    assert EngineFlow(Workspace()).check_step_result(step_missing) is False


def test_check_step_result_default_requires_def_verilog_gds(tmp_path):
    for name in ("gcd.def", "gcd.v", "gcd.gds"):
        (tmp_path / name).write_text("")
    step = EccStep(
        name=StepEnum.PLACEMENT.value,
        output=EccOutput(
            def_=tmp_path / "gcd.def",
            verilog=tmp_path / "gcd.v",
            gds=tmp_path / "gcd.gds",
        ),
    )
    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_check_step_result_timing_opt_does_not_require_gds(tmp_path):
    (tmp_path / "gcd.def").write_text("")
    (tmp_path / "gcd.v").write_text("")
    step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        output=EccOutput(def_=tmp_path / "gcd.def", verilog=tmp_path / "gcd.v"),
    )
    # gds intentionally absent; timing-opt result must still succeed.
    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_rcx_to_sta_spef_transfer(monkeypatch, tmp_path):
    # create_step_workspaces copies the RCX step's spef list onto the following
    # STA step. Drive it with a stubbed create_step returning prebuilt variants.
    import chipcompiler.tools as tools_api
    from chipcompiler.data import OriginDesign

    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )

    spef_paths = [tmp_path / "gcd_c.spef", tmp_path / "gcd_r.spef"]
    prebuilt = {
        StepEnum.RCX.value: EccStep(
            name=StepEnum.RCX.value, tool="ecc", output=EccOutput(spef=list(spef_paths))
        ),
        StepEnum.STA.value: EccStep(name=StepEnum.STA.value, tool="ecc"),
    }

    def fake_create_step(workspace, step, eda, **kwargs):
        return prebuilt[step]

    monkeypatch.setattr(tools_api, "create_step", fake_create_step)

    flow = EngineFlow(workspace)
    # load() leaves flow.data empty (no flow.path); set the steps for this test.
    flow.workspace.flow.data = {
        "steps": [
            {"name": StepEnum.RCX.value, "tool": "ecc"},
            {"name": StepEnum.STA.value, "tool": "ecc"},
        ]
    }
    flow.create_step_workspaces()

    sta_step = flow.get_workspace_step(StepEnum.STA.value)
    assert isinstance(sta_step, EccStep)
    assert sta_step.output.spef == spef_paths  # transferred from the RCX predecessor
