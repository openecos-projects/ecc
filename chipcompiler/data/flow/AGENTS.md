# chipcompiler.data.flow

Scope: the step order of a flow and the `home/flow.json` ledger that records it. Pure
computation plus the single ledger writer; no tool execution.

## Rules

- Planning code works only on step names and step policies; it never touches a Workspace or a
  ledger file.
- Exactly one module writes `flow.json`; don't add another writer (a formal guard enforces
  this).
- The ledger input-source rule has one implementation. The engine, signoff and the LEC gates
  call it; don't re-derive it.
- Don't import `chipcompiler.engine`, `cli` or `project`.
- `__init__.py` re-exports nothing: `data/workspace` imports from this package, and this
  package imports `data/workspace/layout`, so re-exports would create a cycle.
- Tests: `test/data/test_flow_<module>.py`.
