import copy
import json
from types import SimpleNamespace

import pytest

from chipcompiler.data import EccOutput, EccStep, StateEnum, Workspace
from chipcompiler.data.workspace import Flow
from chipcompiler.engine import rerun
from chipcompiler.engine.flow import EngineFlow


def _make_run_flow(tmp_path, steps):
    """EngineFlow over a persisted flow.json plus aligned workspace steps."""
    home = tmp_path / "home"
    home.mkdir()
    workspace = Workspace(directory=tmp_path, flow=Flow(path=home / "flow.json"))
    engine_flow = EngineFlow(workspace)
    engine_flow.workspace.flow.data = {
        "steps": [
            {
                "name": name,
                "tool": "ecc",
                "state": state,
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
            }
            for name, state in steps
        ]
    }
    engine_flow.save()
    engine_flow.workspace_steps = []
    for name, _state in steps:
        directory = tmp_path / f"{name}_ecc"
        engine_flow.workspace_steps.append(
            EccStep(
                name=name,
                tool="ecc",
                directory=directory,
                output=EccOutput(dir=directory / "output"),
            )
        )
    return engine_flow


def _fake_execution(engine_flow, monkeypatch, outcomes=None):
    calls = []
    outcomes = outcomes or {}

    def run_step(workspace_step, *, rerun=False):
        calls.append((workspace_step.name, rerun))
        state = outcomes.get(workspace_step.name, StateEnum.Success)
        engine_flow.set_state(workspace_step.name, workspace_step.tool, state)
        return state

    monkeypatch.setattr(engine_flow, "run_step", run_step)
    monkeypatch.setattr(engine_flow, "init_db_engine_for_step", lambda step: True)
    return calls


def _write_output(engine_flow, name, content="old"):
    step = engine_flow.get_workspace_step(name)
    output_dir = step.output.dir
    output_dir.mkdir(parents=True, exist_ok=True)
    sentinel = output_dir / f"{name}.def.gz"
    sentinel.write_text(content, encoding="utf-8")
    return sentinel


def _flow_states(engine_flow):
    return [step["state"] for step in engine_flow.workspace.flow.data["steps"]]


