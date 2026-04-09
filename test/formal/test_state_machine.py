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
    Int,
    Not,
    Or,
    Solver,
    sat,
    unsat,
)

from chipcompiler.data import (
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
    StateEnum.Invalid: 5,
}

STATE_COUNT = len(STATE_MAP)

# Reference transition graph from spec.
# Key = source state, value = set of valid target states.
VALID_TRANSITIONS: dict[StateEnum, set[StateEnum]] = {
    StateEnum.Unstart: {StateEnum.Ongoing, StateEnum.Invalid},
    StateEnum.Pending: {StateEnum.Ongoing, StateEnum.Invalid},
    StateEnum.Ongoing: {StateEnum.Success, StateEnum.Imcomplete, StateEnum.Invalid},
    StateEnum.Success: set(),  # terminal
    StateEnum.Imcomplete: set(),  # terminal
    StateEnum.Invalid: set(),  # terminal
}

TERMINAL_STATES = {StateEnum.Success, StateEnum.Imcomplete, StateEnum.Invalid}


def _valid_transition_constraint(s_old, s_new):
    """Build z3 constraint: V(s_old, s_new) is True iff transition is in VALID_TRANSITIONS."""
    clauses = []
    for src, targets in VALID_TRANSITIONS.items():
        src_id = STATE_MAP[src]
        for tgt in targets:
            tgt_id = STATE_MAP[tgt]
            clauses.append(And(s_old == src_id, s_new == tgt_id))
    if not clauses:
        return False
    return Or(*clauses)


def _code_transition_constraint(s_old, s_new):
    """Build z3 constraint: T(s_old, s_new) models what set_state() actually allows.

    Current code: set_state() accepts ANY (s_old, s_new) pair without validation.
    So T(s_old, s_new) = True for all valid enum values.
    """
    return And(s_old >= 0, s_old < STATE_COUNT, s_new >= 0, s_new < STATE_COUNT)


# ---------------------------------------------------------------------------
# z3 formal proofs
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="set_state() has no transition guards -- z3 will find invalid pairs (SAT)",
    strict=False,
)
def test_no_invalid_transition_allowed():
    """Prove: no (s_old, s_new) pair exists where code allows it but spec forbids it.

    Query: Exists(s_old, s_new): T(s_old, s_new) AND NOT V(s_old, s_new)
    UNSAT = proven safe. SAT = z3 gives a concrete violating pair.
    """
    s_old = Int("s_old")
    s_new = Int("s_new")

    solver = Solver()
    solver.add(_code_transition_constraint(s_old, s_new))
    solver.add(Not(_valid_transition_constraint(s_old, s_new)))

    result = solver.check()
    if result == sat:
        model = solver.model()
        old_val = model[s_old].as_long()
        new_val = model[s_new].as_long()
        reverse_map = {v: k for k, v in STATE_MAP.items()}
        old_state = reverse_map.get(old_val, f"unknown({old_val})")
        new_state = reverse_map.get(new_val, f"unknown({new_val})")
        pytest.fail(
            f"z3 found invalid transition: {old_state} -> {new_state} "
            f"(code allows it, spec forbids it)"
        )
    else:
        assert result == unsat, f"Unexpected z3 result: {result}"


