# Experience normalization development contract

## Scope and implementation status

Implemented: `ecc experience normalize`, Python API `normalize(stores, output)`,
multi-store provenance, exact-case deduplication, conservative configuration groups,
positive/negative/incomplete/quarantined selections, and JSON/Markdown reports.
The implementation uses generic design evidence; ICS55 is a supported process,
and no private benchmark names, layouts, or design inventory define behavior.

Store merging is metadata-only. Source cases, evidence, active workloads, system
ECC installation, and CI workflows remain outside this command's write scope.
Normalization does not publish releases, train models, or apply tuning parameters.

## CLI and API

```bash
ecc experience normalize --store store-a --store store-b --output reports/normalized --json
```

`ecc_experience.api.normalize(stores: Sequence[str | Path], output: str | Path) -> dict`
returns one report. The CLI wraps it in the standard list-of-records envelope with
`experience=normalize`; it supports the existing `--plain` and `--json` conventions.
No project configuration is required. The source list cannot be empty. Duplicate
resolved store roots are scanned once; output must be a new directory outside all
source stores, including paths reached through symlinked parent directories.

## Persisted schema

`normalized-manifest.json` uses schema `ecc-experience-normalized-manifest/1`:

| Field | Contract |
| --- | --- |
| `manifest_id` | Digest of the complete report before adding the ID and output path; equal scan results have equal IDs |
| `status`, `exit_code` | Overall quality, including failures from every source |
| `counts` | Source observations, exact duplicates, unique cases, groups, selections and errors |
| `stores` | Source root, initial case count, detected concurrent changes |
| `cases` | One row per readable case ID, selected representative, configuration identity and all source provenance |
| `configuration_groups` | Stable key, completeness flag, missing identity fields, case IDs and source-observation count |
| `selections` | Explicit positive, negative, QoR-missing, other and per-source quarantine references |
| `errors` | Store/case read failures; successful cases remain visible |
| `limitations` | Verification, concurrency, resource and downstream-consumer boundaries |

Only non-passing verification findings are expanded; `finding_counts` also counts
successful checks. Every source records its workspace/attempt/revision, capture
time, original case path, verification and stored integrity. The report stores
local references and may contain private configuration data; keep it in the user's
benchmark/report area. It is not a portable evidence package or a GitHub artifact.

Configuration identity includes the input fingerprint, process fingerprint,
complete parameter dictionary, ordered step names/tools, and attempt-bound runtime
context. Runtime sources and known versions for every flow tool are required.
Missing identities fall back to case ID and are explained in `missing_identity`.
No version or input identity is invented.
Two observed configurations may therefore remain separate even when their
displayed parameters match. This is intentional conservative grouping.

## Selection and failure semantics

Positive selection requires passing verification, successful flow, passing
checklists, ready signoff, finite QoR and an input fingerprint. The captured
workspace specification must be an object. This is an audit candidate filter;
release creation and verification retain their existing independent contracts.

Negative selection requires a blocked/failed flow, checklist or signoff, with no
verification failures and no unknown findings except unavailable QoR. An EDA
failure is distinct from corrupt evidence. Neither selection proves parameter
consumption, causal PPA gains, or cross-design generalization.

Each exact duplicate retains source-specific verification. Prefer an eligible
positive source, then an eligible negative source, then the best remaining quality
class, with source path as a deterministic tie-break. A bad source is quarantined
even when a valid source of that case remains usable. `integrity` refers to copied
evidence; live-source freshness also affects `verification`. Do not delete intact
archival copies simply because their live sources changed.

The reader checks the writer lock before/after scanning and compares the case
lists. A detected active or changing store contributes diagnostic rows but no
positive/negative selection. This is a best-effort scan, not a snapshot transaction
or a lock that pauses collectors. Final publication requires stopped writers and
fresh verification. Resource rows retain original observations and scopes; no
aggregate runtime/memory prediction is learned by normalization.

