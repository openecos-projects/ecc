# chipcompiler.data

Scope: persisted design and workspace data — models, file formats, and pure policies over
them. No tool execution, subprocesses or CLI output.

## Layout

- Subpackages: `flow/` (step order and the flow ledger), `workspace/` (the Workspace model and
  the files it owns), `step/` (step directories, metrics, results), `handshake/` (req/rsp
  between the flow and a step), `config_params/`, `foundation/`.
- A top-level module is a concept that needs only one module. The existing prefixed groups
  (`parameter*`, `param_keys`, `step_*`) are covered by the root Module Layout rule.

## Imports

- Never import `chipcompiler.engine`, `cli`, `project` or `analysis`, not even inside a
  function.
- Import `tools`, `rtl2gds` and `params` only inside functions.
- Importing any `chipcompiler.data` module loads `workspace/`. CLI startup-path modules must
  not import `chipcompiler.data` at module level.
- A subpackage `__init__.py` re-exports only when that cannot create an import cycle.

## Tests

Under `test/data/`. Test file basenames must be unique across `test/` (prepend import mode):
name them `test_<package>_<module>.py`, or use a test directory of the package's own.
