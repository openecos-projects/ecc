# chipcompiler.engine.flow

Scope: running a flow — the `EngineFlow` runner that builds, executes and persists the step
chain, the hooks run when a step completes, and the auditable exceptions (skips, waivers)
that let a run pass a step.

## Rules

- `runner.py` is already over 800 lines: put new behavior in a new module of this package, not
  in the runner.
- Tool execution happens only in step workers; the runner schedules and records, it never
  calls a tool in-process (a formal guard enforces this).
- Skips and waivers are recorded in the ledger with their reason; never drop a step silently.
- `__init__.py` re-exports nothing; `EngineFlow` is re-exported from
  `chipcompiler/engine/__init__.py`.
- Tests: `test/engine/test_flow_<module>.py`.