class TestSelectedStepNames:
    def test_resume_selects_suffix_from_first_non_success(self, tmp_path):
        flow = _make_run_flow(
            tmp_path,
            [("Synthesis", "Success"), ("place", "Incomplete"), ("CTS", "Success")],
        )

        assert rerun.selected_step_names(flow) == ["place", "CTS"]

    def test_resume_all_success_selects_nothing(self, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success")])

        assert rerun.selected_step_names(flow) == []

    def test_from_selects_suffix(self, tmp_path):
        flow = _make_run_flow(
            tmp_path,
            [("Synthesis", "Success"), ("place", "Success"), ("CTS", "Success")],
        )

        assert rerun.selected_step_names(flow, from_step="place") == ["place", "CTS"]

    def test_only_success_step_requires_force(self, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success")])

        assert rerun.selected_step_names(flow, only="place") == []
        assert rerun.selected_step_names(flow, only="place", force=True) == ["place"]

    def test_unknown_step_lists_available_names(self, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success"), ("CTS", "Unstart")])

        with pytest.raises(ValueError, match="place.*CTS"):
            rerun.selected_step_names(flow, only="bogus")


class TestRunFrom:
    def test_reexecutes_suffix_and_clears_only_executed_outputs(self, monkeypatch, tmp_path):
        flow = _make_run_flow(
            tmp_path,
            [("Synthesis", "Success"), ("place", "Success"), ("CTS", "Success")],
        )
        keep = _write_output(flow, "Synthesis")
        stale_place = _write_output(flow, "place")
        stale_cts = _write_output(flow, "CTS")
        calls = _fake_execution(flow, monkeypatch)

        result = rerun.run_from(flow, "place")

        assert result.ok
        assert result.executed == ("place", "CTS")
        assert result.failed is None
        assert calls == [("place", True), ("CTS", True)]
        assert keep.read_text(encoding="utf-8") == "old"
        assert not stale_place.exists()
        assert not stale_cts.exists()

    def test_direct_run_self_archives_step_bytes(self, monkeypatch, tmp_path, capfd):
        """In-process rerun routes fd 1/2 through the archiver: step bytes land
        in the step log and markers never reach the caller's terminal."""
        import os

        from chipcompiler.runtime.log_stream import emit_step_marker

        flow = _make_run_flow(tmp_path, [("place", "Success"), ("CTS", "Unstart")])
        _write_output(flow, "place")

        def run_step_with_bytes(workspace_step, *, rerun=False):
            emit_step_marker("begin", step=workspace_step.name, tool=workspace_step.tool)
            os.write(2, f"{workspace_step.name} bytes\n".encode())
            emit_step_marker("end", step=workspace_step.name, tool=workspace_step.tool)
            flow.set_state(workspace_step.name, workspace_step.tool, StateEnum.Success)
            return StateEnum.Success

        monkeypatch.setattr(flow, "run_step", run_step_with_bytes)
        monkeypatch.setattr(flow, "init_db_engine_for_step", lambda step: True)

        result = rerun.run_from(flow, "place")

        assert result.ok
        archive = tmp_path / "place_ecc" / "log" / "place.log"
        assert archive.read_bytes() == b"place bytes\n"
        assert "ECC-STEP" not in capfd.readouterr().err

    def test_archive_failure_fails_and_downgrades_the_record(self, monkeypatch, tmp_path, capfd):
        """An in-process archive failure must not leave ok=True over a Success
        record with a missing log."""
        import os

        from chipcompiler.runtime.log_stream import emit_step_marker

        flow = _make_run_flow(tmp_path, [("place", "Success")])
        _write_output(flow, "place")

        def run_step_with_markers(workspace_step, *, rerun=False):
            emit_step_marker("begin", step=workspace_step.name, tool=workspace_step.tool)
            os.write(2, b"bytes\n")
            emit_step_marker("end", step=workspace_step.name, tool=workspace_step.tool)
            flow.set_state(workspace_step.name, workspace_step.tool, StateEnum.Success)
            return StateEnum.Success

        monkeypatch.setattr(flow, "run_step", run_step_with_markers)
        monkeypatch.setattr(flow, "init_db_engine_for_step", lambda step: True)

        # Make the archive path unopenable: a regular file where the step's
        # log directory must be created (the output dir stays intact).
        (tmp_path / "place_ecc" / "log").write_text("regular file")

        result = rerun.run_from(flow, "place")

        assert result.ok is False
        assert result.failed == "place"
        assert _flow_states(flow) == [StateEnum.Imcomplete.value]
        assert "ECC-STEP" not in capfd.readouterr().err

    def test_step_exception_reconciles_archive_before_propagating(
        self, monkeypatch, tmp_path, capfd
    ):
        """A run_step that raises after its begin marker still reconciles the
        reader state before the exception propagates."""
        import os

        from chipcompiler.runtime.log_stream import emit_step_marker

        flow = _make_run_flow(tmp_path, [("place", "Success")])
        _write_output(flow, "place")

        def raising_run_step(workspace_step, *, rerun=False):
            emit_step_marker("begin", step=workspace_step.name, tool=workspace_step.tool)
            os.write(2, b"partial output\n")
            raise RuntimeError("post-processing blew up")

        monkeypatch.setattr(flow, "run_step", raising_run_step)
        monkeypatch.setattr(flow, "init_db_engine_for_step", lambda step: True)

        with pytest.raises(RuntimeError, match="post-processing"):
            rerun.run_from(flow, "place")

        # The unmatched begin downgraded the record instead of leaving a
        # stale Success over a partial archive.
        assert _flow_states(flow) == [StateEnum.Imcomplete.value]
        assert "ECC-STEP" not in capfd.readouterr().err

    def test_failure_stops_suffix_and_keeps_downstream_output(self, monkeypatch, tmp_path):
        flow = _make_run_flow(
            tmp_path,
            [("place", "Success"), ("CTS", "Success"), ("route", "Success")],
        )
        route_output = _write_output(flow, "route")
        calls = _fake_execution(flow, monkeypatch, outcomes={"CTS": StateEnum.Imcomplete})

        result = rerun.run_from(flow, "place")

        assert not result.ok
        assert result.executed == ("place",)
        assert result.failed == "CTS"
        assert calls == [("place", True), ("CTS", True)]
        assert _flow_states(flow) == ["Success", "Incomplete", "Unstart"]
        assert route_output.read_text(encoding="utf-8") == "old"

    def test_suffix_invalidation_is_persisted_before_execution(self, monkeypatch, tmp_path):
        flow = _make_run_flow(
            tmp_path,
            [("Synthesis", "Success"), ("place", "Success"), ("CTS", "Success")],
        )
        persisted = []

        def run_step(workspace_step, *, rerun=False):
            disk = json.loads(flow.workspace.flow.path.read_text(encoding="utf-8"))
            persisted.append([step["state"] for step in disk["steps"]])
            flow.set_state(workspace_step.name, workspace_step.tool, StateEnum.Success)
            return StateEnum.Success

        monkeypatch.setattr(flow, "run_step", run_step)
        monkeypatch.setattr(flow, "init_db_engine_for_step", lambda step: True)

        assert rerun.run_from(flow, "place").ok
        # the suffix is already persisted Unstart when the first selected step runs
        assert persisted[0] == ["Success", "Unstart", "Unstart"]

    def test_failed_invalidation_save_refuses_to_modify_outputs(self, monkeypatch, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success"), ("CTS", "Success")])
        sentinel = _write_output(flow, "place")
        original = flow.workspace.flow.path.read_bytes()
        monkeypatch.setattr(flow, "save", lambda: False)

        with pytest.raises(ValueError, match="refusing to modify outputs"):
            rerun.run_from(flow, "place")

        assert flow.workspace.flow.path.read_bytes() == original
        assert sentinel.read_text(encoding="utf-8") == "old"

    def test_unknown_step_does_not_mutate_workspace(self, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success")])
        sentinel = _write_output(flow, "place")
        original = flow.workspace.flow.path.read_bytes()
        original_data = copy.deepcopy(flow.workspace.flow.data)

        with pytest.raises(ValueError, match="unknown step"):
            rerun.run_from(flow, "bogus")

        assert flow.workspace.flow.path.read_bytes() == original
        assert flow.workspace.flow.data == original_data
        assert sentinel.read_text(encoding="utf-8") == "old"

    def test_missing_workspace_step_breaks_the_chain_and_is_rejected(self, tmp_path):
        flow = _make_run_flow(tmp_path, [("Synthesis", "Success"), ("place", "Success")])
        flow.workspace_steps = flow.workspace_steps[1:]
        original = flow.workspace.flow.path.read_bytes()
        original_data = copy.deepcopy(flow.workspace.flow.data)

        with pytest.raises(ValueError, match="Synthesis"):
            rerun.run_from(flow, "place")

        assert flow.workspace.flow.path.read_bytes() == original
        assert flow.workspace.flow.data == original_data

    def test_non_canonical_output_is_rejected_before_mutation(self, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success")])
        outside = tmp_path / "outside"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        flow.workspace_steps[0].output.dir = outside
        original = flow.workspace.flow.path.read_bytes()
        original_data = copy.deepcopy(flow.workspace.flow.data)

        with pytest.raises(ValueError, match="canonical"):
            rerun.run_from(flow, "place")

        assert flow.workspace.flow.path.read_bytes() == original
        assert flow.workspace.flow.data == original_data
        assert sentinel.read_text(encoding="utf-8") == "keep"

    def test_closes_inherited_db_engine_before_running(self, monkeypatch, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success")])
        closed = []
        flow.engine_db = SimpleNamespace(close=lambda: closed.append(True))
        _fake_execution(flow, monkeypatch)

        assert rerun.run_from(flow, "place").ok
        assert closed == [True]


class TestRunOnly:
    def test_successful_step_without_force_is_noop(self, monkeypatch, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success"), ("CTS", "Success")])
        sentinel = _write_output(flow, "place")
        calls = _fake_execution(flow, monkeypatch)

        result = rerun.run_only(flow, "place")

        assert result.ok
        assert result.executed == ()
        assert calls == []
        assert _flow_states(flow) == ["Success", "Success"]
        assert sentinel.read_text(encoding="utf-8") == "old"

    def test_force_reruns_and_invalidates_downstream(self, monkeypatch, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success"), ("CTS", "Success")])
        stale_place = _write_output(flow, "place")
        keep_cts = _write_output(flow, "CTS")
        calls = _fake_execution(flow, monkeypatch)

        result = rerun.run_only(flow, "place", force=True)

        assert result.ok
        assert result.executed == ("place",)
        assert calls == [("place", True)]
        assert _flow_states(flow) == ["Success", "Unstart"]
        assert not stale_place.exists()
        assert keep_cts.read_text(encoding="utf-8") == "old"

    def test_non_success_step_runs_without_force(self, monkeypatch, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Incomplete")])
        calls = _fake_execution(flow, monkeypatch)

        result = rerun.run_only(flow, "place")

        assert result.ok
        assert result.executed == ("place",)
        assert calls == [("place", True)]

    def test_failure_reports_failed_step(self, monkeypatch, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Incomplete")])
        _fake_execution(flow, monkeypatch, outcomes={"place": StateEnum.Imcomplete})

        result = rerun.run_only(flow, "place")

        assert not result.ok
        assert result.executed == ()
        assert result.failed == "place"
        assert _flow_states(flow) == ["Incomplete"]


class TestRunResume:
    def test_reruns_suffix_from_first_non_success(self, monkeypatch, tmp_path):
        flow = _make_run_flow(
            tmp_path,
            [("Synthesis", "Success"), ("place", "Incomplete"), ("CTS", "Success")],
        )
        calls = _fake_execution(flow, monkeypatch)

        result = rerun.run_resume(flow)

        assert result.ok
        assert result.executed == ("place", "CTS")
        assert calls == [("place", True), ("CTS", True)]

    def test_all_success_is_noop(self, monkeypatch, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success")])
        calls = _fake_execution(flow, monkeypatch)

        result = rerun.run_resume(flow)

        assert result.ok
        assert result.executed == ()
        assert calls == []


class TestInitDbEngineForStep:
    def test_creates_engine_for_the_selected_step(self, monkeypatch, tmp_path):
        from chipcompiler.engine import EngineDB

        flow = _make_run_flow(tmp_path, [("place", "Success")])
        created = []

        def create_db_engine(self, step):
            created.append(step)
            return True

        monkeypatch.setattr(EngineDB, "create_db_engine", create_db_engine)
        step = flow.workspace_steps[0]

        assert flow.init_db_engine_for_step(step) is True
        assert created == [step]
        assert isinstance(flow.engine_db, EngineDB)

    def test_reuses_initialized_engine(self, tmp_path):
        flow = _make_run_flow(tmp_path, [("place", "Success")])
        engine_db = SimpleNamespace(has_init=lambda: True)
        flow.engine_db = engine_db

        assert flow.init_db_engine_for_step(flow.workspace_steps[0]) is True
        assert flow.engine_db is engine_db
