#!/usr/bin/env python
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.data import (
    PDK,
    KeplerFormalStep,
    OriginDesign,
    OutputPaths,
    Parameters,
    SkippableStepEnum,
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
from test.flow_fixture import step_fields

REPO_ROOT = Path(__file__).resolve().parents[3]
GCD_RTL = REPO_ROOT / "test" / "fixtures" / "gcd" / "gcd.v"


def _kepler_step(*args: Any, **kwargs: Any) -> Any:
    return KeplerFormalStep(*args, **kwargs)


def _yosys_step(*args: Any, **kwargs: Any) -> Any:
    return YosysStep(*args, **kwargs)


def _engine_flow(workspace: Any = None) -> Any:
    return EngineFlow(workspace=workspace)


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

    step: Any = builder.build_step(
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

    step: Any = builder.build_step(
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


@pytest.mark.parametrize(
    ("name", "filelist", "defines"),
    [
        # Synthesis reads a .v file or a plain-Verilog filelist with the native
        # read_verilog, which defines YOSYS too, anything else with read_slang.
        ("", None, "+define+SYNTHESIS\n+define+YOSYS\n"),
        ("design.f", f"{GCD_RTL}\n", "+define+SYNTHESIS\n+define+YOSYS\n"),
        ("design.f", f"+incdir+.\n{GCD_RTL}\n", "+define+SYNTHESIS\n"),
        # The filelist generated for several RTL entries has no suffix.
        ("filelist", f"+incdir+.\n{GCD_RTL}\n", "+define+SYNTHESIS\n"),
    ],
    ids=["rtl file", "plain filelist", "slang filelist", "suffixless filelist"],
)
def test_the_synthesis_lec_config_checks_the_rtl_against_the_netlist_with_sec(
    tmp_path, name, filelist, defines
):
    import yaml

    from chipcompiler.tools.kepler_formal import builder

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_netlist_pair(gate)
    rtl = GCD_RTL
    if filelist is not None:
        rtl = tmp_path / name
        rtl.write_text(filelist)
        workspace.design.input_filelist = rtl
    step: Any = builder.build_step(
        workspace=workspace,
        step_name="lec@Synthesis",
        input_def=None,
        input_verilog=gate,
        input_db=rtl,
    )
    builder.build_step_space(step)

    builder.write_step_config(workspace, step)

    rtl_filelist = step.data.dir / "rtl.f"
    assert yaml.safe_load(step.data.config.read_text()) == {
        "format": "sv2v",
        "verification": "sec",
        "input_paths": [[], [str(gate)]],
        "sv_design1_flist": str(rtl_filelist),
        "sv_design1_top": "gcd",
        "verilog_design2_top": "gcd",
        "liberty_files": [str(workspace.pdk.libs[0])],
        "log_file": str(step.report.miter_log),
    }
    # A filelist nests with -F so its entries resolve against its own directory.
    entry = f'"{rtl}"' if filelist is None else f'-F "{rtl}"'
    assert rtl_filelist.read_text() == f"{defines}{entry}\n"


@pytest.mark.parametrize(
    ("stdout", "returncode", "proven", "status"),
    [
        (
            "No binary-defined difference was found. SEC proved equivalence under the "
            "dual-rail steady-state abstraction at k = 9.\n",
            0,
            True,
            "completed with proven equivalence.",
        ),
        (
            "Difference was found. SEC found a counterexample at k = 2.\n",
            3,
            False,
            "did not prove equivalence: kepler-formal found a difference; "
            "see the miter log for details",
        ),
        # Conflicting verdicts fail: a difference outranks a proof marker.
        (
            "No difference was found.\nDifference was found. SEC found a counterexample.\n",
            0,
            False,
            "did not prove equivalence: kepler-formal found a difference; "
            "see the miter log for details",
        ),
    ],
)
def test_the_synthesis_lec_reads_the_sec_verdict(
    tmp_path, monkeypatch, stdout, returncode, proven, status
):
    from chipcompiler.tools.kepler_formal import builder, runner

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_netlist_pair(gate)
    step: Any = builder.build_step(
        workspace=workspace,
        step_name="lec@Synthesis",
        input_def=None,
        input_verilog=gate,
        input_db=GCD_RTL,
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace=workspace, step=step)

    def fake_run(cmd, cwd, env, stdout, stderr, _text=stdout):
        stdout.write(_text)
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(
        runner,
        "KeplerFormalSubFlow",
        lambda workspace, workspace_step: SimpleNamespace(update_step=lambda **_kw: None),
    )
    monkeypatch.setattr(
        runner, "get_kepler_formal_runtime", lambda: (["kepler-formal"], {"PATH": "/tmp"})
    )
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.run_step(workspace=workspace, step=step) is proven
    # The RTL is read as is: no prepared compare copy of the golden.
    assert (
        step.report.status.read_text(),
        Path(step.data.dir, "golden_compare.v").exists(),
    ) == (f"kepler-formal SEC of the RTL and the netlist {status}\n", False)


def test_kepler_formal_runner_marks_success_from_proven_marker(tmp_path, monkeypatch):
    from chipcompiler.tools.kepler_formal import builder, runner

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    golden, gate_gz = _write_netlist_pair(gate, compressed=True)

    step: Any = builder.build_step(
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
    monkeypatch.setattr(
        runner, "get_kepler_formal_runtime", lambda: (["kepler-formal"], {"PATH": "/tmp"})
    )
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
    assert _engine_flow(workspace=None).check_step_result(step) is True


def test_kepler_formal_runner_writes_incomplete_on_difference(tmp_path, monkeypatch):
    from chipcompiler.tools.kepler_formal import builder, runner

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_netlist_pair(gate)
    step: Any = builder.build_step(
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
    monkeypatch.setattr(
        runner, "get_kepler_formal_runtime", lambda: (["kepler-formal"], {"PATH": "/tmp"})
    )
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    # kepler-formal exits 0 even for a definitive mismatch; only the stdout
    # evidence decides, so this must be a failed proof.
    assert runner.run_step(workspace=workspace, step=step) is False
    payload = json.loads(step.output.json.read_text())
    assert payload["status"] == "incomplete"
    assert "found a difference" in step.report.status.read_text()
    assert _engine_flow(workspace=None).check_step_result(step) is False


def test_kepler_formal_runner_writes_incomplete_on_error_or_missing_tool(tmp_path, monkeypatch):
    from chipcompiler.tools.kepler_formal import builder, runner

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_netlist_pair(gate)
    step: Any = builder.build_step(
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
    monkeypatch.setattr(
        runner, "get_kepler_formal_runtime", lambda: (["kepler-formal"], {"PATH": "/tmp"})
    )
    monkeypatch.setattr(runner.subprocess, "run", raising_run)

    assert runner.run_step(workspace=workspace, step=step) is False
    payload = json.loads(step.output.json.read_text())
    assert payload["status"] == "incomplete"

    monkeypatch.setattr(runner, "get_kepler_formal_runtime", lambda: ([], {}))
    assert runner.run_step(workspace=workspace, step=step) is False
    assert "kepler-formal is not available" in Path(step.log.file).read_text()


def test_the_synthesis_lec_fails_when_the_files_its_rtl_reads_cannot_be_identified(
    tmp_path, monkeypatch
):
    from chipcompiler.tools.kepler_formal import builder, runner

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_netlist_pair(gate)
    rtl = tmp_path / "design.f"
    # -f resolves against the reading tool's working directory.
    rtl.write_text(f"-f {tmp_path / 'other.f'}\n")
    workspace.design.input_filelist = rtl
    step: Any = builder.build_step(
        workspace=workspace,
        step_name="lec@Synthesis",
        input_def=None,
        input_verilog=gate,
        input_db=rtl,
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace=workspace, step=step)

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("kepler-formal must not run")

    monkeypatch.setattr(
        runner,
        "KeplerFormalSubFlow",
        lambda workspace, workspace_step: SimpleNamespace(update_step=lambda **_kw: None),
    )
    monkeypatch.setattr(
        runner, "get_kepler_formal_runtime", lambda: (["kepler-formal"], {"PATH": "/tmp"})
    )
    monkeypatch.setattr(runner.subprocess, "run", unexpected_run)

    assert runner.run_step(workspace=workspace, step=step) is False
    assert (
        json.loads(step.output.json.read_text())["status"],
        step.report.status.read_text(),
    ) == (
        "incomplete",
        "kepler-formal SEC of the RTL and the netlist did not prove equivalence: cannot "
        f"identify the files the RTL reads: {rtl}:1: unsupported filelist option '-f'\n",
    )


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


@pytest.mark.parametrize("filelist", [False, True], ids=["rtl file", "filelist"])
def test_engine_flow_wires_kepler_lec_and_skips_pre_step_advance(tmp_path, monkeypatch, filelist):
    import chipcompiler.tools as tools

    workspace = _workspace(tmp_path)
    if filelist:
        filelist_path = tmp_path / "design.f"
        filelist_path.write_text(f"{GCD_RTL}\n")
        workspace.design.input_filelist = filelist_path
    workspace.flow.path = tmp_path / "flow.json"
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": StepEnum.SYNTHESIS.value,
                "tool": "yosys",
                "state": StateEnum.Unstart.value,
                **step_fields(StepEnum.SYNTHESIS.value, "yosys"),
            },
            {
                "name": "lec@Synthesis",
                "tool": "kepler_formal",
                "state": StateEnum.Unstart.value,
                **step_fields("lec@Synthesis", "kepler_formal"),
            },
            {
                "name": StepEnum.FLOORPLAN.value,
                "tool": "ecc",
                "state": StateEnum.Unstart.value,
                **step_fields(StepEnum.FLOORPLAN.value, "ecc"),
            },
        ],
    }
    assert workspace.flow.path is not None
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
            return _yosys_step(
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
            return _kepler_step(
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
    # The synthesized netlist against the RTL Synthesis read: its filelist, else its file.
    assert (lec_step.input.gate_verilog, lec_step.input.golden_verilog) == (
        synth_step.output.verilog,
        workspace.design.input_filelist if filelist else GCD_RTL,
    )
    # The LEC step must not advance the physical input chain.
    assert floorplan_step.input.verilog == synth_step.output.verilog


def test_engine_flow_wires_kepler_post_route_lec_against_synthesis_gate(tmp_path, monkeypatch):
    import chipcompiler.tools as tools

    workspace = _workspace(tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": StepEnum.SYNTHESIS.value,
                "tool": "yosys",
                "state": StateEnum.Unstart.value,
                **step_fields(StepEnum.SYNTHESIS.value, "yosys"),
            },
            {
                "name": StepEnum.LVS.value,
                "tool": "ecc",
                "state": StateEnum.Unstart.value,
                **step_fields(StepEnum.LVS.value, "ecc"),
            },
            {
                "name": SkippableStepEnum.POST_ROUTE_LEC.value,
                "tool": "kepler_formal",
                "state": StateEnum.Unstart.value,
                **step_fields(SkippableStepEnum.POST_ROUTE_LEC.value, "kepler_formal"),
            },
        ],
    }
    assert workspace.flow.path is not None
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
            return _kepler_step(
                name=step,
                tool=eda,
                input=SimpleNamespace(gate_verilog=input_verilog, golden_verilog=input_db),
                output=OutputPaths(json=tmp_path / step / "output" / f"gcd_{step}_result.json"),
            )
        if eda == "yosys":
            return _yosys_step(
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


def test_kepler_formal_config_yaml_contains_only_plain_values(tmp_path):
    import yaml

    from chipcompiler.tools.kepler_formal import builder

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    _write_netlist_pair(gate)
    step: Any = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.LEC.value,
        input_def=None,
        input_verilog=gate,
    )

    rendered = builder.build_lec_config_yaml(workspace, step)
    document = yaml.safe_load(rendered)

    for enum_name in (
        "StepEnum.",
        "SkippableStepEnum.",
        "StateEnum.",
        "LECEngineEnum.",
        "FlowStepCategory.",
    ):
        assert enum_name not in rendered
    assert document["verification"] == "lec"
    assert document["verilog_design2_top"] == "gcd"
    assert all(isinstance(path, str) for pair in document["input_paths"] for path in pair)
