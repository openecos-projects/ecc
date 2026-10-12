# Plan — Material-based no-clock recognition

## Goal Description

Extend the no-clock CTS skip path so a design is treated as no-clock when **materials** indicate no clock (empty/missing clock port, optional RTL probe), not only when `flow.no_clock=true` is hand-set. Keep fail-closed behavior when a clock is present or when the situation is ambiguous. Do not regress the existing explicit-flag skip policy.

## Acceptance Criteria

- AC-1: Empty clock materials imply effective no-clock
  - Positive Tests (expected to PASS):
    - Workspace/project with empty `clock` / `clock_port` and no conflicting clock config → `resolve_skip_steps` includes CTS; `flow_no_clock`/probe reports no-clock (inferred or explicit)
    - Virtual SDC path still selected when clock name empty (existing #206 behavior)
  - Negative Tests (expected to FAIL):
    - Design with non-empty `clock_port=clk` treated as no-clock solely because CTS is listed in `skip_steps`

- AC-2: Explicit `flow.no_clock` remains authoritative
  - Positive Tests:
    - `no_clock=true` always adds CTS to skip set even if a clock name string is present (document precedence: explicit flag wins)
  - Negative Tests:
    - Clearing materials alone cannot override an explicit `no_clock=false` when a clock port is configured

- AC-3: Clocked designs still require CTS policy
  - Positive Tests:
    - Non-empty clock port → CTS not auto-skipped; `skip_steps` containing CTS without no_clock still raises
  - Negative Tests:
    - Silent CTS omission on a clocked rtl2gds ledger

- AC-4: Ambiguity is fail-closed and observable
  - Positive Tests:
    - CLI/probe distinguishes `no_clock` source: `explicit` vs `inferred` (or equivalent field)
    - Ambiguous RTL/port mismatch surfaces a clear error or requires explicit flag
  - Negative Tests:
    - Guessing no-clock when a clock-like port exists in parameters

- AC-5: Tests and docs cover the recognition path
  - Positive Tests:
    - Unit tests under `test/data` / `test/rtl2gds` for inference helpers and skip policy
    - Short note in existing no-clock docs (examples or development.md) describing materials vs flag
  - Negative Tests:
    - Plan terminology (`AC-`, Milestone) left in product code

## Path Boundaries

### Upper Bound (Maximum Acceptable Scope)

Infer no-clock from parameters + lightweight RTL top-port scan; wire into `resolve_skip_steps` / config validation / CLI probe; tests + minimal docs. Optional: surface inference in `ecc status` / create-project probe.

### Lower Bound (Minimum Acceptable Scope)

Treat empty/missing `clock`/`clock_port` as inferred no-clock for CTS skip (same fold as flag), with explicit `no_clock=true` unchanged; reject CTS-in-skip_steps without effective no-clock; unit tests for empty vs named clock.

### Allowed Choices

- Can use: existing `flow_no_clock`, `resolve_skip_steps`, workspace parameters, CLI effective config, virtual SDC generation
- Cannot use: signoff catalog/`na_when` (other tree); ecc-tools version changes; local API shims; force-push; merging unrelated obs work

## Feasibility Hints and Suggestions

### Conceptual Approach

```text
effective_no_clock =
  explicit flow.no_clock
  OR (not explicit false AND clock_port/clock empty)

resolve_skip_steps(flow) += CTS if effective_no_clock
probe: { no_clock, no_clock_source: explicit|inferred|off }
```

Prefer parameter emptiness over full RTL parse for lower bound; RTL scan only if needed for AC-4 ambiguity.

### Relevant References

- `chipcompiler/rtl2gds/builder.py` — `flow_no_clock`, `resolve_skip_steps`
- `chipcompiler/data/workspace/sdc.py` — virtual clock when clock empty
- `chipcompiler/cli/project/effective_config.py` — `_attach_no_clock`
- `test/data/test_no_clock_config.py`, `test/rtl2gds/test_builder.py`
- Commit `c854efc` on `feat/no-clock-cts`

## Dependencies and Sequence

### Milestones

1. **Infer helper** — pure function: materials + flow dict → effective no-clock + source
2. **Wire skip policy** — `resolve_skip_steps` / validation use effective no-clock
3. **CLI/probe** — expose source; keep create/migrate gates consistent
4. **Tests + docs** — AC-1..AC-5

M1 before M2. M3 can follow M2. M4 with M2.

## Task Breakdown

| Task ID | Description | Target AC | Tag | Depends On |
|---------|-------------|-----------|-----|------------|
| t1 | Add `effective_no_clock` / source helper | AC-1, AC-2, AC-4 | coding | - |
| t2 | Wire into `resolve_skip_steps` + config validation | AC-1, AC-3 | coding | t1 |
| t3 | CLI/probe + create/migrate consistency | AC-4 | coding | t1, t2 |
| t4 | Unit tests empty/named/explicit/reject CTS skip | AC-1..AC-3, AC-5 | coding | t2 |
| t5 | Doc note materials vs flag | AC-5 | coding | t2 |

## Implementation Notes

- Code must not contain plan terminology (`AC-`, Milestone, Phase).
- Do not weaken CTS skip guard without effective no-clock.
- Prefer small pure helpers over scattering emptiness checks.
- Leave local tool shims stashed; do not commit them in this loop.
