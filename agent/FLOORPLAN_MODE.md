# Isolated Floorplan Modes

`candidate.rerun` accepts the optional `floorplanMode` (`floorplan_mode`) field:

- `die_util`: derive core geometry from utilization and aspect ratio.
- `die_size`: use the candidate's existing fixed width and height, validated as
  finite positive numbers. This does not introduce a new dimension-setting API.
- Omitted: preserve ordinary behavior, or inherit an isolated parent's mode.

An explicit mode requires `targetStep: "Floorplan"`, `endStep: "Harden"`, and
`executionScope: "full_flow"`. The existing context hashes, seed, unique candidate
ID and idempotency key remain required. Unknown modes and mode changes starting
after Floorplan are rejected before an operation starts.

Use `patch: []` with an explicit mode to run an isolated baseline without changing
a parameter. Then use its successful `candidateRootRef` as
`parentCandidateRootRef` for a one-knob candidate. For example, the mode-specific
fields for baseline preparation are:

```json
{
  "targetStep": "Floorplan",
  "endStep": "Harden",
  "executionScope": "full_flow",
  "floorplanMode": "die_util",
  "patch": []
}
```

For a subsequent parameter experiment, omit `floorplanMode` to inherit it and
provide the usual single-knob patch, such as
`[{"knob_id":"floorplan.core_util","value":0.7}]`. An explicit `die_size` on
a new Floorplan candidate switches back without changing its parent. Mode-only
baselines have input-binding and mode evidence, not a fabricated parameter
application receipt.

## Isolation And Evidence

All implementation lives in `agent/`. The native builder, parameters, algorithms
and ordinary workspace behavior are unchanged. The override runs after native
step-config rebuilding, before native execution. Fixed `die.size` remains in
the isolated parameters so switching back is possible; it does not override
the explicit `die_util` selection at the Agent execution boundary.

`analysis/floorplan_mode.v1.json` binds the candidate, mode, previous mode, fixed
dimensions when applicable, patch, context hashes, seed and source config hash.
The candidate manifest binds that file, and the candidate state hash covers it
and the canonical `home/params.toml`. Workspaces without a mode receipt keep
their existing state-hash contract.
Success additionally requires the final config to retain the selected mode.
`candidate.resume` reuses the recorded mode and rejects context or artifact
drift; changing modes requires a new candidate, not a resume override.

The ordinary ECC CLI does not apply this Agent-owned override. Use the Agent
rerun/resume path for these candidates. Existing ECOS GUI callers do not select
a new mode automatically; the caller must explicitly request the baseline.

Compare candidates against a baseline executed in the same mode. Switching a
mode and a knob together cannot isolate the knob's effect. Config/receipt tests
prove execution wiring, not QoR improvement or signoff. Historical fixed-size
baselines and their experiment denominators are not rewritten.
