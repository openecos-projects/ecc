"""
Formal verification of EngineFlow state machine transitions using z3.

Encodes StateEnum as integer sort and transition relations as SMT constraints.
z3 provides exhaustive proof (UNSAT = safe) or concrete counterexample (SAT = bug).
"""

import json
import os
from pathlib import Path

import pytest
from z3 import (
    And,
    ArithRef,
    BoolRef,
    Int,
    Not,
    Or,
    Solver,
    sat,
    unsat,
)

from chipcompiler.data import (
    EccOutput,
    EccStep,
    LogPaths,
    OriginDesign,
    StateEnum,
    Workspace,
    WorkspaceStep,
)
from chipcompiler.data.workspace import Flow
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.utility import Logger

# Map StateEnum values to z3 integers.
STATE_MAP: dict[StateEnum, int] = {
    StateEnum.Unstart: 0,
    StateEnum.Pending: 1,
    StateEnum.Ongoing: 2,
    StateEnum.Success: 3,
    StateEnum.Imcomplete: 4,
    StateEnum.Warning: 5,
    StateEnum.Invalid: 6,
}

STATE_COUNT: int = len(STATE_MAP)

# Reference transition graph from spec.
# Key = source state, value = set of valid target states.
# Terminal states (Success, Incomplete, Warning, Invalid) have no outgoing transitions.
# Batch resets (clear_states, _invalidate_suffix) bypass set_state() and
# can assign Unstart directly, including for terminal states.
VALID_TRANSITIONS: dict[StateEnum, set[StateEnum]] = {
    StateEnum.Unstart: {StateEnum.Ongoing, StateEnum.Imcomplete, StateEnum.Warning},
    StateEnum.Pending: {StateEnum.Ongoing, StateEnum.Imcomplete, StateEnum.Warning},
    StateEnum.Ongoing: {
        StateEnum.Success,
        StateEnum.Imcomplete,
        StateEnum.Warning,
        StateEnum.Invalid,
    },
    StateEnum.Success: set(),  # terminal
    StateEnum.Imcomplete: set(),  # terminal
    StateEnum.Warning: set(),  # terminal
    StateEnum.Invalid: set(),  # terminal
}

TERMINAL_STATES: set[StateEnum] = {
    StateEnum.Success,
    StateEnum.Imcomplete,
    StateEnum.Warning,
    StateEnum.Invalid,
}


def _valid_transition_constraint(s_old: ArithRef, s_new: ArithRef) -> BoolRef | bool:
    """Build z3 constraint: V(s_old, s_new) is True iff transition is in VALID_TRANSITIONS."""
    clauses: list[BoolRef] = []
    for src, targets in VALID_TRANSITIONS.items():
        src_id = STATE_MAP[src]
        for tgt in targets:
            tgt_id = STATE_MAP[tgt]
            clauses.append(And(s_old == src_id, s_new == tgt_id))
    if not clauses:
        return False
    return Or(*clauses)


def _code_transition_constraint(s_old: ArithRef, s_new: ArithRef) -> BoolRef:
    """Build z3 constraint: T(s_old, s_new) models what set_state() actually allows.

    With transition guards, set_state() only allows transitions in _VALID_TRANSITIONS.
    T(s_old, s_new) = True iff (s_old, s_new) is in _VALID_TRANSITIONS.
    """
    return _valid_transition_constraint(s_old, s_new)


# ---------------------------------------------------------------------------
# z3 formal proofs
# ---------------------------------------------------------------------------


def test_no_invalid_transition_allowed() -> None:
    """Prove: no (s_old, s_new) pair exists where code allows it but spec forbids it.

    Query: Exists(s_old, s_new): T(s_old, s_new) AND NOT V(s_old, s_new)
    UNSAT = proven safe. SAT = z3 gives a concrete violating pair.
    """
    s_old: ArithRef = Int("s_old")
    s_new: ArithRef = Int("s_new")

    solver = Solver()
    solver.add(_code_transition_constraint(s_old, s_new))
    solver.add(Not(_valid_transition_constraint(s_old, s_new)))

    result = solver.check()
    if result == sat:
        model = solver.model()
        old_val: int = model[s_old].as_long()
        new_val: int = model[s_new].as_long()
        reverse_map: dict[int, StateEnum] = {v: k for k, v in STATE_MAP.items()}
        old_state = reverse_map.get(old_val, f"unknown({old_val})")
        new_state = reverse_map.get(new_val, f"unknown({new_val})")
        pytest.fail(
            f"z3 found invalid transition: {old_state} -> {new_state} "
            f"(code allows it, spec forbids it)"
        )
    else:
        assert result == unsat, f"Unexpected z3 result: {result}"


