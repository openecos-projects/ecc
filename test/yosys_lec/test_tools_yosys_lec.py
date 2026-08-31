#!/usr/bin/env python
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import (
    PDK,
    HomeData,
    OriginDesign,
    OutputPaths,
    Parameters,
    StateEnum,
    StepEnum,
    Workspace,
    YosysLecStep,
    YosysOutput,
    YosysStep,
)
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.utility import json_write

REPO_ROOT = Path(__file__).resolve().parents[2]
GCD_RTL = REPO_ROOT / "test" / "fixtures" / "gcd" / "gcd.v"


def _workspace(tmp_path: Path, *, use_undef: bool = True) -> Workspace:
    lib = tmp_path / "stdcell.lib"
    lib.write_text("library(test) { }\n")
    return Workspace(
        directory=tmp_path / "ws",
        design=OriginDesign(
            name="gcd",
            top_module="gcd",
            origin_verilog=GCD_RTL,
        ),
        pdk=PDK(name="ics55", libs=[lib]),
        parameters=Parameters(
            data={
                "Design": "gcd",
                "Top module": "gcd",
                "Frequency max [MHz]": 100,
                "LEC": {"use_undef": use_undef},
            }
        ),
        home=HomeData(),
    )


def _write_gcd_netlist_pair(gate: Path) -> None:
    gate.parent.mkdir(parents=True, exist_ok=True)
    gcd_text = GCD_RTL.read_text()
    gate.write_text(gcd_text)
    gate.with_name("gcd_Synthesis_golden.v").write_text(gcd_text)


def test_yosys_build_step_exposes_rtl_derived_golden_path(tmp_path):
    from chipcompiler.tools.yosys import builder

    workspace = _workspace(tmp_path)
    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.SYNTHESIS.value,
        input_def=None,
        input_verilog=GCD_RTL,
    )

    assert workspace.design.top_module == "gcd"
    assert step.input.verilog == GCD_RTL
    assert step.output.verilog.name == "gcd_Synthesis.v.gz"
    assert step.output.golden_verilog.name == "gcd_Synthesis_golden.v"


def test_yosys_global_var_tcl_includes_golden_netlist_path(tmp_path):
    from chipcompiler.tools.yosys import builder

    workspace = _workspace(tmp_path)
    workspace.design.input_filelist = None
    workspace.config = {"db": str(tmp_path / "missing_db.json")}
    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.SYNTHESIS.value,
        input_def=None,
        input_verilog=GCD_RTL,
    )

    tcl = builder.generate_global_var_tcl(workspace=workspace, step=step)

    assert "set top_design gcd" in tcl
    assert "set golden_netlist_file" in tcl
    assert str(step.output.golden_verilog.resolve()) in tcl


def test_lec_builder_derives_golden_from_gate_netlist_and_creates_workspace(tmp_path):
    from chipcompiler.tools.yosys_lec import builder

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"

    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.LEC.value,
        input_def=None,
        input_verilog=gate,
    )
    builder.build_step_space(step)

    assert step.tool == "yosys_lec"
    assert step.input.gate_verilog == gate
    assert step.input.golden_verilog == gate.with_name("gcd_Synthesis_golden.v")
    assert step.script.main.name == "run_lec.tcl"
    assert step.output.json.name == "gcd_lec_result.json"
    assert step.script.dir.is_dir()
    assert step.report.dir.is_dir()


def test_lec_builder_accepts_explicit_golden_netlist(tmp_path):
    from chipcompiler.tools.yosys_lec import builder

    workspace = _workspace(tmp_path)
    golden = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    gate = tmp_path / "route_ecc" / "output" / "gcd_route.v"

    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.POST_ROUTE_LEC.value,
        input_def=None,
        input_verilog=gate,
        input_db=golden,
    )

    assert step.input.gate_verilog == gate
    assert step.input.golden_verilog == golden
    assert step.output.json.name == "gcd_postRouteLec_result.json"


def test_lec_build_step_config_writes_models_and_repo_local_script(tmp_path):
    from chipcompiler.tools.yosys_lec import builder

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_gcd_netlist_pair(gate)

    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.LEC.value,
        input_def=None,
        input_verilog=gate,
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace=workspace, step=step)

    config = step.data.config.read_text()
    script = step.script.main.read_text()

    assert str(gate) in config
    assert str(gate.with_name("gcd_Synthesis_golden.v")) in config
    for lib in workspace.pdk.libs:
        assert lib.is_file()
        assert str(lib) in config
    assert "set use_undef true" in config
    assert "splitnets -ports -format __v" in script
    assert "equiv_make" in script
    assert "/home/zhaoxueyan/code/yosys-flow1" not in script


