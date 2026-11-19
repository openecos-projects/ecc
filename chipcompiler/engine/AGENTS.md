# chipcompiler.engine

Scope: running flows — step scheduling and workers, reruns, signoff, snapshots, and
operations on whole workspaces.

## Layout

- Subpackages: `flow/` (the flow runner), `step/` (executing one step), `snapshot/` (the
  Engineering Snapshot), `signoff/`, `workspace/` (operations on whole workspaces). A new
  module goes into the package of its concept, never beside them as a prefixed sibling.

## Imports

- May import `data`, `project`, `tools`, `rtl2gds` and `params`. Don't add imports of
  `chipcompiler.cli`.
- Native ECC initialization stays in worker-side call sites (enforced by a formal test).
- `engine/__init__.py` re-exports the API the CLI and the Agent use. Subpackage
  `__init__.py` files re-export nothing; add public names to `engine/__init__.py`.

## Tests

Under `test/engine/`, named `test_<package>_<module>.py`; basenames must be unique across
`test/`.
