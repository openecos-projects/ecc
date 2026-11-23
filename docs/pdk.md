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
  pdk/<pdk.config_variant>/<name>.json   # sparse override, only the fields that differ
```

`chipcompiler.data.workspace.tool_configs.tool_config(configs_dir, name, pdk)`
merges the two: dict values merge recursively, lists and scalars in the
override replace the default outright. A PDK with no matching `pdk/<variant>/`
directory (or no override for a given file) just gets the defaults.

To add a new PDK, point `ECC_PDK_ROOT` at its tree (with a `VERSION` file for
ICS55-shaped releases), and add any `configs/pdk/<variant>/<name>.json`
overrides a tool needs — corner names, routing layers, cell lists, and VT
suffixes are all PDK-specific and belong there, not in `defaults/`.

## Cell-name overrides

`ecc.toml`'s `[pdk.overrides]` table can override any `PDK` dataclass field
(`dont_use`, `tech`, `lefs`, `libs`, `buffers`, `tap_cell`, ...) except
`name`, `version`, and `root`. Relative paths resolve against the project
directory (for paths explicitly configured outside the PDK, like a custom
`sdc`) or the PDK root (for PDK-content paths like `lefs`/`libs`).