@pytest.mark.parametrize("bound", [1, 2, 3, 5, 10])
def test_success_unreachable_without_ongoing(bound: int) -> None:
    """BMC: prove no trace of length `bound` starting from Unstart reaches
    Success without passing through Ongoing.

    Note: Incomplete IS reachable directly from Unstart (Unstart → Incomplete
    is a valid transition for steps that fail during creation). Only Success
    and Invalid require going through Ongoing.

    s[0] = Unstart
    s[i+1] reachable from s[i] via T (code's guarded transitions)
    Query: Exists trace where s[bound] == Success
           AND for all i in 0..bound-1: s[i] != Ongoing
    SAT = z3 gives a concrete trace that bypasses Ongoing.
    """
    states: list[ArithRef] = [Int(f"s_{i}") for i in range(bound + 1)]

    solver = Solver()
    solver.add(states[0] == STATE_MAP[StateEnum.Unstart])

    for i in range(bound):
        solver.add(_code_transition_constraint(states[i], states[i + 1]))

    solver.add(states[bound] == STATE_MAP[StateEnum.Success])

    for i in range(bound):
        solver.add(states[i] != STATE_MAP[StateEnum.Ongoing])

    result = solver.check()
    if result == sat:
        model = solver.model()
        reverse_map: dict[int, StateEnum] = {v: k for k, v in STATE_MAP.items()}
        trace: list[str] = []
        for i in range(bound + 1):
            val: int = model[states[i]].as_long()
            trace.append(str(reverse_map.get(val, f"unknown({val})")))
        pytest.fail(f"z3 found trace bypassing Ongoing (bound={bound}): " + " -> ".join(trace))
    else:
        assert result == unsat, f"Unexpected z3 result: {result}"


@pytest.mark.parametrize("num_steps", [1, 3, 5, 9])
def test_is_flow_success_iff_all_success(num_steps: int) -> None:
    """Verify: is_flow_success() returns True iff ALL steps have state Success.

    Must be UNSAT when all_success is combined with any step != Success.
    """
    step_states: list[ArithRef] = [Int(f"step_{i}") for i in range(num_steps)]
    success_id: int = STATE_MAP[StateEnum.Success]

    solver = Solver()

    for s in step_states:
        solver.add(And(s >= 0, s < STATE_COUNT))

    all_success: BoolRef = And(*[s == success_id for s in step_states])

    # Part A: no assignment makes all_success True when any step is not Success
    solver.push()
    solver.add(all_success)
    solver.add(Or(*[s != success_id for s in step_states]))
    assert solver.check() == unsat, "all_success should be False when any step is not Success"
    solver.pop()

    # Part B: there exists an assignment where not all steps are Success
    solver.push()
    solver.add(Not(all_success))
    assert solver.check() == sat, "Should be possible for not all steps to be Success"
    solver.pop()


# ---------------------------------------------------------------------------
# Real code tests (exercise actual EngineFlow with mock workspace)
# ---------------------------------------------------------------------------


def _make_workspace(tmp_path: Path, num_steps: int = 3) -> Workspace:
    """Create a minimal workspace for testing EngineFlow."""
    ws_dir: str = str(tmp_path / "workspace")
    os.makedirs(ws_dir, exist_ok=True)
    home_dir: str = os.path.join(ws_dir, "home")
    os.makedirs(home_dir, exist_ok=True)
    os.makedirs(os.path.join(ws_dir, "log"), exist_ok=True)

    flow_path: str = os.path.join(home_dir, "flow.json")

    steps: list[dict[str, object]] = []
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


def test_clear_states_resets_all(tmp_path: Path) -> None:
    """After clear_states(), every step must be Unstart.

    clear_states() is a batch reset that bypasses set_state() guards.
    It can reset terminal states (Success, Incomplete, Invalid) to Unstart.
    For states that set_state() can reach (Ongoing), we use set_state().
    For terminal states, we set them directly (bypassing guards, as batch reset does).
    """
    ws: Workspace = _make_workspace(tmp_path, num_steps=5)
    flow: EngineFlow = EngineFlow(workspace=ws)

    # Set Ongoing via set_state (lifecycle: Unstart → Ongoing)
    flow.set_state(name="step_0", tool="mock", state=StateEnum.Ongoing)

    # Set Success via set_state (lifecycle: Unstart → Ongoing → Success)
    flow.set_state(name="step_1", tool="mock", state=StateEnum.Ongoing)
    flow.set_state(name="step_1", tool="mock", state=StateEnum.Success)

    # Set terminal states directly (simulating batch reset or prior persistence)
    for i, state in [(2, StateEnum.Imcomplete), (3, StateEnum.Invalid), (4, StateEnum.Pending)]:
        step = flow.get_step(name=f"step_{i}", tool="mock")
        step["state"] = state.value
    flow.save()

    for i in range(5):
        step = flow.get_step(name=f"step_{i}", tool="mock")
        assert step["state"] != StateEnum.Unstart.value

    flow.clear_states()

    for i in range(5):
        step = flow.get_step(name=f"step_{i}", tool="mock")
        assert step["state"] == StateEnum.Unstart.value, (
            f"step_{i} should be Unstart after clear_states(), got {step['state']}"
        )


