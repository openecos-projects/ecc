# Parameter Lifecycle

How a parameter value travels from declaration to a running step, and what
protects the persisted state along the way. For the command and file
reference see the [CLI Config Reference](../chipcompiler/docs/ecc-config-ref.en.md);
this page is about semantics.

## Priority matrix

When a **fresh** workspace is created (`ecc run`, `ecc workspace refresh`),
one value per key wins through this precedence (highest first):

| Layer | Source | Applies |
| --- | --- | --- |
| 1 | `ecc run --set key=value` (repeatable) | fresh runs only |
| 2 | `ecc.toml` `[params.*]` | fresh runs only |
| 3 | `project.json` `base_design.parameters` (manifest base layer) | manifest projects |
| 4 | schema defaults (`chipcompiler/data/config_params/`, legacy registry templates) | always |

The manifest base layer is a floor, not an override: `ecc.toml` and `--set`
values are merged over it, so a declared base value loses to any higher
layer and wins only over the schema default.

An **existing** workspace reuses its persisted `home/params.toml` and never
re-resolves the matrix:

- `--set` is rejected with `set_requires_fresh_run`;
- `ecc.toml` `[params]` is ignored, with a `params_ignored_on_existing_run`
  warning that discloses per-parameter `ecc param set --workspace` fix commands;
- changes go through `ecc param set/unset --workspace NAME`, which edits
  `home/params.toml` and refreshes the derived `config/*.json`.

`skip_steps` follows the same convergence: an explicit `ecc.toml`
`[flow] skip_steps` (including `[]`) wins over the `project.json`
workspace entry, which wins over the code default `("lec",)`; when both
surfaces declare different policies, `ecc run`/`ecc check` emit a
`skip_steps_shadowed` warning naming the winning source.

## When parameters take effect

- **Fresh run / refresh**: parameters are baked into the workspace at
  creation — `home/params.toml` is written and `config/*.json` are derived
  from it (plus the PDK). The CLI never rewrites those configs afterwards
  outside the derivation paths.
- **Existing run**: the persisted `home/params.toml` is authoritative.
  Direct reruns preserve user parameters by default (`flow.run` /
  `prepare_workspace_for_rerun(preserve_user_inputs=True)`): step re-executed
  regenerates its config inputs from the current parameters, and steps
  downstream are marked unstarted.
- **GUI runs** refresh the derived configs when the workspace opens, so a
  GUI session and a CLI session converge on the same `config/*.json` for the
  same `home/params.toml`.

## CLI vs GUI

| Concern | CLI (`ecc`) | GUI (ECOS Studio) |
| --- | --- | --- |
| Parameter intent for a spec-mode workspace | `home/params.toml` | `engineering-snapshot.json` `workspaceSpec` |
| Snapshot revision | not consulted on the explicit `--workspace` run path | `workspaceRevision` optimistic concurrency |
| Drift detection | `workspace_spec_drift` warning when `params.toml` is newer than the snapshot | snapshot validation (Studio-side) |
| Overwriting edited `config/*.json` | `ecc workspace refresh` refuses with `derived_configs_modified` (listing the files) unless `--force` | derivation refreshes record a hash manifest (`home/config-derived-manifest.json`) |
| Manifest status write-back failure | `manifest_write_back_failed` error record with a repair command; the run result stands | n/a |

The drift and refresh guards are intentionally one-directional tripwires,
not synchronisation: when they fire, prefer `ecc param set --workspace` (or
editing `ecc.toml` and refreshing) over hand-editing generated files.

## schema versioning

Workspace files carry an explicit schema version so newer files fail loudly
instead of parsing silently:

| File | Field | Current version | Notes |
| --- | --- | --- | --- |
| `home/params.toml` | `schema_version` | 1 | absent = version 0 (pre-versioning); version 0 loads through the legacy `parameters.json` migration |
| `home/flow.json` | `schema_version` | 1 | absent = version 0; writers stamp it, reconcile rejects newer versions |
| `home/engineering-snapshot.json` | `schemaVersion` | 2 (production), 3 (prepared) | shared with the GUI; v2→v3 is an explicit write-only seam |

The registry lives in `chipcompiler/data/schema_migrations.py`:
`{file type: {target version: migration}}`, applied in ascending order at
workspace open. A file declaring a version newer than supported raises
`unsupported_schema_version` with the file path and version — never a
silent parse.
