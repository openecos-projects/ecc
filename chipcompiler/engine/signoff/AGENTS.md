# chipcompiler.engine.signoff

Scope: the signoff package of a finished workspace — collecting it, assessing its gates,
exporting and inspecting the archive, and the text design summary.

## Rules

- Signoff reads finished step outputs and the flow ledger; it never runs a tool or rewrites a
  step result.
- `__init__.py` re-exports the collector, its option/result models and the text report; keep
  everything else importable from its own module.
- Tests: `test/engine/test_signoff_<module>.py`.