def test_lec_runner_marks_success_from_yosys_status(tmp_path, monkeypatch):
    from chipcompiler.tools.yosys_lec import builder, runner

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_gcd_netlist_pair(gate)

    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.LEC.value,
        input_def=None,
        input_verilog=gate,
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace=workspace, step=step)

    updates = []

    class FakeSubFlow:
        def __init__(self, workspace, workspace_step):
            pass

        def update_step(self, step_name, state, info=None):
            updates.append((step_name, state))

    def fake_run(cmd, cwd, env, stdout, stderr):
        step.report.equiv_status.write_text("Equivalence successfully proven!\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner, "YosysLecSubFlow", FakeSubFlow)
    monkeypatch.setattr(runner, "get_yosys_runtime", lambda: (["yosys"], {"PATH": "/tmp"}))
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.run_step(workspace=workspace, step=step) is True
    assert ("run lec", StateEnum.Success) in updates
    assert step.output.json.exists()


def test_engine_flow_accepts_lec_result_json(tmp_path):
    result_json = tmp_path / "lec_result.json"
    result_json.write_text('{"status": "proven"}\n')
    step = YosysLecStep(name=StepEnum.LEC.value, output=OutputPaths(json=result_json))

    assert EngineFlow(workspace=None).check_step_result(step) is True


def test_post_route_lec_flow_appends_lec_after_route():
    from chipcompiler.rtl2gds import build_post_route_lec_flow

    steps = build_post_route_lec_flow()

    assert steps[-2][0] == StepEnum.ROUTING
    assert steps[-1] == (StepEnum.POST_ROUTE_LEC, "yosys_lec", StateEnum.Unstart)


def test_engine_flow_wires_post_route_lec_against_synthesis_gate(tmp_path, monkeypatch):
    import chipcompiler.tools as tools

    workspace = _workspace(tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    workspace.flow.data = {
        "steps": [
            {"name": StepEnum.SYNTHESIS.value, "tool": "yosys", "state": StateEnum.Unstart.value},
            {"name": StepEnum.ROUTING.value, "tool": "ecc", "state": StateEnum.Unstart.value},
            {
                "name": StepEnum.POST_ROUTE_LEC.value,
                "tool": "yosys_lec",
                "state": StateEnum.Unstart.value,
            },
        ]
    }
    json_write(workspace.flow.path, workspace.flow.data)

    def fake_create_step(
        workspace,
        step,
        eda,
        input_def,
        input_verilog,
        input_db=None,
        **kwargs,
    ):
        if eda == "yosys_lec":
            return YosysLecStep(
                name=step,
                tool=eda,
                input=SimpleNamespace(
                    gate_verilog=input_verilog,
                    golden_verilog=input_db,
                    db=input_db,
                ),
                output=OutputPaths(json=tmp_path / step / "output" / f"gcd_{step}_result.json"),
            )
        if eda == "yosys":
            return YosysStep(
                name=step,
                tool=eda,
                input=SimpleNamespace(def_=input_def, verilog=input_verilog, db=input_db),
                output=YosysOutput(
                    def_=tmp_path / step / "output" / f"gcd_{step}.def.gz",
                    verilog=tmp_path / step / "output" / f"gcd_{step}.v",
                    golden_verilog=tmp_path / step / "output" / f"gcd_{step}_golden.v",
                    db=tmp_path / step / "output" / f"gcd_{step}_db",
                ),
            )
        return SimpleNamespace(
            name=step,
            tool=eda,
            input=SimpleNamespace(def_=input_def, verilog=input_verilog, db=input_db),
            output=SimpleNamespace(
                def_=tmp_path / step / "output" / f"gcd_{step}.def.gz",
                verilog=tmp_path / step / "output" / f"gcd_{step}.v",
                db=tmp_path / step / "output" / f"gcd_{step}_db",
            ),
        )

    monkeypatch.setattr(tools, "create_step", fake_create_step)

    engine_flow = EngineFlow(workspace=workspace)
    engine_flow.create_step_workspaces()

    synth_step, route_step, lec_step = engine_flow.workspace_steps
    assert synth_step.name == StepEnum.SYNTHESIS.value
    assert route_step.name == StepEnum.ROUTING.value
    assert lec_step.name == StepEnum.POST_ROUTE_LEC.value
    assert lec_step.input.gate_verilog == route_step.output.verilog
    assert lec_step.input.golden_verilog == synth_step.output.verilog
