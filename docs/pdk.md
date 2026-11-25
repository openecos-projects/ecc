# PDK selection and configuration

ECC resolves a PDK from a plain directory tree; there is no descriptor file,
registry, or import step.

## Root and release

- `ECC_PDK_ROOT` is the only PDK-root environment variable. A project's
  `[pdk] root` (or `--pdk-root`/`pdk_root` parameter where accepted) takes
  precedence over it; if neither is set, ECC falls back to the repository's
  bundled `pdk/icsprout55-pdk` tree.
- ICS55 reads `<root>/VERSION`: a missing file means `v1`; the file must
  otherwise contain exactly `ics55-v1` or `ics55-v2`, and any other value is a
  hard error. `PDK.config_variant` is `f"{name}-{version}"` (e.g. `ics55-v2`).
- An existing workspace that never persisted a `[pdk] root` hard-errors on
  re-run (`pdk_root_not_persisted`) instead of silently re-resolving against
  whatever `ECC_PDK_ROOT` happens to be set to; rerun with `ecc run
  --overwrite` to pin the resolved root into the workspace.

## Point-tool configs

Each point tool owns its own config tree instead of a shared profile:

```
chipcompiler/tools/<tool>/configs/
  defaults/<name>.json          # complete, PDK-neutral
  pdk/<pdk.config_variant>/<name>.json   # sparse override, shipped with ECC
<pdk root>/ecc-configs/<tool>/<name>.json   # sparse override, shipped with the PDK
```

`chipcompiler.data.workspace.tool_configs.tool_config(configs_dir, name, pdk)`
layers them in that order: dict values merge recursively, lists and scalars in
an override replace what is under them. Any layer may be absent; a PDK with
neither override just gets the defaults.

For IO-cell floorplans, the PDN uses an additional `io_cell/<name>.json`
override within each PDK layer. The order is shipped common, shipped
`io_cell`, PDK-root common, then PDK-root `io_cell`. Both ICS55 profiles use
this to extend the core mesh through T4M2/RDL. PDK-root mesh overrides and
explicit project/workspace parameters still take precedence; other PDKs do
not inherit these layers. Switching back to IO-pin mode restores the core
defaults without replacing an explicitly configured or imported custom mesh.

Corner names, routing layers, cell lists and VT suffixes are all PDK-specific
and belong in an override, never in `defaults/`.

Both ICS55 releases route signals from `MET2` up. `MET1` carries the
standard-cell pins, the cells' own internal metal and the row power rails, so
a bottom routing layer of `MET1` shorts signal wires into the rails and into
cell interiors; DreamPlace's global router also refuses the first metal layer
outright and reports every net that needs it as unrouted. Keep
`RT.-bottom_routing_layer`, `LayerSettings.routing_layer_1st` and
`gpugr_bottom_routing_layer` above the rail layer named by
`floorplan_ecc.json`.

Adding a *new ICS55 release* takes two edits in `chipcompiler/data/pdk.py`,
because the marker allowlist is closed by design:

1. accept the new marker in `_ics55_release()`;
2. add a `_PDK_ICS55_V<n>()` factory with that release's paths and cell names,
   and dispatch to it from `PDK_ICS55()`.

Everything else that differs belongs in that release's `configs/pdk/<variant>/`
overrides, and only there: parameters outrank the tool-config layers, so a copy
kept as a parameter default would override a PDK supplying its own
`ecc-configs/`.

## Bringing your own PDK

A PDK ECC has no built-in entry for needs no registration: set `[pdk] name` to
any string and `[pdk] root` to its tree. `get_pdk()` returns an empty `PDK`
whose `config_variant` is `""`, so every tool starts from the PDK-neutral
`defaults/` and inherits nothing from ICS55. Fill it in from two places:

- `[pdk.overrides]` in `ecc.toml` for the `PDK` fields below — which LEFs and
  Liberty files to read, buffer and tap cell names, `dont_use`, latch masters;
- `<pdk root>/ecc-configs/<tool>/<name>.json` for point-tool settings, so the
  PDK carries them instead of every project repeating them. Corner names are
  arbitrary strings, so a PDK with `SLOW`/`FAST` corners writes exactly that
  into `ecc-configs/ecc/sta_ecc.json`.

The defaults configure no corners at all, so nothing of ICS55's is assumed
silently: generated timing constraints need a `TYP`/`TYPICAL` scenario and
raise an error naming `config_overrides.sta.signoff` when none exists.
Per-project one-offs still belong in `config_overrides`.

## Cell-name overrides

`ecc.toml`'s `[pdk.overrides]` table can override any `PDK` dataclass field
(`dont_use`, `tech`, `lefs`, `libs`, `buffers`, `tap_cell`, ...) except
`name`, `version`, and `root`. Relative paths resolve against the project
directory (for paths explicitly configured outside the PDK, like a custom
`sdc`) or the PDK root (for PDK-content paths like `lefs`/`libs`).
