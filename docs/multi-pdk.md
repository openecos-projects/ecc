# PDK descriptions and project bindings

An ICS55 package publishes a single plain-text `VERSION` file at its root.
Its only line is the generation identifier, `ics55-v1` or `ics55-v2`. `ecc pdk version --root /data/pdk`
can print it before large assets are extracted. ECC selects the bundled profile
for a recognized release. It checks paths and roles before running and permits
updated resources within the same version. For a custom version, use `configure
init` or import a matching configuration. Older packages containing `ecc-pdk.json`
remain supported. ECC owns the resource descriptions and tool adaptations.

ECC owns a separate adaptation schema (`schema_version: 1`): an exact
`description_digest` binding, `profile_revision`, `cells` (selected roles),
`synthesis_libraries`, `tools`, and `parameters`. Native tool configuration
contracts remain owned by their tools; changes are handled in ECC and do not
require a new PDK release. No process name automatically supplies settings.

Imported descriptions and adaptations are stored together as separate objects in
an atomic ECC-managed `configuration.json`, under
`<inventory-directory>/pdk-configurations/<canonical-root-hash>/`. This avoids
partially updating a description without its matching adaptation. Their schemas
and hashes remain independent. The generated STA catalog can be shared in the PDK root.

When a vendor description is missing, including ICS55, CLI/Studio creates a local
description in that same management directory. When the description is present
but no adaptation has been configured, configure the ECC policy before requesting
stages that need it. Version metadata alone does not qualify a physical flow.

## Import or export the two documents

```sh
# Import portable facts and a matching ECC-owned adaptation:
ecc pdk configure import --root /data/pdk \
  --description /data/pdk/ecc-pdk.json --adaptation /configs/ecc-adaptation.json
# Copy the vendor description into ECC management (idempotent):
ecc pdk configure adopt --root /data/pdk
# Separate publication outputs; only the first belongs in a PDK repository:
ecc pdk configure export-description --root /data/pdk > /tmp/ecc-pdk.json
ecc pdk configure export-adaptation --root /data/pdk > /tmp/ecc-adaptation.json
```

The old combined schema-version-1 descriptor remains an import/migration input.
Import/adopt splits it without changing values or rewriting the original file.
CLI project creation and Studio import adopt it into ECC management. Existing
project/workspace snapshots retain their version-one resolved representation;
that internal execution format is not the format for new PDK publications.

## Author and inspect ECC-managed configuration

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

`show` returns both documents, their digests, source path, an editor projection
(`descriptor`) and a revision for compare-and-swap edits. `set` edits this
projection and writes the separated documents atomically. `schema` includes
`x-pdk-description-schema` and `x-ecc-adaptation-schema`, and labels each editor
field by owner. `--output` selects an explicit ECC configuration path outside the
PDK; import that configuration before using it through an inventory default.

The JSON schema is the executable format contract. `resources` uses paths relative
to the package root, optional SHA-256 checksums and explicit roles. Paths escaping
the package, including symlinks, are rejected. `views` and `synthesis_libraries`
reference Liberty resource IDs. `cells` supplies site and standard-cell roles.
ECC derives ICS55 sizing candidates from the standard-cell LEFs selected by the exact
bundled profile. Import and workspace refresh verify `<PDK_ROOT>/cell_catalog.tsv` against its
generated cell table. ECC atomically rebuilds a missing or damaged file. When the
installation is read-only and needs a new table, ECC uses
`pdk-catalogs/<table-sha256>/cell_catalog.tsv` beside the PDK inventory. Each workspace records the absolute path in
`STA.-cell_catalog`. Older descriptors and custom PDKs with explicit cell lists
are supported. Unclassified processes retain singleton families in iSTA.

`tools.configs` in the **ECC adaptation** contains each tool's own configuration (`db`, `Floorplan`, `CTS`,
`route`, `sta`, `sizer`, `RCX`, `dreamplace`, etc.). Electrical/physical settings
belong here rather than in process-name branches in Python/C++. Further typed
namespaces include `timing.default_view` (backend Liberty selection),
`timing.signoff_view` (STA, power and Harden default analysis view), `extraction.backend_id/corners`,
`sizer.vt_groups/hold_view`, `buffering.drive_strengths`, and declarative
`synthesis.primitive_mappings`. Unknown typed settings are rejected. Raw native
configurations remain subject to their backend's validation.

STA path entries must resolve to declared Liberty resources. EMIR prefers the
single declared `em` resource. For flow validation, an ICS55 adaptation may
explicitly select `tools.configs.emir.synthetic_model: "ics55"` (or the public
parameter `emir.synthetic_model`). The bundled fixture has invented electrical
values: its config, log, model report and checklist label it **NOT FOR SIGNOFF**.
It does not register an authentic EM resource or qualify process signoff.
An empty selection disables this fallback; other processes never inherit it.
Macro halo is configured
as `tools.configs.dreamplace.macro_halo_microns` and converted using actual LEF DBU.

Drafts may be incomplete. Validation separates file readiness from backend
support and process qualification; readable files do not certify physical signoff.
A Liberty-only package can create a synthesis workspace with explicit SDC and
`synthesis_libraries`; requesting physical steps reports missing resources.

Version-specific changes apply to the selected ECC-managed adaptation, without
editing PDK files or the recorded configuration of earlier workspaces. The reviewed
ICS55 profile values and stage settings are recorded below.

