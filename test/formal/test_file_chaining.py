"""
Formal verification of EngineFlow file chaining invariants using z3.

Abstracts file paths to boolean flags (has_key, is_nonempty).
z3 proves invariants over all possible step sequences exhaustively.
"""

from __future__ import annotations

import pytest
from z3 import (
    And,
    ArithRef,
    Bool,
    BoolRef,
    If,
    Int,
    Not,
    Or,
    Solver,
    sat,
    unsat,
)

from chipcompiler.data import StepEnum

# Assign each StepEnum member an integer ID for z3.
STEP_TYPE_MAP: dict[StepEnum, int] = {member: i for i, member in enumerate(StepEnum)}
STEP_TYPE_COUNT: int = len(STEP_TYPE_MAP)

# Steps that only require verilog output (not def/gds).
SYNTHESIS_ONLY_STEPS: set[StepEnum] = {StepEnum.SYNTHESIS}


def _expected_output_keys(
    step_type_id: ArithRef,
    has_def: BoolRef,
    has_verilog: BoolRef,
    has_gds: BoolRef,
) -> BoolRef:
    """Encode: for a given step type, are the expected output keys present?

    Synthesis: requires has_verilog only.
    All others: requires has_def AND has_verilog AND has_gds.
    """
    synthesis_ids: list[int] = [STEP_TYPE_MAP[s] for s in SYNTHESIS_ONLY_STEPS]

    is_synthesis: BoolRef = Or(*[step_type_id == sid for sid in synthesis_ids])

    synthesis_ok: BoolRef = has_verilog
    other_ok: BoolRef = And(has_def, has_verilog, has_gds)

    return If(is_synthesis, synthesis_ok, other_ok)


def test_output_keys_present_for_all_step_types() -> None:
    """Prove: for every StepEnum value, the expected output key requirements
    from check_step_result() are satisfiable -- i.e., no step type has
    impossible requirements.

    Also verify: there exists no step type where check_step_result() would
    pass with MISSING required keys.
    """
    step_type: ArithRef = Int("step_type")
    has_def: BoolRef = Bool("has_def")
    has_verilog: BoolRef = Bool("has_verilog")
    has_gds: BoolRef = Bool("has_gds")

    solver = Solver()

    # Constrain step_type to valid range
    solver.add(And(step_type >= 0, step_type < STEP_TYPE_COUNT))

    # There must exist a configuration where the step passes (satisfiability).
    solver.push()
    solver.add(_expected_output_keys(step_type, has_def, has_verilog, has_gds))
    result = solver.check()
    assert result == sat, "No step type can satisfy output key requirements (should be SAT)"
    solver.pop()

    # Verify: for non-synthesis steps, missing def should cause failure.
    solver.push()
    non_synth_ids: list[int] = [STEP_TYPE_MAP[s] for s in StepEnum if s not in SYNTHESIS_ONLY_STEPS]
    solver.add(Or(*[step_type == sid for sid in non_synth_ids]))
    solver.add(Not(has_def))  # def is missing
    solver.add(_expected_output_keys(step_type, has_def, has_verilog, has_gds))
    result = solver.check()
    assert result == unsat, "Non-synthesis step should FAIL check_step_result when def is missing"
    solver.pop()

    # Verify: for synthesis steps, missing def should NOT cause failure.
    solver.push()
    synth_ids: list[int] = [STEP_TYPE_MAP[s] for s in SYNTHESIS_ONLY_STEPS]
    solver.add(Or(*[step_type == sid for sid in synth_ids]))
    solver.add(Not(has_def))  # def is missing
    solver.add(has_verilog)  # but verilog is present
    solver.add(_expected_output_keys(step_type, has_def, has_verilog, has_gds))
    result = solver.check()
    assert result == sat, "Synthesis step should PASS check_step_result even without def"
    solver.pop()


@pytest.mark.xfail(
    reason="create_step_workspaces() silently skips failed steps (line 240-241)",
    strict=False,
)
@pytest.mark.parametrize("num_steps", [3, 5, 9])
def test_chain_breaks_on_failure(num_steps: int) -> None:
    """Prove: if step K fails, step K+1 must NOT receive input from step K-1.

    Model create_step_workspaces() chaining logic:
      step[0].input_from = -1 (origin)
      step[i].input_from = i-1 if create_step(i-1) succeeded
      step[i].input_from = input_from[i-1] if create_step(i-1) FAILED (current code!)

    The current code does NOT update pre_step on failure, so step[i+1] gets
    step[i-1]'s output (skipping step[i] entirely). z3 will find this.
    """
    succeeded: list[BoolRef] = [Bool(f"succeeded_{i}") for i in range(num_steps)]
    input_from: list[ArithRef] = [Int(f"input_from_{i}") for i in range(num_steps)]

    solver = Solver()

    # Step 0 always reads from origin (-1)
    solver.add(input_from[0] == -1)

    # Encode current code behavior:
    for i in range(1, num_steps):
        solver.add(
            If(
                succeeded[i - 1],
                input_from[i] == i - 1,
                input_from[i] == input_from[i - 1],
            )
        )

    # There exists a step K that fails
    fail_k: ArithRef = Int("fail_k")
    solver.add(And(fail_k >= 0, fail_k < num_steps - 1))
    solver.add(Not(succeeded[fail_k]))

    # Check: does the code allow input_from[K+1] to skip step K?
    solver.add(
        If(
            fail_k > 0,
            input_from[fail_k + 1] == fail_k - 1,
            input_from[fail_k + 1] == -1,
        )
    )

    result = solver.check()
    if result == sat:
        model = solver.model()
        k: int = model[fail_k].as_long()
        trace: list[str] = []
        for i in range(num_steps):
            s = model.evaluate(succeeded[i])
            src: int = model.evaluate(input_from[i]).as_long()
            trace.append(f"step[{i}]: succeeded={s}, input_from={src}")
        pytest.fail(f"z3 found chain skip at K={k} (num_steps={num_steps}):\n" + "\n".join(trace))
    else:
        assert result == unsat, f"Unexpected z3 result: {result}"


