# Formal Verification Tests

z3-based formal verification of the ECC chipcompiler Python codebase. Tests encode production code logic as SMT constraints and use z3 to exhaustively prove properties or find concrete counterexamples.

## How it works

Each test encodes two models:

1. **Code model** -- what the production code actually does (derived by reading the source)
2. **Spec model** -- what the code *should* do (the intended invariant)

z3 checks: "does there exist any input where these two disagree?"

- **UNSAT** = no such input exists, the property is proven for all inputs
- **SAT** = z3 found a concrete counterexample (a bug)

Tests that probe known-missing guards are marked `pytest.xfail(strict=False)`. When production code is hardened, remove the xfail to make them enforcing.

## Test files

### `test_state_machine.py` -- EngineFlow state transitions

| Test | Method | Status |
|------|--------|--------|
| `test_no_invalid_transition_allowed` | z3 existential query over all 36 state pairs | XFAIL -- `set_state()` has no guards |
| `test_terminal_unreachable_without_ongoing` | z3 bounded model checking (K=1..10) | XFAIL -- direct `Unstart -> Success` possible |
| `test_is_flow_success_iff_all_success` | z3 tautology check | PASS |
| `test_clear_states_resets_all` | Real `EngineFlow` on mock workspace | PASS |
| `test_run_steps_stops_on_failure` | Parametrized over fail index 0-4 | PASS |

### `test_file_chaining.py` -- Step output chaining invariants

Abstracts file paths to boolean flags (`has_def`, `has_verilog`, `has_gds`).

| Test | Method | Status |
|------|--------|--------|
| `test_output_keys_present_for_all_step_types` | z3 satisfiability + unsatisfiability checks | PASS |
| `test_chain_breaks_on_failure` | z3 existential query over step sequences | XFAIL -- silent skip on failure (flow.py:240) |
| `test_first_step_always_reads_origin` | z3 constraint contradiction | PASS |
| `test_check_step_result_completeness` | z3 exhaustive check over all `StepEnum` | PASS |
| `test_no_stale_output_propagation` | z3 taint propagation model | XFAIL -- no taint tracking in code |

### `test_param_merge.py` -- Parameter override merge behavior

z3 proofs that `update_parameters()` recursive dict merge is correct.

| Test | Method | Status |
|------|--------|--------|
| `test_scalar_override_wins` | z3 universally quantified over keys | PASS |
| `test_absent_keys_preserved` | z3 universally quantified over keys | PASS |
| `test_list_replaced_not_appended` | z3 universally quantified over keys | PASS |
| `test_new_key_added` | z3 universally quantified over keys | PASS |
| `test_nested_dict_merges_not_replaces` | z3 with fixed key layout | PASS |
| `test_merge_against_real_template_*` | Concrete tests against ICS55 template | PASS |

### `test_param_propagation.py` -- Parameter to tool config pipeline

Verifies parameters reach tool configs correctly through the builder pipeline.

| Test | Method | Status |
|------|--------|--------|
| `test_key_spelling_matches_template` | String match against ICS55 template | XFAIL -- `"File list"` missing from template |
| `test_dead_defaults` | z3 proves config defaults overwritten by builder | PASS (3 dead defaults found) |
| `test_builder_forced_overrides` | z3 proves forced values are immutable | PASS |
| `test_propagation_z3` | z3 proves parameter reaches config field | PASS |

## Running

```bash
uv run pytest test/formal/ -v
```

## SMT-LIB Export

Use `dump_smt2()` from `test.formal` to export any solver's constraints to
SMT-LIB2 format for manual review or use with other solvers (cvc5, yices2):

```python
from z3 import Solver, Int
from test.formal import dump_smt2

solver = Solver()
x = Int("x")
solver.add(x > 0, x < 10)
dump_smt2(solver, "example")  # writes test/formal/smt2/example.smt2
```

Output directory: `test/formal/smt2/` (generated on demand, not committed).

## Dependencies

- `z3-solver>=4.12` (dev dependency)

## Known bugs and findings

Documented by XFAIL tests with concrete z3 counterexamples:

### EngineFlow state machine

1. **No transition guards** -- `set_state()` accepts any `(old, new)` pair, including `Success -> Ongoing`
2. **Terminal states reachable without Ongoing** -- `Unstart -> Success` in one step

### File chaining

3. **Silent step skip** -- `create_step_workspaces()` silently continues when `create_step()` returns None, feeding stale data to downstream steps
4. **No taint tracking** -- steps after a failure can "succeed" on stale input from a pre-failure step

### Parameter pipeline

5. **"File list" key missing from template** -- yosys builder reads `"File list"` via `dict.get()` but ICS55 template does not define it
6. **Dead config defaults** -- these JSON defaults are always overwritten by the builder:
   - `dreamplace.json: target_density=0.8` -- overwritten with parameter default 0.3
   - `dreamplace.json: routability_opt_flag=0` -- overwritten with parameter default 1
   - `no_default_config_fixfanout.json: max_fanout=32` -- overwritten with parameter default 20
7. **Forced overrides** -- DreamPlace builder forces `timing_opt_flag`, `timing_eval_flag`, `with_sta`, `differentiable_timing_obj` to 0 regardless of parameters