| Exit | Meaning | Report written? |
| --- | --- | --- |
| 0 | All cases satisfy positive selection | Yes |
| 7 | Empty, incomplete, negative or changing observations | Yes |
| 6 | Any invalid evidence or unreadable source | Yes |
| 2 | Invalid normalization arguments | No |
| 21 | Existing output | No; existing contents preserved |

Filesystem errors retain the common CLI I/O error contract. Source order does not
change the manifest ID. Later changes to sources can change verification and the
manifest ID, so the same inputs are not guaranteed to produce the same result at
different times.

## Validation and next stages

### Execution identity collection: implemented

Ordinary enabled `run → recorder → drain` now freezes the same runtime identity
used by campaign/DSE plus selected PDK file digests. The recorder captures runtime
and process before/after an attempt and checks PDK identity at committed steps.
The finished event includes schema `ecc-experience-execution-context/1`, attempt
ID, final snapshot digest, primary runtime/process, `checks`, and before/after
`observations`. Checks are `available`, `changed` or `unknown`; changed/unknown
identities have no usable primary runtime/process fingerprint. No historical
backfill occurs. Existing context-free events remain compatible.

LEC version discovery uses the owning tool resolver and sanitized environment,
with internal key `kepler_formal`; campaign/DSE receive it through their existing
runtime helper. Optional capture failures are recorded as unknown without entering
the flow's commit-failure domain. Disabled recording performs no capture. Probes
run at attempt boundaries, with the existing per-tool version-query timeout; PDK
digest checks occur at boundaries and commits. No recording worker or CI job is
introduced. Resume after a runtime format/version change may require a new campaign
output root because frozen runtime equality is intentionally conservative.

Validation covers recorder/drain/normalize grouping across distinct attempts,
runtime changes, PDK changes restored before finish, failed optional probes through
the engine observer, malformed context, and old outbox compatibility. A fresh gcd
attempt is used for source-CLI smoke; historical stores remain read-only.

The real smoke executes a bounded synthesis stage and a forced synthesis rerun in
an isolated project. Both attempts have complete process/runtime identity and share
one configuration group while retaining distinct case/attempt IDs. After reuse of
the workspace, the older case is quarantined for live-source changes; its stored
metadata is preserved. This validates collection/grouping, not full signoff or a
PPA improvement. Prefer separate derived workspaces per trial when old cases must
remain live-verifiable.

### Normalization validation and follow-up

Unit and CLI coverage exercises duplicate cases, repeated configurations, tool/
input/process/parameter/flow mismatches, missing identities, malformed facts,
negative observations without QoR, legacy sources, copied-evidence corruption,
changed live sources with intact copies, read errors, active writers, concurrent
case publication, empty stores, output collisions and store-overlap rejection.
Real-store smoke tests are read-only and write reports outside the repository.

Next: when benchmark writers finish, rerun verification, inspect quarantined and
incomplete sources, and freeze a new release. Feed that release into the existing
dataset/DSE workflow.
Automatic repair, negative-sample model training and policy promotion remain deferred
until their separate evidence contracts exist.

### Release promotion from a normalized manifest

The normalized manifest can be used as a controlled release input through the
separate promotion command:

```bash
ecc experience release from-manifest \
  --manifest reports/normalized/normalized-manifest.json \
  --store reports/reviewed-release-store \
  --output reports/experience-release.json --json
```

The command validates the manifest identity and provenance references, selects only
`selections.positive`, re-runs case verification against the current source and
stored evidence, and copies eligible cases into a new independent store. It then
uses the existing release creation code, so release IDs, case records, atomic output,
and later `release verify` retain the established contract. The source stores and
manifest are never modified, and the destination must not overlap any source store.

Cases that fail the fresh verification are returned in `excluded` with a reason. If
at least one case remains, the release is created and `selection_status` is
`partial`; the command returns exit 7 so automation cannot silently treat a partial
promotion as complete. If no positive case remains, no release is written and the
command returns 7. Existing output returns 21, malformed or tampered manifests return
2, and source/destination overlap is rejected. Negative, QoR-missing, quarantined,
and other selections are never promoted by this command.
