#!/usr/bin/env python
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import (
    PDK,
    HomeData,
    KeplerFormalStep,
    OriginDesign,
    OutputPaths,
    Parameters,
    StateEnum,
    StepEnum,
    Workspace,
    YosysOutput,
    YosysStep,
)
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.tools.kepler_formal.netlist_prep import (
    physical_cell_names,
    prepare_netlist,
)
from chipcompiler.utility import json_write

REPO_ROOT = Path(__file__).resolve().parents[3]
GCD_RTL = REPO_ROOT / "test" / "fixtures" / "gcd" / "gcd.v"


def _workspace(tmp_path: Path) -> Workspace:
    lib = tmp_path / "stdcell.lib"
    lib.write_text("library(test) { }\n")
    return Workspace(
        directory=tmp_path / "ws",
        design=OriginDesign(
            name="gcd",
            top_module="gcd",
            origin_verilog=GCD_RTL,
        ),
        pdk=PDK(
            name="ics55",
            libs=[lib],
            tap_cell="FILLTAPH7R",
            fillers=["FILLER4H7R", "FILLER8H7R"],
        ),
        parameters=Parameters(data={"design": "gcd", "top_module": "gcd"}),
        home=HomeData(),
    )


def _write_netlist_pair(gate: Path, *, compressed: bool = False) -> tuple[Path, Path]:
    gate.parent.mkdir(parents=True, exist_ok=True)
    gcd_text = GCD_RTL.read_text()
    golden = gate.with_name("gcd_Synthesis_golden.v")
    if compressed:
        gzip_gate = gate.with_name(f"{gate.stem}.v.gz")
        gzip_gate.write_bytes(gzip.compress(gcd_text.encode()))
        golden.write_text(gcd_text)
        return golden, gzip_gate
    gate.write_text(gcd_text)
    golden.write_text(gcd_text)
    return golden, gate


def test_kepler_formal_build_step_derives_golden_and_creates_workspace(tmp_path):
    from chipcompiler.tools.kepler_formal import builder

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"

    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.LEC.value,
        input_def=None,
        input_verilog=gate,
    )
    builder.build_step_space(step)

    assert step.tool == "kepler_formal"
    assert step.input.gate_verilog == gate
    assert step.input.golden_verilog == gate.with_name("gcd_Synthesis_golden.v")
    assert step.data.config.name == "lec_config.yaml"
    assert step.output.json.name == "gcd_lec_result.json"
    assert step.directory.name == "lec_kepler_formal"
    assert step.report.dir.is_dir()
    assert step.data.dir.is_dir()


def test_kepler_formal_build_step_config_writes_yaml(tmp_path):
    from chipcompiler.tools.kepler_formal import builder

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_netlist_pair(gate)

    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.LEC.value,
        input_def=None,
        input_verilog=gate,
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace=workspace, step=step)

    config = step.data.config.read_text()
    assert "verification: lec" in config
    assert "format: verilog" in config
    assert str(gate.with_name("gcd_Synthesis_golden.v")) in config
    assert str(gate) in config
    assert str(workspace.pdk.libs[0]) in config
    assert str(step.report.miter_log) in config


