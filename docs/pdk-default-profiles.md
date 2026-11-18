# ECC-owned PDK defaults

PDK repositories provide process facts in `ecc-pdk.json` (description schema 2).
ECC owns tool policy in adaptation schema 1. Both versions of ICS55 and custom
processes use these same schemas. ECC never writes configuration into a PDK root.
See `chipcompiler/pdk/documents.py` for the executable document contracts.

## Bundled profiles

`chipcompiler/pdk/profiles/index.json` maps exact, normalized description digests
to a description and a separate adaptation JSON file. The catalog is distributed
in both the Python wheel and frozen CLI. It contains metadata, hashes and policy,
not LEF, Liberty or GDS contents.

| Profile | Qualified package | Standard cells | Floorplan rail | Routing |
| --- | --- | --- | --- | --- |
| `ics55-v1` | `v1.10.103` | 7T, `core7`, H7H/H7R/H7L | 0.16 um | MET2–MET5 |
| `ics55-v2` | `v2-2026.10.28-7d83e6d` | 9T, `SC9T_site`, 9THVT/9TSVT/9TLVT | 0.30 um | detailed MET1–MET5; coarse MET2–MET5 |

V1 policy was recovered from the pre-v2 ICS55 and tool defaults in ECC commit
`5e108b2f^`, with explicit process/VT/primitive mappings for the current tool ABI.
Its description was generated from the installed v1.10.103 resources. V2 policy
uses the stage defaults validated in ECC `ae9b8f2b`, with the complete 25-resource
description (including five GDS resources). The catalog also explicitly accepts
the vendor's earlier 20-resource v2 description. Every bundled resource has a
SHA-256 identity, checked before any default is published.

V2 uses passive filler cells and five STA views (TYP25 plus four MINm40 views),
without SS reports. Both profiles explicitly use the synthetic EMIR model for
flow validation only; it is not a foundry signoff model. Resource availability,
runtime compatibility and physical signoff are separate claims.

## Loading and precedence

1. An explicit PDK root or a selected registered installation identifies the
   resource directory. Its managed configuration takes precedence over the
   vendor description.
2. On first adoption/import of a description without an explicit adaptation,
   ECC looks for an exact catalog match, verifies all resource hashes and copies
   the reviewed defaults into ECC management. It never guesses from `ics55`, a
   directory name or a version prefix.
3. Already managed defaults, including drafts and user edits, are preserved.
   Importing an explicit adaptation also preserves that policy.
4. A missing or unknown description requires configuration through CLI/Studio.
   This rule also applies to ICS55. Explicit selection of a known bundled profile
   can initialize a root without metadata after all its resources are verified.
5. Project creation snapshots process facts, policy and content identities in
   `pdk.lock.json`. Workspace creation and execution resolve that project lock;
   updating managed defaults affects new projects only. Even a broken replacement
   default does not invalidate a sound existing project lock. Resource contents
   must still match the lock.

Managed configuration lives beside the shared PDK inventory, under
`pdk-configurations/<hash-of-canonical-root>/configuration.json`. Set
`ECC_PDK_INVENTORY` to isolate CLI and Studio management for testing. The usual
inventory is under `$XDG_STATE_HOME/ecos-studio/resources/`.

## CLI and Studio

```bash
ecc pdk profiles list
ecc pdk profiles show --profile ics55-v2

# Known v1 without a vendor description; the directory remains read-only.
ecc pdk profiles apply --root /absolute/pdk-v1 --profile ics55-v1

# A recognized v2 description is adopted with defaults on first use.
ecc pdk configure adopt --root /absolute/pdk-v2

# Existing managed policy: inspect its revision, then explicitly replace it.
ecc pdk configure show --root /absolute/pdk-v2
ecc pdk profiles apply --root /absolute/pdk-v2 --profile ics55-v2 \
  --expected-revision REVISION_FROM_SHOW

ecc init /absolute/projects/design-v2 --design-name design \
  --pdk-root /absolute/pdk-v2
```

`apply` requires an exact matching description when one exists, and checks the
resource hashes in either case. Its revision check and write are atomic. It
rejects stale revisions and concurrent creation. If an already registered
installation would acquire a different process identity (for example, additional
GDS entries), apply rejects the change before writing: import a separate PDK root
for the enriched description. Adaptation-only updates retain process identity.

Studio's Configure PDK dialog calls the same `pdk profiles list/show/apply` API.
Replacing managed defaults requires an explicit checkbox and revision. An older
ECC runtime without this API retains the existing manual configuration workflow.
For other processes use `ecc pdk configure init/discover/set/validate/export` or
the dialog; adding a tool adaptation never requires editing the vendor PDK.

## Runtime compatibility

The ECC adaptation's `tools.compatibility` contains ECC and Python distribution
version constraints and, when required, Sizer's explicit-VT contract revision:

```json
{
  "ecc": ">=0.1.0a12,<0.1.0a13",
  "distributions": {
    "ecc-tools-bin": "==0.1.0a13",
    "ecc-dreamplace": "==0.1.0a7"
  },
  "sizer_vt_contract": 1
}
```

ECC compatibility is checked while resolving the adaptation. Execution preflight
checks only selected backends; synthesis does not require Sizer or DreamPlace.
Sizer reports its contract through `--ecc-capabilities`, before OpenROAD startup.
Missing packages, incompatible versions, unavailable probes and malformed probe
responses block the affected stages. Profiles without compatibility requirements
remain readable for backward compatibility. Version checks cannot distinguish
unrelated binaries carrying the same version; preserve build provenance as well.

## Verification and limits

Regression coverage exercises exact matching, changed resources, explicit-policy
precedence, stale revisions, concurrent writers, registered process identity,
old project locks and selected-backend compatibility. Real v1/v2 GCD flows and
packaging checks are recorded in the external `ics55_profiles_20261118` campaign.
They establish support for these packages and this design, not arbitrary PDK
qualification. The separately diagnosed v2 AES MET1 spacing violation remains
an EDA/physical issue; this profile-management change does not waive or fix it.
