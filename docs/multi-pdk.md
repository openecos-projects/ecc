# PDK descriptions and project bindings

PDK providers may publish `ecc-pdk.json` containing **process facts only**:
`schema_version: 2`, `family_id`, `release`, `resources`, and
`views`. ICS55 v1, v2 and other processes use exactly this format. Technology
files and timing views are facts; tool configuration and the
selection of cells/views for execution are ECC policy.

ECC owns a separate adaptation schema (`schema_version: 1`): an exact
`description_digest` binding, `profile_revision`, `cells` (selected roles),
`synthesis_libraries`, `tools`, and `parameters`. Native tool configuration
contracts remain owned by their tools; changes are handled in ECC and do not
require a new PDK release. No process name automatically supplies settings.

Imported descriptions and adaptations are stored together as separate objects in
an atomic ECC-managed `configuration.json`, under
`<inventory-directory>/pdk-configurations/<canonical-root-hash>/`. This avoids
partially updating a description without its matching adaptation. Their schemas
and hashes remain independent. Nothing is written into the PDK root.

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
expected SHA-256. ECC atomically rebuilds a missing or damaged file. When the
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
editing PDK files or configurations locked by existing projects. The reviewed
ICS55 profile values and stage settings are recorded below.

## Bundled ICS55 profiles

The profile index maps exact normalized description digests to independent
description and adaptation JSON files. Those files are included in the Python
wheel and frozen CLI; they contain process metadata and policy, not PDK payloads.
Every referenced resource is checked against its SHA-256 before a default is
applied.

| Profile | PDK release | Site and cells | Rail | Detailed routing |
| --- | --- | --- | --- | --- |
| `ics55-v1` | `v1.10.103` | 7T `core7`; H7H/H7R/H7L | 0.16 um | MET2-MET5 |
| `ics55-v2` | `v2-2026.10.28-7d83e6d` | 9T `SC9T_site`; 9THVT/9TSVT/9TLVT | 0.30 um | MET1-MET5 |

The v2 description includes the full 25-resource set, including five GDS
resources. The catalog also recognizes the earlier 20-resource v2 descriptor.
The v1 adaptation is based on the pre-v2 7T configuration; v2 defaults were
checked against the public 9T package. Neither profile changes or writes into
the PDK directory. Both explicitly mark the bundled ICS55 synthetic EM model as
flow-test-only; it is not foundry signoff data.

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
reselected from defaults. Legacy ICS55 root environment aliases remain read
compatibility inputs for older configurations, not process default generators.

## Immutable projects and relocation

Each project writes `pdk.lock.json` at creation, containing the resolved snapshot,
all declared file hashes, and separate `pdk_digest` and `adaptation_digest` values.
The PDK digest excludes ECC policy. An adaptation edit changes its own digest and
the combined execution digest, but does not change the PDK's identity.
Existing projects use their locked adaptation for every workspace, even after
local defaults are edited. Old locks without separate digests remain readable. Workspaces preserve a descriptor and resolved context in
`home/`. Changes to resources or technology overrides fail instead of silently
changing the process. Workspace optimization parameters remain editable.
`ecc pdk library locate` permits moving a package only when content is identical
and carries its ECC-managed description/adaptation to the new root binding;
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
