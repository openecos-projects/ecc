import json
import os
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import EccOutput, EccStep, StateEnum, StepEnum, Workspace

from ._sizer_helpers import _sizer_runtime, _subflow_states, _workspace


def test_timing_opt_step_result_does_not_require_gds(tmp_path):
    from chipcompiler.engine.flow import EngineFlow

    output_def = tmp_path / "out.def"
    output_verilog = tmp_path / "out.v"
    output_def.write_text("def\n", encoding="utf-8")
    output_verilog.write_text("module gcd; endmodule\n", encoding="utf-8")

    step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        output=EccOutput(
            def_=output_def,
            verilog=output_verilog,
            gds=tmp_path / "missing.gds",
        ),
    )

    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_timing_opt_step_result_requires_declared_geometry_manifest(tmp_path):
    from chipcompiler.engine.flow import EngineFlow

    output_def = tmp_path / "out.def"
    output_verilog = tmp_path / "out.v"
    geometry = tmp_path / "geometry"
    output_def.write_text("def\n", encoding="utf-8")
    output_verilog.write_text("module gcd; endmodule\n", encoding="utf-8")

    step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        output=EccOutput(
            def_=output_def,
            verilog=output_verilog,
            geometry=geometry,
            geometry_manifest=geometry / "geometry.manifest",
        ),
    )

    assert EngineFlow(Workspace()).check_step_result(step) is False
    geometry.mkdir()
    (geometry / "geometry.manifest").write_text("schema=ecc.geometry.v1\n")
    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_engine_flow_clears_cached_db_after_successful_sizer_step(tmp_path, monkeypatch):
    import chipcompiler.tools as tools_api
    from chipcompiler.engine import flow as flow_module
    from chipcompiler.engine.flow import EngineFlow

    workspace = _workspace(tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    # Preferred order is legalization then Timing Opt; a trailing extra
    # legalize sibling after Timing Opt is still a valid cached-DB boundary.
    workspace.flow.data = {
        "steps": [
            {
                "name": StepEnum.TIMING_OPT.value,
                "tool": "sizer",
                "state": StateEnum.Unstart.value,
            },
            {
                "name": StepEnum.LEGALIZATION.value,
                "tool": "ecc",
                "state": StateEnum.Unstart.value,
            },
        ]
    }

    sizer_step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        output=EccOutput(
            def_=tmp_path / "sizer.def",
            verilog=tmp_path / "sizer.v",
        ),
    )
    post_sizer_step = EccStep(
        name=StepEnum.LEGALIZATION.value,
        tool="ecc",
        output=EccOutput(
            def_=tmp_path / "post.def",
            verilog=tmp_path / "post.v",
            gds=tmp_path / "post.gds",
        ),
    )
    pre_sizer_db_closed = []

    class CloseableDb:
        engine = "pre-sizer-db"

        def has_init(self):
            return True

        def close(self):
            pre_sizer_db_closed.append(True)

    engine_flow = EngineFlow(workspace)
    engine_flow.workspace_steps = [sizer_step, post_sizer_step]
    monkeypatch.setattr(engine_flow, "engine_db", CloseableDb())

    init_seen = []
    run_seen = []

    def fake_init_db_engine():
        current_db = engine_flow.engine_db
        init_seen.append(None if current_db is None else current_db.engine)
        if current_db is None:
            assert pre_sizer_db_closed == [True]
            monkeypatch.setattr(
                engine_flow,
                "engine_db",
                SimpleNamespace(engine="post-sizer-db", has_init=lambda: True),
            )
        return True

    def fake_tool_run(workspace, step, ecc_module):
        del workspace
        run_seen.append(
            (
                step.tool,
                ecc_module,
            )
        )
        for path in (step.output.def_, step.output.verilog, step.output.gds):
            if path is None:
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as file:
                file.write("\n")
        return StateEnum.Success

    monkeypatch.setattr(engine_flow, "init_db_engine", fake_init_db_engine)
    monkeypatch.setattr(tools_api, "run_step", fake_tool_run)
    monkeypatch.setattr(tools_api, "save_layout_image", lambda workspace, step: True)
    monkeypatch.setattr(flow_module, "log_flow", lambda workspace: None)

    assert engine_flow.run_steps() is True
    assert init_seen == ["pre-sizer-db", None]
    assert pre_sizer_db_closed == [True]
    assert run_seen == [("sizer", "pre-sizer-db"), ("ecc", "post-sizer-db")]