## Bundled ICS55 profiles

The profile index maps public release numbers and legacy description digests to independent
description and adaptation JSON files. Those files are included in the Python
wheel and frozen CLI; they contain process metadata and policy, not PDK payloads.
Versioned installations check that the referenced files exist.

| Profile | PDK release | Site and cells | Rail | Detailed routing |
| --- | --- | --- | --- | --- |
| `ics55-v1` | `ics55-v1` | 7T `core7`; H7H/H7R/H7L | 0.16 um | MET2-MET5 |
| `ics55-v2` | `ics55-v2` | 9T `SC9T_site`; 9THVT/9TSVT/9TLVT | 0.30 um | MET1-MET5 |

The v2 description includes the full 25-resource set, including five GDS
resources. The catalog also recognizes the earlier 20-resource v2 descriptor.
The v1 adaptation is based on the pre-v2 7T configuration; v2 defaults were
checked against the public 9T package. ECC stores the management configuration outside the PDK. When it prepares STA,
it writes a shared cell catalog under the installed root. Both explicitly mark the bundled ICS55 synthetic EM model as
flow-test-only; it is not foundry signoff data.

Native tool templates live in each tool adapter’s `configs/defaults/` directory.
`configs/pdk/<profile>/` holds the fields that change for that release. Objects
merge recursively, and arrays replace the whole default array. STA resolves
Liberty resource IDs against the description. Workspace creation records the
effective configuration.

## Reviewed ICS55 v2 stage settings

V2 uses 1.8 um rows from `SC9T_site`; do not carry over v1's 1.4 um row height.
The technology LEF supplies row geometry, while the floorplan adaptation reserves
the 0.30 um power rail. Routing tracks retain their physical pitch; no 9/7 scale
factor is applied.

| Stage | Default or decision |
| --- | --- |
| Synthesis | Select the 9T libraries, tie cells, and driver cells from the v2 adaptation. Keep the 1.08 V / 125 C synthesis view. |
| Floorplan | Use `SC9T_site`, LEF-derived row geometry, 0.4 die-util target, and 2 um margins. Reserve a 0.30 um PDN follow-pin rail. |
| Tap and boundary | Keep the reviewed 58 um tap spacing and 30 um boundary rule; exclude pre-route FILLCAP cells from post-route whitespace filling. |
| Placement and legalization | Use the selected v2 site and VT definitions. Retain one-site padding where configured. |
| Placement optimization | Use MET2-MET5 for coarse DreamPlace global routing; keep MET1-MET5 for detailed routing. |
| CTS and timing optimization | Use v2 buffers, libraries, and ordered VT groups. Keep the declared hold view and existing skew/slew limits. |
| Filler | Restrict insertion to the six configured passive v2 filler masters. An empty resolved list blocks insertion rather than selecting all CORE cells. |
| STA | Report TYP and four MIN RC corners; do not add SS reports. |
| EMIR | Prefer a declared EM resource. The synthetic model is an explicitly labeled flow fixture only. |
| Harden and delivery | Register available GDS resources and layer map in the PDK description; registration alone does not establish tapeout qualification. |

The retained AES route checkpoint still has one MET1 pin-access spacing marker:
the BUFX10_9TLVT access via has 0.088 um clearance to an internal obstruction,
below the 0.090 um rule. The router reports it before filler insertion. This is
not a reason to narrow the rail or expand the filler list, and the DRC is not
waived. The updated GCD run completed all enabled flow stages; post-filler DRC
and LVS report zero violations/opens/shorts for that test design. This evidence
checks the profile defaults and flow wiring, not foundry qualification.

ECC CI runs the ICS55 v2 profile only. Its PDK fetch downloads three NLDM
Liberty archives and four GDS archives, then extracts only the 15 Liberty and
five GDS files declared by the ECC v2 profile. Each archive is checked against
`release-assets.sha256`, and each extracted file against `release-files.sha256`.
Unused NLDM views and the much larger CCS archives are not unpacked/downloaded.
This is a verified CI resource subset, not a full PDK release integrity check;
users installing the complete PDK should continue to use
`make -C icsprout55-pdk unzip`.

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
reselected from defaults. `ECC_PDK_ROOT` applies to every process.

## Installation updates and workspace history

Studio records the selected registry release and archive checksum during download.
ECC first reads `VERSION`. Legacy installations with neither `VERSION` nor a vendor description use the bundled resource checksums as a compatibility fallback. Unknown
packages can be configured explicitly. The official ICS55 packages do not need to
provide an ECC-specific file.

The project stores the PDK root in `ecc.toml`. A new workspace uses the current
ECC-managed configuration at that root. Earlier workspaces keep their descriptor
and resolved context in `home/`. Recreate a workspace to use the new configuration.
`ecc pdk set-root` changes the selected installation. `ecc pdk library locate`
relocates an existing installation after checking its content.

To extend v2, export its description and adaptation, add the resources to the
installation and update the configuration. Import the updated configuration with
`ecc pdk configure import --root ROOT --description FILE --expected-revision REV`.
`ecc pdk configure show --root ROOT` supplies the revision. A description-only update for the same release preserves the current tool settings.
Pass `--adaptation FILE` to replace them. Use `configure set` for individual fields.

```sh
ecc pdk clone-with-pdk --source /data/old-project \
  --target /data/new-project --root /data/another-pdk
```

This local command copies RTL and design constraints into a new project with the selected PDK root.
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
