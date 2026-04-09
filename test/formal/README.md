# Formal Verification Tests

z3-based formal verification of `EngineFlow` invariants. These tests encode production code logic as SMT constraints and use z3 to exhaustively prove properties or find concrete counterexamples.

## How it works

Each test encodes two models:

1. **Code model** -- what `set_state()`, `create_step_workspaces()`, etc. actually allow (derived by reading the source)
2. **Spec model** -- what the code *should* allow (the intended invariant)

z3 checks: "does there exist any input where these two disagree?"

- **UNSAT** = no such input exists, the property is proven for all inputs
- **SAT** = z3 found a concrete counterexample (a bug)

Tests that probe known-missing guards are marked `pytest.xfail(strict=False)`. When production code is hardened, remove the xfail to make them enforcing.

## Test files

### `test_state_machine.py`

Verifies `EngineFlow` state transitions (`StateEnum`).

| Test | Method | Status |
|------|--------|--------|
| `test_no_invalid_transition_allowed` | z3 existential query over all 36 state pairs | XFAIL -- `set_state()` has no guards |
| `test_terminal_unreachable_without_ongoing` | z3 bounded model checking (K=1..10) | XFAIL -- direct `Unstart -> Success` possible |
| `test_is_flow_success_iff_all_success` | z3 tautology check | PASS -- `is_flow_success()` logic is correct |
| `test_clear_states_resets_all` | Real `EngineFlow` on mock workspace | PASS |
| `test_run_steps_stops_on_failure` | Parametrized over fail index 0-4 | PASS -- `run_steps()` stops correctly |

### `test_file_chaining.py`

Verifies `create_step_workspaces()` file chaining invariants. Abstracts file paths to boolean flags (`has_def`, `has_verilog`, `has_gds`).

| Test | Method | Status |
|------|--------|--------|
| `test_output_keys_present_for_all_step_types` | z3 satisfiability + unsatisfiability checks | PASS |
| `test_chain_breaks_on_failure` | z3 existential query over step sequences | XFAIL -- silent skip on failure (flow.py:240) |
| `test_first_step_always_reads_origin` | z3 constraint contradiction | PASS -- proven |
| `test_check_step_result_completeness` | z3 exhaustive check over all `StepEnum` | PASS |
| `test_no_stale_output_propagation` | z3 taint propagation model | XFAIL -- no taint tracking in code |

## Running

```bash
uv run pytest test/formal/ -v
```

## Dependencies

- `z3-solver>=4.12` (dev dependency)

## Known bugs found

These are documented by XFAIL tests with concrete z3 counterexamples:

1. **No transition guards** -- `set_state()` accepts any `(old, new)` pair, including `Success -> Ongoing`
2. **Terminal states reachable without Ongoing** -- `Unstart -> Success` in one step
3. **Silent step skip** -- `create_step_workspaces()` silently continues when `create_step()` returns None, feeding stale data to downstream steps
4. **No taint tracking** -- steps after a failure can "succeed" on stale input from a pre-failure step
5. **"File list" key missing from template** -- yosys builder reads `"File list"` via `dict.get()` but ICS55 template does not define it

## Parameter Pipeline Verification

### `test_param_merge.py`

z3 proofs that `update_parameters()` merge logic is correct:

| Test | Method | Status |
|------|--------|--------|
| `test_scalar_override_wins` | z3 universally quantified over keys | PASS |
| `test_absent_keys_preserved` | z3 universally quantified over keys | PASS |
| `test_list_replaced_not_appended` | z3 universally quantified over keys | PASS |
| `test_new_key_added` | z3 universally quantified over keys | PASS |
| `test_nested_dict_merges_not_replaces` | z3 with fixed key layout | PASS |
| `test_merge_against_real_template_*` | Concrete tests against ICS55 template | PASS |

### `test_param_propagation.py`

Verifies parameters reach tool configs correctly:

| Test | Method | Status |
|------|--------|--------|
| `test_key_spelling_matches_template` | String match against ICS55 template | XFAIL (`"File list"` missing) |
| `test_dead_defaults` | z3 proves config defaults overwritten by builder | PASS (3 dead defaults found) |
| `test_builder_forced_overrides` | z3 proves forced values are immutable | PASS |
| `test_propagation_z3` | z3 proves parameter reaches config field | PASS |

### Dead defaults found

These JSON config defaults are always overwritten by the builder with parameter values:

1. `dreamplace.json: target_density=0.8` -- overwritten with parameter default 0.3
2. `dreamplace.json: routability_opt_flag=0` -- overwritten with parameter default 1
3. `no_default_config_fixfanout.json: max_fanout=32` -- overwritten with parameter default 20