def test_engine_flow_clears_cached_db_after_incomplete_sizer_step(tmp_path, monkeypatch):
    import chipcompiler.tools as tools_api
    from chipcompiler.engine import flow as flow_module
    from chipcompiler.engine.flow import EngineFlow

    workspace = _workspace(tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    workspace.flow.data = {
        "steps": [
            {
                "name": StepEnum.TIMING_OPT.value,
                "tool": "sizer",
                "state": StateEnum.Unstart.value,
            }
        ]
    }
    sizer_step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        output=EccOutput(
            def_=tmp_path / "sizer.def",
            verilog=tmp_path / "sizer.v",
        ),
    )
    closed = []

    class CloseableDb:
        engine = "pre-sizer-db"

        def has_init(self):
            return True

        def close(self):
            closed.append(True)

    engine_flow = EngineFlow(workspace)
    engine_flow.workspace_steps = [sizer_step]
    monkeypatch.setattr(engine_flow, "engine_db", CloseableDb())
    monkeypatch.setattr(engine_flow, "init_db_engine", lambda: True)
    monkeypatch.setattr(tools_api, "run_step", lambda **kwargs: StateEnum.Imcomplete)
    monkeypatch.setattr(tools_api, "save_layout_image", lambda workspace, step: True)
    monkeypatch.setattr(flow_module, "log_flow", lambda workspace: None)

    assert engine_flow.run_steps() is False
    assert closed == [True]
    assert engine_flow.engine_db is None


def test_legacy_one_stage_success_is_invalidated_before_skip(tmp_path, monkeypatch):
    from chipcompiler.engine.flow import EngineFlow
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(_sizer_runtime(tmp_path)))
    workspace = _workspace(tmp_path)
    workspace.flow.path = Path(workspace.directory) / "home" / "flow.json"
    workspace.flow.path.parent.mkdir(parents=True, exist_ok=True)
    flow_data = {
        "steps": [
            {
                "name": StepEnum.TIMING_OPT.value,
                "tool": "sizer",
                "state": StateEnum.Success.value,
            },
            {
                "name": StepEnum.ROUTING.value,
                "tool": "ecc",
                "state": StateEnum.Success.value,
            },
        ]
    }
    workspace.flow.path.write_text(json.dumps(flow_data), encoding="utf-8")
    workspace.flow.data = flow_data

    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def=Path("input.def"),
        input_verilog=Path("input.v"),
    )
    sizer_builder.build_step_space(step)
    output_def = Path(step.output.def_)
    output_verilog = Path(step.output.verilog)
    output_def.parent.mkdir(parents=True, exist_ok=True)
    output_def.write_text("unlegalized def\n", encoding="utf-8")
    output_verilog.write_text("module gcd; endmodule\n", encoding="utf-8")
    assert step.subflow.path is not None
    step.subflow.path.write_text(
        json.dumps(
            {
                "path": str(step.subflow.path),
                "steps": [
                    {
                        "name": "run sizer",
                        "state": StateEnum.Success.value,
                        "runtime": "",
                        "peak memory (mb)": 0,
                        "info": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sizer_builder.build_step_config(workspace, step)
    assert list(_subflow_states(step)) == [
        "run sizer",
        "run legalization",
        "save data",
    ]
    assert set(_subflow_states(step).values()) == {StateEnum.Unstart.value}
    persisted = json.loads(workspace.flow.path.read_text(encoding="utf-8"))
    assert [item["state"] for item in persisted["steps"]] == [
        StateEnum.Unstart.value,
        StateEnum.Unstart.value,
    ]

    engine_flow = EngineFlow(workspace)
    assert not engine_flow.check_state(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        state=StateEnum.Success,
    )
    assert not engine_flow.check_state(
        name=StepEnum.ROUTING.value,
        tool="ecc",
        state=StateEnum.Success,
    )
