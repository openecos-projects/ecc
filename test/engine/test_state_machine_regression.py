"""
Regression tests for EngineFlow state machine transition guards.

Tests that set_state() enforces lifecycle transitions, batch resets
bypass guards, and idempotency/staleness invariants hold.
"""

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler import tools
from chipcompiler.data import EccOutput, EccStep, OriginDesign, StateEnum, Workspace
from chipcompiler.data.workspace import Flow
from chipcompiler.engine.flow import _VALID_TRANSITIONS, EngineFlow
from chipcompiler.utility import Logger


def _make_workspace(tmp_path: Path, num_steps: int = 3) -> Workspace:
    ws_dir = str(tmp_path / "workspace")
    os.makedirs(ws_dir, exist_ok=True)
    home_dir = os.path.join(ws_dir, "home")
    os.makedirs(home_dir, exist_ok=True)
    os.makedirs(os.path.join(ws_dir, "log"), exist_ok=True)

    flow_path = os.path.join(home_dir, "flow.json")
    steps = []
    for i in range(num_steps):
        steps.append(
            {
                "name": f"step_{i}",
                "tool": "mock",
                "state": StateEnum.Unstart.value,
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
            }
        )

    with open(flow_path, "w") as f:
        json.dump({"steps": steps}, f)

    return Workspace(
        directory=ws_dir,
        design=OriginDesign(name="test", top_module="test"),
        flow=Flow(path=flow_path, data={"steps": steps}),
        logger=Logger(),
    )