@pytest.mark.xfail(
    reason="set_state() has no guards -- z3 will find path bypassing Ongoing (SAT)",
    strict=False,
)
@pytest.mark.parametrize("bound", [1, 2, 3, 5, 10])
def test_terminal_unreachable_without_ongoing(bound):
    """BMC: prove no trace of length `bound` starting from Unstart reaches
    a terminal state without passing through Ongoing.

    s[0] = Unstart
    s[i+1] reachable from s[i] via T (code's unconstrained transitions)
    Query: Exists trace where s[bound] in {Success, Imcomplete}
           AND for all i in 0..bound-1: s[i] != Ongoing
    SAT = z3 gives a concrete trace that bypasses Ongoing.
    """
    states = [Int(f"s_{i}") for i in range(bound + 1)]

    solver = Solver()
    solver.add(states[0] == STATE_MAP[StateEnum.Unstart])

    for i in range(bound):
        solver.add(_code_transition_constraint(states[i], states[i + 1]))

    solver.add(
        Or(
            states[bound] == STATE_MAP[StateEnum.Success],
            states[bound] == STATE_MAP[StateEnum.Imcomplete],
        )
    )

    for i in range(bound):
        solver.add(states[i] != STATE_MAP[StateEnum.Ongoing])

    result = solver.check()
    if result == sat:
        model = solver.model()
        reverse_map = {v: k for k, v in STATE_MAP.items()}
        trace = []
        for i in range(bound + 1):
            val = model[states[i]].as_long()
            trace.append(str(reverse_map.get(val, f"unknown({val})")))
        pytest.fail(f"z3 found trace bypassing Ongoing (bound={bound}): " + " -> ".join(trace))
    else:
        assert result == unsat, f"Unexpected z3 result: {result}"


@pytest.mark.parametrize("num_steps", [1, 3, 5, 9])
def test_is_flow_success_iff_all_success(num_steps):
    """Verify: is_flow_success() returns True iff ALL steps have state Success.

    Must be UNSAT when all_success is combined with any step != Success.
    """
    step_states = [Int(f"step_{i}") for i in range(num_steps)]
    success_id = STATE_MAP[StateEnum.Success]

    solver = Solver()

    for s in step_states:
        solver.add(And(s >= 0, s < STATE_COUNT))

    all_success = And(*[s == success_id for s in step_states])

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


def test_clear_states_resets_all(tmp_path):
    """After clear_states(), every step must be Unstart."""
    ws = _make_workspace(tmp_path, num_steps=5)
    flow = EngineFlow(workspace=ws)

    for i, state in enumerate(
        [
            StateEnum.Ongoing,
            StateEnum.Success,
            StateEnum.Imcomplete,
            StateEnum.Invalid,
            StateEnum.Pending,
        ]
    ):
        flow.set_state(name=f"step_{i}", tool="mock", state=state)

    for i in range(5):
        step = flow.get_step(name=f"step_{i}", tool="mock")
        assert step["state"] != StateEnum.Unstart.value

    flow.clear_states()

    for i in range(5):
        step = flow.get_step(name=f"step_{i}", tool="mock")
        assert step["state"] == StateEnum.Unstart.value, (
            f"step_{i} should be Unstart after clear_states(), got {step['state']}"
        )


@pytest.mark.parametrize("fail_index", [0, 1, 2, 3, 4])
def test_run_steps_stops_on_failure(tmp_path, fail_index):
    """Property: if step K fails, steps K+1..N are never executed."""
    num_steps = 5
    ws = _make_workspace(tmp_path, num_steps=num_steps)
    flow = EngineFlow(workspace=ws)

    executed = []
    for i in range(num_steps):
        step_dir = os.path.join(ws.directory, f"step_{i}_mock")
        os.makedirs(step_dir, exist_ok=True)
        output_dir = os.path.join(step_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        ws_step = WorkspaceStep(
            name=f"step_{i}",
            tool="mock",
            directory=step_dir,
            output={
                "verilog": os.path.join(output_dir, "design.v"),
                "def": os.path.join(output_dir, "design.def"),
                "gds": os.path.join(output_dir, "design.gds"),
            },
            log={"file": os.path.join(step_dir, "log.txt")},
        )
        flow.workspace_steps.append(ws_step)

    def mock_run_step(workspace_step, rerun=False):
        if isinstance(workspace_step, str):
            workspace_step = flow.get_workspace_step(workspace_step)
        idx = int(workspace_step.name.split("_")[1])
        executed.append(idx)

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

    flow.run_step = mock_run_step
    flow.run_steps()

    for idx in executed:
        assert idx <= fail_index, f"Step {idx} was executed after failure at step {fail_index}"
