# CLI Config Parameters Design

## Status

Approved design. This document describes the implementation boundary for exposing
ECC tool configuration through the existing `ecc param` CLI and `ecc.toml`.

## Goal

Expose every intentional, user-tunable tool configuration field as a typed CLI
parameter. Parameters are persistent project defaults in `ecc.toml` and can be
overridden for one new run with `ecc run --set key=value`.

The initial reference is `gcd/runs/3/config`, which contains these workspace
configurations: db, CTS, floorplan, DreamPlace, routing, filler, RCX, STA, and
DRC. DRC has no fields. The other files contain roughly 239 scalar values,
including PDK-derived and workspace-runtime values.

## Non-Goals

- Do not allow workspace input, output, temporary, or generated-artifact paths
  to be modified through `ecc param`.
- Do not introduce an independent `ecc config set` command or a second project
  configuration language.
- Do not synthesize a registry from JSON templates at runtime. Every exposed
  field is deliberately reviewed and declared in Python.
- Do not change the behavior or spelling of the existing public parameter keys.

## User Interface

All tool configuration uses the existing commands:

```bash
ecc param set cts.skew_bound 0.05
ecc param set cts.routing_layer '[4, 5]'
ecc param set floorplan.die_builder.margin.left_micron 4.0
ecc param set pdk.tech prtech/techLEF/N551P6M_ecos.lef
ecc param show cts.skew_bound
ecc param list --step cts
ecc param list --all
ecc param unset cts.skew_bound

ecc run --run-id cts-exp --set cts.max_buf_tran=0.4
```

Scalars retain the declared schema type. Lists and object-valued fields use a
JSON literal on the command line. Lists replace the entire configured list;
there is no index-level array editing command.

Persistent fields retain the existing TOML root:

```toml
[params.cts]
max_fanout = 16
skew_bound = "0.05"
routing_layer = [4, 5]

[params.floorplan.die_builder.margin]
left_micron = 4.0
right_micron = 4.0

[pdk.overrides]
tech = "prtech/techLEF/N551P6M_ecos.lef"
```

The TOML reader and writer must recursively flatten and materialize parameter
paths. TOML keys that contain a leading dash remain quoted, for example:

```toml
[params.route.RT]
"-top_routing_layer" = "MET5"
```

## Registry Layout

Create `chipcompiler/cli/project/config_params/` with one reviewed module per
configuration owner:

```text
common.py       # ParamSchema extensions and target types
db.py
cts.py
floorplan.py
dreamplace.py
route.py
filler.py
rcx.py
sta.py
__init__.py     # aggregate schemas and validate unique coverage
```

`params.py` keeps parsing, TOML editing, resolution, and command-line glue. It
imports the aggregate registry. Existing parameter declarations move to the
module that owns their target so a field has exactly one declaration. The
registry remains a manually maintained, explicit source of truth.

Extend `ParamSchema` with a target discriminator:

- `parameter_target`: the existing legacy `parameters.json` mapping used by
  semantic settings such as `design.frequency_mhz` and `cts.max_fanout`.
- `config_target`: a config key such as `cts` or `dreamplace` plus an exact JSON
  path tuple such as `("skew_bound",)` or
  `("die_builder", "margin", "left_micron")`.
- `pdk_target`: a PDK field for allowed PDK paths. This writes the appropriate
  `[pdk]` or `[pdk.overrides]` TOML location, not `[params]`.

Each schema also declares its CLI type, default, description, valid range or
enumeration where meaningful, owning step, and target. Complex values use a
`json` schema type and must decode to the declared JSON shape.

## Protected Paths And PDK Paths

Only static tool settings receive `config_target` schemas. The aggregate module
maintains an explicit protected-path manifest with a reason for each excluded
field.

Protected fields include all workspace-owned paths, including `db.INPUT.def_path`,
`db.INPUT.verilog_path`, `db.OUTPUT.output_dir_path`, DreamPlace `def_input`,
`verilog_input`, `result_dir`, and step temporary directories. Mixed structures
containing workspace paths are protected as a whole unless they are split into
safe, independently meaningful fields.

PDK paths remain configurable through PDK targets. `ecc pdk set-root` remains
the root-specific command; `ecc param set pdk.<field> VALUE` writes permitted
override fields such as `tech`, `lefs`, `libs`, `sdc`, `spef`, and
`mapping_file` into `[pdk.overrides]`. Their existing relative-path resolution
and filesystem validation remain authoritative. Workspace paths are never
accepted as PDK path aliases.

PDK-derived non-path values, such as CTS `buffer_type`, are normal tool
configuration fields. A user parameter is applied after the PDK default and
therefore intentionally wins when configured.

## Resolution And Persistence

For a project run, configuration is generated in this order:

```text
tool template
-> PDK-derived fields
-> legacy semantic parameter mappings
-> config-target parameter mappings
-> step-owned workspace I/O fields
```

`config_target` overrides are copied into `home/parameters.json` under a
dedicated structured `Config Overrides` value when the workspace is created.
`refresh_workspace_config` re-applies that value after PDK and legacy parameter
refreshes. Consequently an existing workspace can be resumed or rerun without
requiring access to its parent `ecc.toml`.

`ecc run --set` uses the same schema validation and applies its values only to
the newly created workspace. It must persist direct config-target overrides in
the same workspace form. Existing `cli-param-overrides.json` remains provenance
for project inspection.

Existing public aliases remain the sole parameter spelling for their field. For
example `cts.max_fanout` stays a legacy semantic parameter and is not duplicated
as a second raw JSON-path parameter.

## Inspection

`ecc config <step> --resolved` remains an unchanged path-inspection command.
Parameter inspection is extended:

- `ecc param show KEY` displays target file/path, effective value, default,
  source, type, validation constraints, and protection status when relevant.
- `ecc param list --step STEP` lists the schemas for one owner.
- `ecc param list --all` lists the complete registry. The default listing stays
  concise by showing the current public parameter set and explicit overrides.
- `ecc param diff` includes both legacy and direct config-target overrides.

## Validation And Errors

The CLI rejects unknown keys, invalid scalar types, malformed JSON literals,
schema range/choice violations, and any protected path. Project configuration
validation reports invalid `[params]` nesting or values before a workspace is
created. PDK targets reuse `get_pdk` validation so nonexistent tech, LEF, and
liberty paths fail before flow execution.

## Tests

Add focused CLI tests for set/show/list/unset, recursive TOML parsing and
writing, one-run `--set`, scalar/list/object value validation, and source
precedence. Add workspace tests proving that direct overrides survive reload
and are reapplied after a configuration refresh.

Each step module has a coverage test against its real tool template. Every
template field must be covered exactly once by a `ParamSchema` or exactly once
by the protected-path manifest. The test fails when a tool template changes,
forcing an explicit review and avoiding silent registry drift.

## Documentation

Update the CLI user guide and configuration reference with the new command
examples, TOML nesting convention, target/source reporting, protected path
policy, PDK path parameters, and the full generated schema table.