class TestValidTransitionGuards:
    """set_state() only allows transitions in _VALID_TRANSITIONS."""

    def test_unstart_to_ongoing(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        assert flow.set_state("step_0", "mock", StateEnum.Ongoing)
        step = flow.get_step(name="step_0", tool="mock")
        assert step["state"] == StateEnum.Ongoing.value

    def test_unstart_to_incomplete(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        assert flow.set_state("step_0", "mock", StateEnum.Imcomplete)
        step = flow.get_step(name="step_0", tool="mock")
        assert step["state"] == StateEnum.Imcomplete.value

    def test_ongoing_to_success(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        flow.set_state("step_0", "mock", StateEnum.Ongoing)
        assert flow.set_state("step_0", "mock", StateEnum.Success)

    def test_ongoing_to_incomplete(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        flow.set_state("step_0", "mock", StateEnum.Ongoing)
        assert flow.set_state("step_0", "mock", StateEnum.Imcomplete)

    def test_ongoing_to_invalid(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        flow.set_state("step_0", "mock", StateEnum.Ongoing)
        assert flow.set_state("step_0", "mock", StateEnum.Invalid)

    def test_pending_to_ongoing(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        step = flow.get_step(name="step_0", tool="mock")
        step["state"] = StateEnum.Pending.value
        flow.save()
        assert flow.set_state("step_0", "mock", StateEnum.Ongoing)

    def test_pending_to_incomplete(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        step = flow.get_step(name="step_0", tool="mock")
        step["state"] = StateEnum.Pending.value
        flow.save()
        assert flow.set_state("step_0", "mock", StateEnum.Imcomplete)


class TestInvalidTransitionRejection:
    """set_state() raises ValueError for transitions not in _VALID_TRANSITIONS."""

    def test_unstart_to_success_rejected(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        with pytest.raises(ValueError, match="Illegal state transition"):
            flow.set_state("step_0", "mock", StateEnum.Success)

    def test_unstart_to_invalid_rejected(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        with pytest.raises(ValueError, match="Illegal state transition"):
            flow.set_state("step_0", "mock", StateEnum.Invalid)

    def test_success_to_ongoing_rejected(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        step = flow.get_step(name="step_0", tool="mock")
        step["state"] = StateEnum.Success.value
        flow.save()
        with pytest.raises(ValueError, match="Illegal state transition"):
            flow.set_state("step_0", "mock", StateEnum.Ongoing)

    def test_incomplete_to_ongoing_rejected(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        step = flow.get_step(name="step_0", tool="mock")
        step["state"] = StateEnum.Imcomplete.value
        flow.save()
        with pytest.raises(ValueError, match="Illegal state transition"):
            flow.set_state("step_0", "mock", StateEnum.Ongoing)

    def test_invalid_to_ongoing_rejected(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        step = flow.get_step(name="step_0", tool="mock")
        step["state"] = StateEnum.Invalid.value
        flow.save()
        with pytest.raises(ValueError, match="Illegal state transition"):
            flow.set_state("step_0", "mock", StateEnum.Ongoing)

    def test_invalid_to_success_rejected(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        step = flow.get_step(name="step_0", tool="mock")
        step["state"] = StateEnum.Invalid.value
        flow.save()
        with pytest.raises(ValueError, match="Illegal state transition"):
            flow.set_state("step_0", "mock", StateEnum.Success)


class TestIdempotency:
    """set_state() with same value persists and returns True (no guard violation)."""

    def test_unstart_to_unstart(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        assert flow.set_state("step_0", "mock", StateEnum.Unstart)

    def test_ongoing_to_ongoing(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        flow.set_state("step_0", "mock", StateEnum.Ongoing)
        assert flow.set_state("step_0", "mock", StateEnum.Ongoing)

    def test_success_to_success(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        step = flow.get_step(name="step_0", tool="mock")
        step["state"] = StateEnum.Success.value
        flow.save()
        assert flow.set_state("step_0", "mock", StateEnum.Success)


class TestBatchResetBypassesGuards:
    """clear_states() bypasses set_state() guards via direct assignment."""

    def test_clear_resets_all_to_unstart(self, tmp_path):
        ws = _make_workspace(tmp_path, num_steps=5)
        flow = EngineFlow(workspace=ws)

        # Set lifecycle-reachable states via set_state
        flow.set_state("step_0", "mock", StateEnum.Ongoing)
        flow.set_state("step_1", "mock", StateEnum.Ongoing)
        flow.set_state("step_1", "mock", StateEnum.Success)

        # Set terminal states via direct assignment (bypassing guards)
        for i, state in [(2, StateEnum.Imcomplete), (3, StateEnum.Invalid), (4, StateEnum.Pending)]:
            step = flow.get_step(name=f"step_{i}", tool="mock")
            step["state"] = state.value
        flow.save()

        flow.clear_states()

        for i in range(5):
            step = flow.get_step(name=f"step_{i}", tool="mock")
            assert step["state"] == StateEnum.Unstart.value

    def test_invalidate_suffix_resets_to_unstart(self, tmp_path):
        from chipcompiler.engine import rerun

        ws = _make_workspace(tmp_path, num_steps=5)
        flow = EngineFlow(workspace=ws)

        flow.set_state("step_0", "mock", StateEnum.Ongoing)
        flow.set_state("step_0", "mock", StateEnum.Success)
        flow.set_state("step_1", "mock", StateEnum.Ongoing)
        flow.set_state("step_1", "mock", StateEnum.Success)
        flow.set_state("step_2", "mock", StateEnum.Ongoing)
        flow.set_state("step_2", "mock", StateEnum.Invalid)

        # Directly set remaining steps to Invalid (bypassing guards)
        for i in [3, 4]:
            step = flow.get_step(name=f"step_{i}", tool="mock")
            step["state"] = StateEnum.Invalid.value
        flow.save()

        # _invalidate_suffix takes an integer index
        rerun._invalidate_suffix(flow, 2)

        # step_2 and all downstream should be Unstart
        for i in [2, 3, 4]:
            step = flow.get_step(name=f"step_{i}", tool="mock")
            assert step["state"] == StateEnum.Unstart.value

        # step_0, step_1 should remain Success
        for i in [0, 1]:
            step = flow.get_step(name=f"step_{i}", tool="mock")
            assert step["state"] == StateEnum.Success.value


class TestPersistence:
    """set_state() persists to JSON file after guard check passes."""

    def test_state_persists_to_file(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        flow.set_state("step_0", "mock", StateEnum.Ongoing)
        flow.set_state("step_0", "mock", StateEnum.Success)

        # Reload from disk
        flow2 = EngineFlow(workspace=ws)
        step = flow2.get_step(name="step_0", tool="mock")
        assert step["state"] == StateEnum.Success.value

    def test_rejected_transition_does_not_persist(self, tmp_path):
        ws = _make_workspace(tmp_path)
        flow = EngineFlow(workspace=ws)
        with pytest.raises(ValueError, match="Illegal state transition"):
            flow.set_state("step_0", "mock", StateEnum.Success)

        # Reload — should still be Unstart
        flow2 = EngineFlow(workspace=ws)
        step = flow2.get_step(name="step_0", tool="mock")
        assert step["state"] == StateEnum.Unstart.value


class TestResumeAndRerun:
    """Resume/rerun lifecycle goes through Unstart → Ongoing → target."""

    def test_rerun_respects_lifecycle(self, tmp_path):
        ws = _make_workspace(tmp_path, num_steps=3)
        flow = EngineFlow(workspace=ws)

        # Simulate lifecycle: Unstart → Ongoing → Success
        for i in range(3):
            flow.set_state(f"step_{i}", "mock", StateEnum.Ongoing)
            flow.set_state(f"step_{i}", "mock", StateEnum.Success)

        # Reload — all should be Success
        flow2 = EngineFlow(workspace=ws)
        for i in range(3):
            step = flow2.get_step(name=f"step_{i}", tool="mock")
            assert step["state"] == StateEnum.Success.value


class TestTransitionTableCompleteness:
    """All transitions in _VALID_TRANSITIONS are documented and tested."""

    def test_all_source_states_covered(self):
        """_VALID_TRANSITIONS covers all 6 StateEnum string values."""
        all_states = {s.value for s in StateEnum}
        assert set(_VALID_TRANSITIONS.keys()) == all_states

    def test_no_self_transitions(self):
        """No state transitions to itself (except implicitly via idempotency)."""
        for src, targets in _VALID_TRANSITIONS.items():
            assert src not in targets, f"{src} should not transition to itself"


# ---------------------------------------------------------------------------
# Legacy state normalization tests (Phase 3a)
# ---------------------------------------------------------------------------


def _make_resume_workspace(tmp_path, steps):
    """Create workspace + EngineFlow with persisted flow.json and aligned workspace_steps."""
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
    engine_flow.engine_db = SimpleNamespace(engine=None)
    for name, _ in steps:
        directory = tmp_path / f"{name}_ecc"
        directory.mkdir(exist_ok=True)
        engine_flow.workspace_steps.append(
            EccStep(
                name=name,
                tool="ecc",
                directory=directory,
                output=EccOutput(verilog=directory / "design.v"),
            )
        )
    return engine_flow


class TestLegacyStateNormalization:
    """run_step() normalizes terminal states before set_state(Ongoing)."""

    def test_incomplete_step_normalized_on_resume(self, tmp_path, monkeypatch):
        """Legacy workspace with Incomplete step — resume normalizes it."""
        flow = _make_resume_workspace(
            tmp_path,
            [("Synthesis", "Success"), ("Floorplan", "Incomplete")],
        )
        monkeypatch.setattr(tools, "run_step", lambda **_kw: True)
        monkeypatch.setattr(flow, "check_step_result", lambda **_kw: True)

        # This must NOT raise ValueError
        result = flow.run_step(flow.workspace_steps[1], rerun=False)
        assert result == StateEnum.Success

        # Verify persisted state is Success (not Incomplete)
        persisted = json.loads((tmp_path / "home" / "flow.json").read_text())
        assert persisted["steps"][1]["state"] == StateEnum.Success.value

    def test_invalid_step_normalized_on_resume(self, tmp_path, monkeypatch):
        """Legacy workspace with Invalid step — resume normalizes it."""
        flow = _make_resume_workspace(
            tmp_path,
            [("Synthesis", "Success"), ("Floorplan", "Invalid")],
        )
        monkeypatch.setattr(tools, "run_step", lambda **_kw: True)
        monkeypatch.setattr(flow, "check_step_result", lambda **_kw: True)

        result = flow.run_step(flow.workspace_steps[1], rerun=False)
        assert result == StateEnum.Success

        persisted = json.loads((tmp_path / "home" / "flow.json").read_text())
        assert persisted["steps"][1]["state"] == StateEnum.Success.value

    def test_ongoing_step_not_normalized(self, tmp_path, monkeypatch):
        """Ongoing step is NOT a terminal state — no normalization needed."""
        flow = _make_resume_workspace(
            tmp_path,
            [("Synthesis", "Success"), ("Floorplan", "Ongoing")],
        )
        monkeypatch.setattr(tools, "run_step", lambda **_kw: True)
        monkeypatch.setattr(flow, "check_step_result", lambda **_kw: True)

        # Ongoing → Ongoing is idempotent, should work
        result = flow.run_step(flow.workspace_steps[1], rerun=False)
        assert result == StateEnum.Success

    def test_unstart_step_not_affected(self, tmp_path, monkeypatch):
        """Normal Unstart step — no normalization, normal lifecycle."""
        flow = _make_resume_workspace(
            tmp_path,
            [("Synthesis", "Success"), ("Floorplan", "Unstart")],
        )
        monkeypatch.setattr(tools, "run_step", lambda **_kw: True)
        monkeypatch.setattr(flow, "check_step_result", lambda **_kw: True)

        result = flow.run_step(flow.workspace_steps[1], rerun=False)
        assert result == StateEnum.Success

    def test_normalization_emits_warning(self, tmp_path, monkeypatch, caplog):
        """Normalization logs a warning so the legacy state is not silently lost."""
        flow = _make_resume_workspace(
            tmp_path,
            [("Synthesis", "Success"), ("Floorplan", "Incomplete")],
        )
        monkeypatch.setattr(tools, "run_step", lambda **_kw: True)
        monkeypatch.setattr(flow, "check_step_result", lambda **_kw: True)

        with caplog.at_level(logging.WARNING):
            flow.run_step(flow.workspace_steps[1], rerun=False)
        assert "Normalizing legacy" in caplog.text
        assert "Incomplete" in caplog.text

    def test_agent_incomplete_step_normalized_on_resume(self, tmp_path, monkeypatch):
        """AgentEngineFlow: legacy Incomplete step resumes without ValueError."""
        import agent.engine as agent_engine

        flow = _make_resume_workspace(
            tmp_path,
            [("Synthesis", "Success"), ("Floorplan", "Incomplete")],
        )
        agent_flow = agent_engine.AgentEngineFlow.__new__(agent_engine.AgentEngineFlow)
        agent_flow.workspace = flow.workspace
        agent_flow.workspace_steps = flow.workspace_steps
        agent_flow.engine_db = flow.engine_db

        monkeypatch.setattr(agent_engine, "run_agent_step", lambda **_kw: True)
        monkeypatch.setattr(agent_flow, "check_step_result", lambda **_kw: True)

        result = agent_flow.run_step(agent_flow.workspace_steps[1], rerun=False)
        assert result == StateEnum.Success

        persisted = json.loads((tmp_path / "home" / "flow.json").read_text())
        assert persisted["steps"][1]["state"] == StateEnum.Success.value