def test_kepler_formal_runner_marks_success_from_proven_marker(tmp_path, monkeypatch):
    from chipcompiler.tools.kepler_formal import builder, runner

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    golden, gate_gz = _write_netlist_pair(gate, compressed=True)

    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.LEC.value,
        input_def=None,
        input_verilog=gate_gz,
        input_db=golden,
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace=workspace, step=step)

    updates = []

    class FakeSubFlow:
        def __init__(self, workspace, workspace_step):
            pass

        def update_step(self, step_name, state, info=None):
            updates.append((step_name, state))

    recorded = {}

    def fake_run(cmd, cwd, env, stdout, stderr):
        recorded["cmd"] = cmd
        recorded["env"] = env
        stdout.write("kepler-formal run\nNo difference was found.\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner, "KeplerFormalSubFlow", FakeSubFlow)
    monkeypatch.setattr(runner, "get_kepler_formal_runtime", lambda: (["kepler-formal"], {"PATH": "/tmp"}))
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.run_step(workspace=workspace, step=step) is True
    assert ("run lec", StateEnum.Success) in updates
    assert ("analysis", StateEnum.Success) in updates
    payload = json.loads(step.output.json.read_text())
    assert payload["status"] == "proven"
    assert payload["gate_verilog"] == str(gate_gz)
    assert payload["golden_sha256"]
    assert payload["gate_sha256"]
    # The subprocess environment must not inherit sidecar loader overrides.
    assert "LD_LIBRARY_PATH" not in recorded["env"]
    assert "LD_PRELOAD" not in recorded["env"]
    assert recorded["cmd"] == ["kepler-formal", "--config", str(step.data.config)]
    # The runner regenerates the YAML for the prepared compare netlists: the
    # gzipped gate is decompressed into a compare copy, while the plain,
    # filler-free golden passes through untouched.
    config_text = step.data.config.read_text()
    assert "gate_compare.v" in config_text
    assert str(step.input.golden_verilog) in config_text
    assert Path(step.data.dir, "gate_compare.v").is_file()
    assert EngineFlow(workspace=None).check_step_result(step) is True


def test_kepler_formal_runner_writes_incomplete_on_difference(tmp_path, monkeypatch):
    from chipcompiler.tools.kepler_formal import builder, runner

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_netlist_pair(gate)
    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.LEC.value,
        input_def=None,
        input_verilog=gate,
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace=workspace, step=step)

    class FakeSubFlow:
        def __init__(self, workspace, workspace_step):
            pass

        def update_step(self, step_name, state, info=None):
            return None

    def fake_run(cmd, cwd, env, stdout, stderr):
        stdout.write("Difference was found. Please refer to the log for details.\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner, "KeplerFormalSubFlow", FakeSubFlow)
    monkeypatch.setattr(runner, "get_kepler_formal_runtime", lambda: (["kepler-formal"], {"PATH": "/tmp"}))
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    # kepler-formal exits 0 even for a definitive mismatch; only the stdout
    # evidence decides, so this must be a failed proof.
    assert runner.run_step(workspace=workspace, step=step) is False
    payload = json.loads(step.output.json.read_text())
    assert payload["status"] == "incomplete"
    assert "found a difference" in step.report.status.read_text()
    assert EngineFlow(workspace=None).check_step_result(step) is False


def test_kepler_formal_runner_writes_incomplete_on_error_or_missing_tool(tmp_path, monkeypatch):
    from chipcompiler.tools.kepler_formal import builder, runner

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_netlist_pair(gate)
    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.LEC.value,
        input_def=None,
        input_verilog=gate,
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace=workspace, step=step)

    class FakeSubFlow:
        def __init__(self, workspace, workspace_step):
            pass

        def update_step(self, step_name, state, info=None):
            return None

    def raising_run(cmd, cwd, env, stdout, stderr):
        raise OSError("kepler-formal exec format error")

    monkeypatch.setattr(runner, "KeplerFormalSubFlow", FakeSubFlow)
    monkeypatch.setattr(runner, "get_kepler_formal_runtime", lambda: (["kepler-formal"], {"PATH": "/tmp"}))
    monkeypatch.setattr(runner.subprocess, "run", raising_run)

    assert runner.run_step(workspace=workspace, step=step) is False
    payload = json.loads(step.output.json.read_text())
    assert payload["status"] == "incomplete"

    monkeypatch.setattr(runner, "get_kepler_formal_runtime", lambda: ([], {}))
    assert runner.run_step(workspace=workspace, step=step) is False
    assert "kepler-formal is not available" in Path(step.log.file).read_text()


def test_prepare_netlist_strips_physical_cells_and_decompresses(tmp_path):
    netlist = tmp_path / "lvs.v"
    netlist.write_text(
        "module gcd (clk);\n"
        "  input clk;\n"
        "  FILLTAPH7R BNDRY_CAP_1 (  );\n"
        "  FILLER4H7R FILLER4H7R_0 (  );\n"
        "  FILLCAP16H7L DCAP_1 (  );\n"
        "endmodule\n"
    )
    physical = physical_cell_names(
        SimpleNamespace(fillers=["FILLER4H7R"], tap_cell="FILLTAPH7R", end_cap=None)
    )
    target = tmp_path / "gate_compare.v"

    prepared = prepare_netlist(netlist, target, physical)

    assert prepared == target
    text = target.read_text()
    assert "FILL" not in text
    assert "module gcd" in text

    # A netlist without physical cells is passed through untouched.
    clean = tmp_path / "syn.v"
    clean.write_text("module gcd (clk);\n  input clk;\nendmodule\n")
    assert prepare_netlist(clean, tmp_path / "unused.v", physical) == clean

    # gzip inputs are decompressed into the compare copy.
    gz = tmp_path / "syn.v.gz"
    gz.write_bytes(gzip.compress(b"module gcd (clk);\n  input clk;\nendmodule\n"))
    prepared_gz = prepare_netlist(gz, tmp_path / "golden_compare.v", physical)
    assert prepared_gz == tmp_path / "golden_compare.v"
    assert "module gcd" in prepared_gz.read_text()


