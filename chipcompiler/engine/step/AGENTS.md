# chipcompiler.engine.step

Scope: executing one flow step — running its tool in a one-shot worker process, wiring the
step's inputs along the flow chain, and projecting its outputs.

## Rules

- Native tool initialization happens only worker-side (a formal guard enforces this).
- The worker takes its inputs only from the step's `req.json` and publishes `rsp.json`; it never
  writes the flow ledger.
- The worker module name is part of the process contract (`STEP_WORKER_MODULE`, the packaged
  `--ecc-worker` dispatch in `packaging/run_ecc.py`): rename it only together with those.
- `__init__.py` re-exports nothing.
- Tests: `test/engine/test_step_<module>.py`.
