"""Dual builder contract: path-only construction, delegated space/config."""

import json
from pathlib import Path

from ._helpers import GCD_RTL, _workspace


def _build(tmp_path):
    from chipcompiler.tools.lec_dual import builder

    workspace = _workspace(tmp_path)
    gate = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v"
    gate.parent.mkdir(parents=True)
    gate.write_text(GCD_RTL.read_text())
    step = builder.build_step(
        workspace=workspace,
        step_name="lec",
        input_def=None,
        input_verilog=gate,
    )
    return workspace, step


def test_build_step_is_path_only_and_builds_engine_steps_in_memory(tmp_path):
    workspace, step = _build(tmp_path)

    assert step.tool == "lec_dual"
    assert step.directory.name == "lec_dual"
    assert step.output.json.name == "gcd_lec_result.json"
    assert step.input.golden_verilog.name == "gcd_Synthesis_golden.v"
    assert set(step.engine_steps) == {"yosys_lec", "kepler_formal"}
    assert step.engine_steps["yosys_lec"].directory.name == "lec_yosys_lec"
    assert step.engine_steps["kepler_formal"].directory.name == "lec_kepler_formal"
    # Both engines share the aggregate's logical inputs.
    for engine_step in step.engine_steps.values():
        assert engine_step.input.gate_verilog == step.input.gate_verilog
        assert engine_step.input.golden_verilog == step.input.golden_verilog

    # An inspection-style build leaves the workspace tree untouched.
    assert not Path(workspace.directory).exists()


def test_build_step_space_creates_aggregate_and_engine_directories(tmp_path):
    from chipcompiler.tools.lec_dual import builder

    _workspace_dir, step = _build(tmp_path)
    builder.build_step_space(step)

    for directory in (
        step.directory,
        step.output.dir,
        step.log.dir,
        step.engine_steps["yosys_lec"].directory,
        step.engine_steps["kepler_formal"].directory,
    ):
        assert Path(directory).is_dir()


def test_build_step_config_is_idempotent_across_the_double_call(tmp_path):
    from chipcompiler.tools.lec_dual import builder

    workspace, step = _build(tmp_path)
    builder.build_step_space(step)
    builder.build_step_config(workspace, step)

    roots = [step.directory, *(engine_step.directory for engine_step in step.engine_steps.values())]
    first = {
        path: path.read_bytes()
        for root in roots
        for path in sorted(Path(root).rglob("*"))
        if path.is_file()
    }
    assert first

    builder.build_step_config(workspace, step)

    second = {
        path: path.read_bytes()
        for root in roots
        for path in sorted(Path(root).rglob("*"))
        if path.is_file()
    }
    assert first == second


def test_build_step_config_writes_engine_configs_and_the_aggregate_subflow(tmp_path):
    from chipcompiler.tools.lec_dual import builder

    workspace, step = _build(tmp_path)
    builder.build_step_space(step)
    builder.build_step_config(workspace, step)

    assert Path(step.engine_steps["yosys_lec"].data.config).is_file()
    assert Path(step.engine_steps["kepler_formal"].data.config).is_file()
    subflow = json.loads(Path(step.subflow.path).read_text())
    assert [stage["name"] for stage in subflow["steps"]] == [
        "run lec (yosys_lec)",
        "run lec (kepler_formal)",
        "analysis",
    ]
    assert {stage["state"] for stage in subflow["steps"]} == {"Unstart"}