def test_engine_flow_wires_kepler_lec_and_skips_pre_step_advance(tmp_path, monkeypatch):
    import chipcompiler.tools as tools

    workspace = _workspace(tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    workspace.flow.data = {
        "steps": [
            {"name": StepEnum.SYNTHESIS.value, "tool": "yosys", "state": StateEnum.Unstart.value},
            {"name": StepEnum.LEC.value, "tool": "kepler_formal", "state": StateEnum.Unstart.value},
            {"name": StepEnum.FLOORPLAN.value, "tool": "ecc", "state": StateEnum.Unstart.value},
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
        if eda == "yosys":
            return YosysStep(
                name=step,
                tool=eda,
                input=SimpleNamespace(def_=input_def, verilog=input_verilog, db=input_db),
                output=YosysOutput(
                    verilog=tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v.gz",
                    golden_verilog=(
                        tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis_golden.v"
                    ),
                    db=tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis_db",
                ),
            )
        if eda == "kepler_formal":
            return KeplerFormalStep(
                name=step,
                tool=eda,
                input=SimpleNamespace(gate_verilog=input_verilog, golden_verilog=input_db),
                output=OutputPaths(
                    json=tmp_path / "lec_kepler_formal" / "output" / "gcd_lec_result.json"
                ),
            )
        return SimpleNamespace(
            name=step,
            tool=eda,
            input=SimpleNamespace(def_=input_def, verilog=input_verilog, db=input_db),
            output=SimpleNamespace(
                def_=tmp_path / "Floorplan_ecc" / "output" / "gcd.def",
                verilog=tmp_path / "Floorplan_ecc" / "output" / "gcd.v",
                db=tmp_path / "Floorplan_ecc" / "output" / "gcd_db",
            ),
        )

    monkeypatch.setattr(tools, "create_step", fake_create_step)

    engine_flow = EngineFlow(workspace=workspace)
    engine_flow.create_step_workspaces()

    synth_step, lec_step, floorplan_step = engine_flow.workspace_steps
    assert lec_step.input.gate_verilog == synth_step.output.verilog
    assert lec_step.input.golden_verilog == synth_step.output.golden_verilog
    # The LEC step must not advance the physical input chain.
    assert floorplan_step.input.verilog == synth_step.output.verilog


def test_engine_flow_wires_kepler_post_route_lec_against_synthesis_gate(tmp_path, monkeypatch):
    import chipcompiler.tools as tools

    workspace = _workspace(tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    workspace.flow.data = {
        "steps": [
            {"name": StepEnum.SYNTHESIS.value, "tool": "yosys", "state": StateEnum.Unstart.value},
            {"name": StepEnum.LVS.value, "tool": "ecc", "state": StateEnum.Unstart.value},
            {
                "name": StepEnum.POST_ROUTE_LEC.value,
                "tool": "kepler_formal",
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
        if eda == "kepler_formal":
            return KeplerFormalStep(
                name=step,
                tool=eda,
                input=SimpleNamespace(gate_verilog=input_verilog, golden_verilog=input_db),
                output=OutputPaths(json=tmp_path / step / "output" / f"gcd_{step}_result.json"),
            )
        if eda == "yosys":
            return YosysStep(
                name=step,
                tool=eda,
                input=SimpleNamespace(def_=input_def, verilog=input_verilog, db=input_db),
                output=YosysOutput(
                    verilog=tmp_path / step / "output" / f"gcd_{step}.v.gz",
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
                verilog=tmp_path / step / "output" / f"gcd_{step}.v.gz",
                db=tmp_path / step / "output" / f"gcd_{step}_db",
            ),
        )

    monkeypatch.setattr(tools, "create_step", fake_create_step)

    engine_flow = EngineFlow(workspace=workspace)
    engine_flow.create_step_workspaces()

    synth_step, lvs_step, lec_step = engine_flow.workspace_steps
    assert lec_step.input.gate_verilog == lvs_step.output.verilog
    assert lec_step.input.golden_verilog == synth_step.output.verilog


def test_step_directory_helpers_resolve_both_lec_engines():
    from chipcompiler.data.step_dirs import (
        LEGACY_STEP_DIRECTORIES,
        STEP_DIRECTORIES,
        all_step_directories,
        step_directory_for_tool,
    )

    assert step_directory_for_tool("lec", "kepler_formal") == "lec_kepler_formal"
    assert step_directory_for_tool("lec", "yosys_lec") == "lec_yosys_lec"
    assert step_directory_for_tool("postRouteLec", None) == STEP_DIRECTORIES["postRouteLec"]
    assert LEGACY_STEP_DIRECTORIES["lec"] in all_step_directories()
    assert STEP_DIRECTORIES["lec"] in all_step_directories()


def test_reconcile_treats_lec_engines_as_interchangeable():
    from chipcompiler.engine.reconcile import compare_flows, _normalized_entries

    persisted = [("Synthesis", "yosys"), ("lec", "yosys_lec"), ("Floorplan", "ecc")]
    target = [("Synthesis", "yosys"), ("lec", "kepler_formal"), ("Floorplan", "ecc")]

    assert compare_flows(_normalized_entries(persisted), _normalized_entries(target)) == "equal"

    prefix = [("Synthesis", "yosys")]
    assert (
        compare_flows(_normalized_entries(prefix), _normalized_entries(target)) == "proper_prefix"
    )
