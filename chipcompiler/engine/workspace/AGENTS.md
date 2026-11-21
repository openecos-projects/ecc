# chipcompiler.engine.workspace

Scope: operations on a whole workspace — create from a spec, update in place, configuration
edits, reset, derive, backup, archive and delete. Called by the CLI and through the
re-exports in `chipcompiler/engine/__init__.py`. The stored model and file formats belong in
`chipcompiler/data/workspace/`.

## Rules

- Reuse the existing primitives: file transactions from `data/workspace`, the workspace lock
  from `utility`, and engine snapshots; don't write a second mechanism.
- Several modules here are already over 700 lines: put new behavior in a new module.
- `__init__.py` re-exports nothing; public names go in `chipcompiler/engine/__init__.py`.
- Tests: `test/engine/test_workspace_<module>.py`.
