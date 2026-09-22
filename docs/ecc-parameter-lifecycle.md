# ECC Parameter Lifecycle

This document is a maintainer- and integration-facing semantic contract for
ECC workspace behavior. It explains how parameter values travel from
declaration to a running step and how persisted state is protected. It is not
a user command reference. For commands and file fields, see the
[CLI Config Reference](../chipcompiler/docs/ecc-config-ref.en.md) and
[CLI User Guide](../chipcompiler/docs/ecc-user-guide.en.md).

## Priority matrix

When a **fresh** workspace is created (`ecc run`, `ecc workspace refresh`),
one value per key wins through this precedence (highest first):

| Layer | Source | Applies |
| --- | --- | --- |
| 1 | `ecc run --set key=value` (repeatable) | fresh runs only |
| 2 | `ecc.toml` `[params.*]` | fresh runs only |
| 3 | `project.json` `base_design.parameters` merged with the selected workspace entry's `parameter_patch` (manifest base layer) | manifest projects |
| 4 | schema defaults (`chipcompiler/data/config_params/`, legacy registry templates) | always |

The manifest base layer is a floor, not an override: `ecc.toml` and `--set`
values are merged over it, so a declared base value loses to any higher
layer and wins only over the schema default.

An **existing** workspace reuses its persisted `home/params.toml` and never
re-resolves the matrix:

- `--set` is rejected with `set_requires_fresh_run`;
- `ecc.toml` `[params]` is ignored, with a `params_ignored_on_existing_run`
  warning that discloses `ecc param set --workspace` fix commands for the
  parameters whose `ecc.toml` values differ from the workspace's current
  values;
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
- **GUI runs**: `workspace.open` performs no config refresh. The derived
  configs are refreshed when parameters are saved through the GUI
  (`workspace.step_configuration.update` / `workspace.configuration.update`),
  and before a run whenever the flow holds stale steps, so a GUI session and
  a CLI session converge on the same `config/*.json` for the same
  `home/params.toml`.

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
workspace open. A `params.toml` or `flow.json` declaring a version newer than
supported raises `unsupported_schema_version` with the file path and version —
never a silent parse. An `engineering-snapshot.json` that does not match a
supported shape instead raises `EngineeringSnapshotError`
(`invalid Engineering Snapshot: <path>`) without a version number; v2 and v3
both load natively, and the v2→v3 migration stays registered for discovery
only — an explicit write-only seam, not applied by the load chain.

## Engineering Snapshot payload bounds

`home/engineering-snapshot.json` is a bounded index, not a container for full
EDA reports. `build_workspace_analysis()` keeps artifact metadata for every
declared analysis file, but only embeds a JSON body when both limits allow it:

| Boundary | Limit | Oversize behavior |
| --- | ---: | --- |
| One analysis or LEC JSON body | 256 KiB | `status: oversized`, `data: null`, artifact reference retained |
| All embedded analysis bodies | 2 MiB | later bodies use `ANALYSIS_INLINE_BUDGET_EXCEEDED` |
| Signoff checklist body | 1 MiB | checklist and signoff projections become unavailable |
| Serialized Engineering Snapshot | 16 MiB | write fails with `EngineeringSnapshotError`; the previous atomic file remains |

The unavailable analysis-file contract is
`{artifactId, status: "oversized", reasonCode, data: null}`. Studio must accept
that status while continuing to expose `flow` and the remaining valid Snapshot
sections. Tests must cover the per-file limit, cumulative analysis budget,
final write limit, and Studio validation. Do not raise the Studio read limit to
accommodate a report; keep the report as an artifact and its body out of the
Snapshot.

STA corner detail discovery is independent of the aggregate
`sta_timing_issues.json` body. ECC indexes at most 32 deterministic
`feature/<process>/<rc>/qor_summary.json` and `timing_paths.json` pairs as
verified artifacts, even when the aggregate analysis body is oversized. Studio
uses the artifact ID to read and validate one selected corner on demand; file
references and report bodies remain outside the renderer-facing Snapshot
projection.