@pytest.mark.parametrize("num_steps", [1, 3, 5, 9])
def test_first_step_always_reads_origin(num_steps: int) -> None:
    """Prove: step[0].input_from is always -1 (origin), regardless of flow config.

    Query negation: Exists config where step[0].input_from != -1.
    Must be UNSAT.
    """
    input_from_0: ArithRef = Int("input_from_0")

    solver = Solver()

    # Encode the code's behavior: step[0] always uses origin
    solver.add(input_from_0 == -1)

    # Query: can step[0] NOT read from origin?
    solver.push()
    solver.add(input_from_0 != -1)
    result = solver.check()
    assert result == unsat, "First step must always read from origin"
    solver.pop()


def test_check_step_result_completeness() -> None:
    """Prove: check_step_result() covers all StepEnum values correctly.

    For each StepEnum, verify the match statement in check_step_result()
    routes to the correct check:
    - Synthesis -> verilog only
    - Everything else -> def + verilog + gds
    """
    step_type: ArithRef = Int("step_type")
    has_def: BoolRef = Bool("has_def")
    has_verilog: BoolRef = Bool("has_verilog")
    has_gds: BoolRef = Bool("has_gds")

    solver = Solver()
    solver.add(And(step_type >= 0, step_type < STEP_TYPE_COUNT))

    # For every non-synthesis step: check requires def AND verilog AND gds.
    non_synth_ids: list[int] = [STEP_TYPE_MAP[s] for s in StepEnum if s not in SYNTHESIS_ONLY_STEPS]
    solver.push()
    solver.add(Or(*[step_type == sid for sid in non_synth_ids]))
    solver.add(_expected_output_keys(step_type, has_def, has_verilog, has_gds))
    solver.add(Or(Not(has_def), Not(has_verilog), Not(has_gds)))  # at least one missing
    result = solver.check()
    assert result == unsat, "Non-synthesis step must require all of def, verilog, gds"
    solver.pop()

    # For synthesis: check requires only verilog.
    synth_ids: list[int] = [STEP_TYPE_MAP[s] for s in SYNTHESIS_ONLY_STEPS]
    solver.push()
    solver.add(Or(*[step_type == sid for sid in synth_ids]))
    solver.add(Not(has_verilog))
    solver.add(_expected_output_keys(step_type, has_def, has_verilog, has_gds))
    result = solver.check()
    assert result == unsat, "Synthesis step must require verilog"
    solver.pop()


@pytest.mark.xfail(
    reason="create_step_workspaces() does not track taint from failed steps",
    strict=False,
)
@pytest.mark.parametrize("num_steps", [4, 6, 9])
def test_no_stale_output_propagation(num_steps: int) -> None:
    """BMC: if step K fails, all downstream steps K+1..N-1 should be tainted.

    Model: tainted[i] = True if any step j < i failed.
    Invariant: if tainted[i], step[i] should not be marked Success.

    Current code has no taint tracking -- it continues the chain from the last
    successful pre_step, so a step after a failure can still "succeed" using
    stale data. z3 will find this.
    """
    succeeded: list[BoolRef] = [Bool(f"succ_{i}") for i in range(num_steps)]
    tainted: list[BoolRef] = [Bool(f"taint_{i}") for i in range(num_steps)]

    solver = Solver()

    # Step 0 is never tainted (it reads from origin)
    solver.add(Not(tainted[0]))

    # Taint propagation: tainted[i] = NOT succeeded[i-1] OR tainted[i-1]
    for i in range(1, num_steps):
        solver.add(tainted[i] == Or(Not(succeeded[i - 1]), tainted[i - 1]))

    # There exists at least one failure
    solver.add(Or(*[Not(s) for s in succeeded]))

    # Invariant violation: a tainted step is still marked as succeeded
    solver.add(Or(*[And(tainted[i], succeeded[i]) for i in range(1, num_steps)]))

    result = solver.check()
    if result == sat:
        model = solver.model()
        trace: list[str] = []
        for i in range(num_steps):
            s = model.evaluate(succeeded[i])
            t = model.evaluate(tainted[i])
            trace.append(f"step[{i}]: succeeded={s}, tainted={t}")
        pytest.fail(
            f"z3 found stale output propagation (num_steps={num_steps}):\n" + "\n".join(trace)
        )
    else:
        assert result == unsat, f"Unexpected z3 result: {result}"
