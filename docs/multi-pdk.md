# PDK descriptions and project bindings

New projects use an explicit, versioned `ecc-pdk.json` at the selected PDK root.
Every family follows the same path, including an ICS55 release without a profile:
configure the package before using it. A family name never supplies technology
files, cells, corners, RC values or EM models.

## Author and inspect a package

```sh
ecc pdk configure init --root /data/pdk --family vendor_node
ecc pdk configure discover --root /data/pdk
ecc pdk configure schema
ecc pdk configure show --root /data/pdk
# Use the revision from show/init for compare-and-swap edits:
ecc pdk configure set --root /data/pdk --field resources \
  --value-json '{"cells":{"path":"lib/cells.lib","role":"liberty"}}' \
  --expected-revision REVISION
ecc pdk configure validate --root /data/pdk
ecc pdk configure resolve --root /data/pdk
```

The JSON schema is the executable format contract. `resources` uses paths relative
to the package root, optional SHA-256 checksums and explicit roles. Paths escaping
the package, including symlinks, are rejected. `views` and `synthesis_libraries`
reference Liberty resource IDs. `cells` supplies site and standard-cell roles.
`cell_catalog` declares candidate family/VT/drive relationships; native STA still
checks pin, function and arc compatibility before grouping cells.

`tools.configs` contains each tool's own configuration (`db`, `Floorplan`, `CTS`,
`route`, `sta`, `sizer`, `RCX`, `dreamplace`, etc.). Electrical/physical settings
belong here rather than in process-name branches in Python/C++. Further typed
namespaces include `timing.default_view` (backend Liberty selection),
`timing.signoff_view` (STA, power and Harden default analysis view), `extraction.backend_id/corners`,
`sizer.vt_groups/hold_view`, `buffering.drive_strengths`, and declarative
`synthesis.primitive_mappings`. Unknown typed settings are rejected. Raw native
configurations remain subject to their backend's validation.

STA path entries must resolve to declared Liberty resources. EMIR consumes the
single declared `em` resource; absent authentic data stays unavailable. The generic
runtime never substitutes the synthetic ICS55 EM model. Macro halo is configured
as `tools.configs.dreamplace.macro_halo_microns` and converted using actual LEF DBU.

Drafts may be incomplete. Validation separates file readiness from backend
support and process qualification; readable files do not certify physical signoff.
A Liberty-only package can create a synthesis workspace with explicit SDC and
`synthesis_libraries`; requesting physical steps reports missing resources.

## Shared library and independent defaults

```sh
ecc pdk library import --root /data/pdk
ecc pdk library list
ecc pdk library default --client ecc --installation INSTALLATION_ID
ecc pdk library default --client studio --installation INSTALLATION_ID
ecc init /data/project --pdk-root /data/pdk
```

Studio and ECC share `${XDG_STATE_HOME:-~/.local/state}/ecos-studio/resources/pdk-inventory.json`.
`ECC_PDK_INVENTORY=/isolated/path/inventory.json` overrides it for tests. Clients
use the same directory lock (`inventory.json.lock`) and atomic file replacement.
A lock remaining after a crash fails closed after ten seconds. Confirm no writer
is running before manually removing an abandoned lock; age alone never authorizes
lock stealing. Studio migrates its old resource manifest on first access.

New-project selection is explicit `--pdk-root`, then `ECC_PDK_ROOT`, then the
chosen client's inventory default. Existing project/workspace bindings are never
reselected from defaults. Legacy ICS55 root environment aliases remain read
compatibility inputs for older configurations, not process default generators.

## Immutable projects and relocation

Each project writes `pdk.lock.json`, containing the normalized descriptor and all
declared file hashes. Workspaces preserve a descriptor and resolved context in
`home/`. Changes to resources or technology overrides fail instead of silently
changing the process. Workspace optimization parameters remain editable.
`ecc pdk library locate` permits moving a package only when content is identical;
`ecc pdk set-root` verifies an existing project lock before changing its path.

```sh
ecc pdk clone-with-pdk --source /data/old-project \
  --target /data/new-project --root /data/another-pdk
```

Clone copies RTL and design constraints into a new project with a new PDK lock.
It accepts RTL sources or one filelist, does not inherit workspaces or physical
results, and does not carry old process-specific parameter overrides. Review the
new project's clock/flow constraints for its new technology. A physically mapped
netlist cannot be retargeted by this command.

## Backend limits and qualification

- Sizer supports 1–3 ordered VT slots, supplied slow/high-threshold to fast/low-
  threshold. IDs and suffixes are package-defined; four or more groups fail
  explicitly. Suffix-based grouping remains a backend constraint. Arbitrary
  Liberty unit combinations have not been newly qualified.
- Candidate buffering accepts an explicit table of two or more strengths. Its
  retained option name `four_strength_table` does not constrain row count.
- Sequential/macros without a proven replacement contract remain singleton
  families. A configured label alone does not prove equivalence.
- The `ics55` extraction adapter remains technology-specific. `native` needs a
  matching model; selecting it is not certification for another foundry.
- ICS55 v2 is the real-process regression target. Synthetic alternate-family,
  two-strength and different-DBU fixtures test contracts, not foundry signoff.
- Xplace receives resolved files; no new foundry qualification is claimed. The
  optional OpenROAD placement bridge and CUDA kernels require separate builds.

## Development without changing system installations

Point the development CLI at local source/native builds and set explicit
`CHIPCOMPILER_ECC_SIZER_ROOT`, `CHIPCOMPILER_OSS_CAD_DIR`, and
`CHIPCOMPILER_KEPLER_FORMAL_ROOT`. Use `--pdk-root` and an isolated
`ECC_PDK_INVENTORY`. Studio accepts `ECOS_ECC_BIN_DIR=/path/to/development/bin`.
Do not run installers or replace `~/.local/bin/ecc` to test this feature.
