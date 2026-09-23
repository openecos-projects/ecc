"""Dual runner: concurrency, converge-both, stale-evidence, degraded mode."""

import threading

from chipcompiler.data import LECEngineEnum
from chipcompiler.tools.lec_dual import runner as runner_module
from chipcompiler.utility import json_read

from ._helpers import (
    _aggregate_step,
    _engine_step,
    _workspace,
    _write_netlists,
    write_engine_result,
)


def _patch_engines(monkeypatch, tmp_path, runs, availability=None):
    """Wire fake engine steps/modules/availability into the dual runner."""
    engine_steps = {engine.value: _engine_step(tmp_path, engine.value) for engine in runs}
    modules = {engine: runner_module.lec_engine_module(engine) for engine in runs}
    from ._helpers import FakeEngineModule

    fakes = {engine: FakeEngineModule(modules[engine], runs[engine]) for engine in runs}
    monkeypatch.setattr(runner_module, "build_engine_steps", lambda workspace, step: engine_steps)
    monkeypatch.setattr(runner_module, "lec_engine_module", lambda engine: fakes[engine])
    if availability is None:
        availability = {engine: (True, "") for engine in runs}
    monkeypatch.setattr(runner_module, "engine_availability", lambda engine: availability[engine])
    return engine_steps


def _run(workspace, step):
    return runner_module.run_step(workspace, step)