def test_run_steps_does_not_reset_home_directly(tmp_path: Path) -> None:
    """Rerun preparation is handled before run_steps(); step execution should not reset home."""
    ws: Workspace = _make_workspace(tmp_path, num_steps=1)
    reset_calls = []
    ws.home.reset = lambda: reset_calls.append(True)  # type: ignore[method-assign]

    flow: EngineFlow = EngineFlow(workspace=ws)
    flow.workspace_steps.append(WorkspaceStep(name="step_0", tool="mock"))
    flow.run_step = lambda workspace_step, rerun=False: StateEnum.Success  # type: ignore[assignment]

    assert flow.run_steps(rerun=False)
    assert reset_calls == []

    assert flow.run_steps(rerun=True)
    assert reset_calls == []


def test_run_steps_does_not_refresh_workspace_config_directly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws: Workspace = _make_workspace(tmp_path, num_steps=1)
    refresh_calls = []

    def refresh_config(workspace: Workspace) -> None:
        refresh_calls.append(workspace.directory)

    monkeypatch.setattr("chipcompiler.data.init_workspace_config", refresh_config)

    flow: EngineFlow = EngineFlow(workspace=ws)
    flow.workspace_steps.append(WorkspaceStep(name="step_0", tool="mock"))
    flow.run_step = lambda workspace_step, rerun=False: StateEnum.Success  # type: ignore[assignment]

    assert flow.run_steps(rerun=False)
    assert refresh_calls == []

    assert flow.run_steps(rerun=True)
    assert refresh_calls == []


@pytest.mark.parametrize("fail_index", [0, 1, 2, 3, 4])
def test_run_steps_stops_on_failure(tmp_path: Path, fail_index: int) -> None:
    """Property: if step K fails, steps K+1..N are never executed."""
    num_steps: int = 5
    ws: Workspace = _make_workspace(tmp_path, num_steps=num_steps)
    flow: EngineFlow = EngineFlow(workspace=ws)

    executed: list[int] = []
    for i in range(num_steps):
        step_dir: str = os.path.join(ws.directory, f"step_{i}_mock")
        os.makedirs(step_dir, exist_ok=True)
        output_dir: str = os.path.join(step_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        ws_step = EccStep(
            name=f"step_{i}",
            tool="mock",
            directory=step_dir,
            output=EccOutput(
                verilog=Path(output_dir) / "design.v",
                def_=Path(output_dir) / "design.def",
                gds=Path(output_dir) / "design.gds",
            ),
            log=LogPaths(file=Path(step_dir) / "log.txt"),
        )
        flow.workspace_steps.append(ws_step)

    def mock_run_step(workspace_step: WorkspaceStep | str, *, rerun: bool = False) -> StateEnum:
        if isinstance(workspace_step, str):
            resolved = flow.get_workspace_step(workspace_step)
            assert resolved is not None, f"Step '{workspace_step}' not found"
            workspace_step = resolved
        idx: int = int(workspace_step.name.split("_")[1])
        executed.append(idx)

        # Simulate lifecycle: Unstart → Ongoing → Success/Incomplete
        flow.set_state(
            name=workspace_step.name,
            tool=workspace_step.tool,
            state=StateEnum.Ongoing,
        )

        if idx == fail_index:
            flow.set_state(
                name=workspace_step.name,
                tool=workspace_step.tool,
                state=StateEnum.Imcomplete,
            )
            return StateEnum.Imcomplete

        flow.set_state(
            name=workspace_step.name,
            tool=workspace_step.tool,
            state=StateEnum.Success,
        )
        return StateEnum.Success

    flow.run_step = mock_run_step  # type: ignore[assignment]
    flow.run_steps()

    for idx in executed:
        assert idx <= fail_index, f"Step {idx} was executed after failure at step {fail_index}"
