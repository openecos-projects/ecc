# chipcompiler.data.workspace

Scope: the Workspace model and the files a workspace directory owns (configuration,
parameters, crash-safe file transactions, design inputs, timing constraints, step layout).
Operations on a whole workspace (create from spec, update, reset, derive, archive) belong in
`chipcompiler/engine/workspace/`; the flow ledger belongs in `chipcompiler/data/flow/`.

## Rules

- `chipcompiler.data` imports this package on every import: keep module-level imports cheap
  and import heavy dependencies inside functions.
- Never import `chipcompiler.engine`, `cli` or `project`.
- `__init__.py` is already over 800 lines: add new behavior in a module of this package, not
  in `__init__.py`.
- Tests: `test/data/test_workspace_<module>.py`.