def test_dual_run_aggregates_both_engine_results(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    golden, gate = _write_netlists(tmp_path)
    step = _aggregate_step(tmp_path, golden, gate)

    def proven_run(engine_step):
        write_engine_result(engine_step.output.json, proven=True)
        return True

    engine_steps = _patch_engines(
        monkeypatch,
        tmp_path,
        {LECEngineEnum.YOSYS_LEC: proven_run, LECEngineEnum.KEPLER_FORMAL: proven_run},
    )

    assert _run(workspace, step) is True

    aggregate = json_read(step.output.json)
    assert aggregate["status"] == "proven"
    assert aggregate["agreement"] is True
    assert set(aggregate["engines"]) == {"yosys_lec", "kepler_formal"}
    assert aggregate["engines"]["yosys_lec"]["status"] == "proven"
    # The top-level single-engine contract fields cover the shared inputs.
    from chipcompiler.utility import file_digest

    assert aggregate["golden_sha256"] == file_digest(golden)[0]
    assert aggregate["gate_sha256"] == file_digest(gate)[0]
    assert aggregate["golden_size_bytes"] == file_digest(golden)[1]
    assert aggregate["gate_size_bytes"] == file_digest(gate)[1]

    subflow = json_read(step.subflow.path)
    assert {stage["name"]: stage["state"] for stage in subflow["steps"]} == {
        "run lec (yosys_lec)": "Success",
        "run lec (kepler_formal)": "Success",
        "analysis": "Success",
    }
    assert engine_steps  # both per-engine workspaces were addressed


def test_engines_run_concurrently(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    golden, gate = _write_netlists(tmp_path)
    step = _aggregate_step(tmp_path, golden, gate)

    fast_done = threading.Event()

    def slow_yosys(engine_step):
        # yosys spawns first; a sequential runner would block here forever
        # because the fast sibling never starts.
        assert fast_done.wait(timeout=5), "fast engine did not finish while slow was blocked"
        write_engine_result(engine_step.output.json, proven=True)
        return True

    def fast_kepler(engine_step):
        write_engine_result(engine_step.output.json, proven=True)
        fast_done.set()
        return True

    _patch_engines(
        monkeypatch,
        tmp_path,
        {LECEngineEnum.YOSYS_LEC: slow_yosys, LECEngineEnum.KEPLER_FORMAL: fast_kepler},
    )

    assert _run(workspace, step) is True
    assert json_read(step.output.json)["agreement"] is True


def test_one_engine_raising_still_waits_for_the_sibling(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    golden, gate = _write_netlists(tmp_path)
    step = _aggregate_step(tmp_path, golden, gate)

    sibling_failed = threading.Event()

    def exploding_yosys(engine_step):
        sibling_failed.set()
        raise RuntimeError("yosys exploded")

    def slow_kepler(engine_step):
        # Converge-both: the failure must not terminate this engine; its
        # verdict is the cross-check evidence.
        assert sibling_failed.wait(timeout=5)
        write_engine_result(engine_step.output.json, proven=True)
        return True

    _patch_engines(
        monkeypatch,
        tmp_path,
        {LECEngineEnum.YOSYS_LEC: exploding_yosys, LECEngineEnum.KEPLER_FORMAL: slow_kepler},
    )

    assert _run(workspace, step) is False

    aggregate = json_read(step.output.json)
    assert aggregate["status"] == "incomplete"
    assert aggregate["agreement"] is None
    assert aggregate["engines"]["kepler_formal"]["status"] == "proven"
    assert aggregate["engines"]["yosys_lec"]["status"] == "incomplete"
    assert "yosys exploded" in aggregate["engines"]["yosys_lec"]["error"]

    subflow = json_read(step.subflow.path)
    states = {stage["name"]: stage["state"] for stage in subflow["steps"]}
    assert states["run lec (yosys_lec)"] == "Incomplete"
    assert states["run lec (kepler_formal)"] == "Success"

    orphan = [t for t in threading.enumerate() if t.name.startswith("lec_dual-")]
    assert orphan == []


def test_stale_evidence_is_deleted_before_spawning(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    golden, gate = _write_netlists(tmp_path)
    step = _aggregate_step(tmp_path, golden, gate)

    def silent_failure(engine_step):
        return False

    engine_steps = _patch_engines(
        monkeypatch,
        tmp_path,
        {LECEngineEnum.YOSYS_LEC: silent_failure, LECEngineEnum.KEPLER_FORMAL: silent_failure},
    )

    # Plant prior-run evidence everywhere the run reads from.
    step.output.json.write_text('{"status": "proven", "planted": true}\n')
    for engine_step in engine_steps.values():
        write_engine_result(engine_step.output.json, proven=True)
        engine_step.report.status.write_text("planted status\n")

    assert _run(workspace, step) is False

    # A pre-existing aggregate never survives as readable prior result: the
    # aggregate present now is the fresh one from this run.
    aggregate = json_read(step.output.json)
    assert "planted" not in aggregate
    assert aggregate["status"] == "incomplete"
    assert aggregate["agreement"] is None
    # Planted per-engine results/status reports are gone (engines wrote none).
    for engine_step in engine_steps.values():
        assert not engine_step.output.json.exists()
        assert not engine_step.report.status.exists()


def test_engine_failing_after_a_proven_result_never_proves_the_aggregate(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    golden, gate = _write_netlists(tmp_path)
    step = _aggregate_step(tmp_path, golden, gate)

    def exploding_yosys(engine_step):
        write_engine_result(engine_step.output.json, proven=True)
        raise RuntimeError("post-write explosion")

    def false_kepler(engine_step):
        write_engine_result(engine_step.output.json, proven=True)
        return False

    _patch_engines(
        monkeypatch,
        tmp_path,
        {LECEngineEnum.YOSYS_LEC: exploding_yosys, LECEngineEnum.KEPLER_FORMAL: false_kepler},
    )

    assert _run(workspace, step) is False

    aggregate = json_read(step.output.json)
    # Both engines left a proven verdict file but neither run succeeded:
    # the conservative aggregate never reports proven...
    assert aggregate["status"] == "incomplete"
    assert "post-write explosion" in aggregate["engines"]["yosys_lec"]["error"]
    # ...while agreement keeps its tri-state verdict semantics: both
    # parseable status fields match.
    assert aggregate["agreement"] is True


def test_stale_evidence_deletion_failure_stops_the_run(tmp_path, monkeypatch):
    from pathlib import Path

    workspace = _workspace(tmp_path)
    golden, gate = _write_netlists(tmp_path)
    step = _aggregate_step(tmp_path, golden, gate)

    ran = []

    def unreachable(engine_step):
        ran.append(engine_step)
        raise AssertionError("no engine may run when stale evidence survives")

    engine_steps = _patch_engines(
        monkeypatch,
        tmp_path,
        {LECEngineEnum.YOSYS_LEC: unreachable, LECEngineEnum.KEPLER_FORMAL: unreachable},
    )
    planted = engine_steps["yosys_lec"].output.json
    write_engine_result(planted, proven=True)

    def failing_unlink(self, *, missing_ok=False):
        raise OSError("read-only directory")

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    assert _run(workspace, step) is False
    assert ran == []
    assert not step.output.json.exists()
    assert "failed to delete stale LEC evidence" in step.log.file.read_text()
    subflow = json_read(step.subflow.path)
    states = {stage["name"]: stage["state"] for stage in subflow["steps"]}
    assert states["run lec (yosys_lec)"] == "Invalid"
    assert states["run lec (kepler_formal)"] == "Invalid"


def test_degraded_mode_runs_the_available_engine(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    golden, gate = _write_netlists(tmp_path)
    step = _aggregate_step(tmp_path, golden, gate)

    def proven_yosys(engine_step):
        write_engine_result(engine_step.output.json, proven=True)
        return True

    ran = []

    def unreachable_kepler(engine_step):
        ran.append(engine_step)
        raise AssertionError("unavailable engine must not run")

    _patch_engines(
        monkeypatch,
        tmp_path,
        {LECEngineEnum.YOSYS_LEC: proven_yosys, LECEngineEnum.KEPLER_FORMAL: unreachable_kepler},
        availability={
            LECEngineEnum.YOSYS_LEC: (True, ""),
            LECEngineEnum.KEPLER_FORMAL: (False, "kepler-formal is not installed"),
        },
    )

    # A degraded run never reports proven.
    assert _run(workspace, step) is False
    assert ran == []

    aggregate = json_read(step.output.json)
    assert aggregate["status"] == "incomplete"
    assert aggregate["agreement"] is None
    assert aggregate["engines"]["yosys_lec"]["status"] == "proven"
    assert aggregate["engines"]["kepler_formal"] == {
        "status": "unavailable",
        "reason": "kepler-formal is not installed",
    }

    subflow = json_read(step.subflow.path)
    states = {stage["name"]: stage["state"] for stage in subflow["steps"]}
    assert states["run lec (yosys_lec)"] == "Success"
    assert states["run lec (kepler_formal)"] == "Invalid"
    # Mirror the single-engine contract: analysis succeeds only with a
    # proven verdict; anything less stays Unstart.
    assert states["analysis"] == "Unstart"


def test_both_engines_unavailable_starts_no_run(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    golden, gate = _write_netlists(tmp_path)
    step = _aggregate_step(tmp_path, golden, gate)

    ran = []

    def unreachable(engine_step):
        ran.append(engine_step)
        raise AssertionError("no engine may run")

    _patch_engines(
        monkeypatch,
        tmp_path,
        {LECEngineEnum.YOSYS_LEC: unreachable, LECEngineEnum.KEPLER_FORMAL: unreachable},
        availability={
            LECEngineEnum.YOSYS_LEC: (False, "no yosys"),
            LECEngineEnum.KEPLER_FORMAL: (False, "no kepler"),
        },
    )

    assert _run(workspace, step) is False
    assert ran == []
    # No evidence is produced for a step that never started.
    assert not step.output.json.exists()
    subflow = json_read(step.subflow.path)
    states = {stage["name"]: stage["state"] for stage in subflow["steps"]}
    assert states["run lec (yosys_lec)"] == "Invalid"
    assert states["run lec (kepler_formal)"] == "Invalid"
    assert "no LEC engine" in step.log.file.read_text()


def test_runner_rebuilds_engine_steps_at_run_time(tmp_path, monkeypatch):
    """The attached engine steps are build-time wiring; the runner works
    with freshly rebuilt ones, so nothing relies on attached state."""
    from chipcompiler.tools.lec_dual import builder

    workspace = _workspace(tmp_path)
    golden, gate = _write_netlists(tmp_path)

    runs = {}

    def proven_run(engine_step):
        runs[engine_step.tool] = engine_step
        write_engine_result(engine_step.output.json, proven=True)
        return True

    real_modules = {
        engine: runner_module.lec_engine_module(engine)
        for engine in LECEngineEnum.DUAL.spawn_engines
    }
    from ._helpers import FakeEngineModule

    fakes = {
        engine: FakeEngineModule(real_modules[engine], proven_run)
        for engine in LECEngineEnum.DUAL.spawn_engines
    }
    monkeypatch.setattr(builder, "lec_engine_module", lambda engine: fakes[engine])
    monkeypatch.setattr(runner_module, "lec_engine_module", lambda engine: fakes[engine])
    monkeypatch.setattr(runner_module, "engine_availability", lambda engine: (True, ""))

    step = builder.build_step(
        workspace=workspace,
        step_name="lec",
        input_def=None,
        input_verilog=gate,
        input_db=golden,
    )
    builder.build_step_space(step)
    # Poison the build-time attachment: the run must not consult it.
    step.engine_steps.clear()

    assert runner_module.run_step(workspace, step) is True
    assert set(runs) == {"yosys_lec", "kepler_formal"}
    for engine_step in runs.values():
        assert engine_step.directory.parent == workspace.directory
    assert json_read(step.output.json)["status"] == "proven"
