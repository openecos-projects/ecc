# ECC Sweep Reference (parameter-grid experiments)

This reference documents the `ecc sweep` and `ecc explore` command groups: deterministic
parameter-grid experiments over isolated project copies, with evidence-first result
records and an explicit promote step. Command basics also appear in the
[CLI User Guide §11.5](ecc-user-guide.en.md); this document is the full contract for the
plan and results schemas, execution model, and ranking rules.

The implementation lives in
[chipcompiler/cli/commands/experiments.py](https://github.com/openecos-projects/ecc/blob/main/chipcompiler/cli/commands/experiments.py)
and
[chipcompiler/cli/experiments/operations.py](https://github.com/openecos-projects/ecc/blob/main/chipcompiler/cli/experiments/operations.py).

## 1. Model

A **sweep** is a named experiment under `<project>/experiments/<name>/`:

- **create** freezes a plan: the Cartesian product of the given parameter value lists,
  one candidate per combination, in a deterministic order.
- **run** executes candidates one by one, each inside its own isolated copy of the
  project, and records terminal evidence per candidate.
- **compare / rank** are read-only views over the recorded results.
- **promote** records the winning candidate explicitly; nothing is promoted or applied
  automatically.

The first implementation is deterministic and evidence-oriented. It does not provide
automatic optimization, distributed scheduling, multi-SDC sweeps, or automatic
replacement of a baseline workspace.

## 2. Quick start

```bash
ecc sweep create --project /path/to/project --name density \
  --param place.target_density=0.60,0.65 \
  --param cts.max_fanout=16,32
ecc sweep run   --project /path/to/project --name density
ecc sweep compare --project /path/to/project --name density
ecc explore rank   --project /path/to/project --name density
ecc explore promote --project /path/to/project --name density --candidate candidate_0002
```

## 3. On-disk layout

```
<project>/experiments/<name>/
├── sweep.json                  # frozen plan (§5)
├── results.json                # recorded per-candidate evidence (§7)
├── pareto.json                 # written by Pareto promotion (§4.9)
├── winner.json                 # written only after an explicit selection (§4.8–4.9)
└── candidates/
    └── candidate_0001/
        └── project/            # isolated project copy for this candidate
            └── candidate_0001/ # the candidate's workspace inside the copy
```

`sweep list` enumerates exactly those `experiments/*/` directories that contain a
`sweep.json`. Everything a sweep writes stays under `experiments/`; the project manifest,
`ecc.toml`, and any baseline workspace are not modified.

## 4. Commands

All commands accept `--project DIR` (default: the project discovered from the current
directory). `sweep create`, `sweep list`, `sweep show`, `sweep run`, `sweep verify`, and
`explore rank`/`promote` emit JSON. `sweep compare` prints a table by default and JSON
with `--json`; `explore export` prints the selected format unless `--output` is given.
`sweep show` accepts `--json` for CLI compatibility but always prints JSON. Usage or
validation errors exit `2` with the message on stderr.

### 4.1 sweep create

```bash
ecc sweep create --name NAME --param KEY=V1[,V2,...] [--param KEY=... ...] [--project DIR]
```

Freezes the plan. `--param` is repeatable; each takes `KEY=VALUE[,VALUE...]` with at
least one value. Keys are the reviewed `ecc param` keys and values are passed verbatim to
`ecc run --set` at execution time, so the same validation applies (an invalid value fails
the candidate's run, not the create). Creating an existing name, a malformed `--param`,
or an empty parameter set exits `2`.

The emitted plan JSON is also what `sweep show` prints later.

### 4.2 sweep list

```bash
ecc sweep list [--project DIR]
```

Prints a JSON array of the existing sweep names (`["density"]`, or `[]`).

### 4.3 sweep show

```bash
ecc sweep show --name NAME [--project DIR]
```

Prints the stored `sweep.json` (indented, key-sorted). An unknown name exits `2`.

### 4.4 sweep run

```bash
ecc sweep run --name NAME [--max-candidates N] [--project DIR]
```

Executes the plan (see §6) and prints the recorded `results.json`. `--max-candidates N`
(N ≥ 1) bounds the run to the first N candidates in plan order — useful for a smoke pass
over a large grid. The command is resumable: any candidate with a recorded status of
`passed`, `blocked`, `failed`, or `unknown` and an existing workspace directory is
reused without re-running the flow or recollecting evidence, so an interrupted `run`
continues where it stopped.

### 4.5 sweep compare

```bash
ecc sweep compare --name NAME [--json] [--project DIR]
```

Default output is one row per candidate, sorted by the ranking rules in §8:

```
candidate | flow | steps | checklist | violations | qor | exit | parameters
----------|------|-------|-----------|-------------|-----|------|-----------
```

- `flow` is the recorded overall status (`passed / blocked / failed / unknown`);
- `steps` and `checklist` join the per-step `name=status` pairs (omitted as `-` when no
  steps were recorded);
- `violations` and `qor` are the harvested evidence values (`unknown` when absent);
- `exit` is the candidate run's `ecc run` exit code;
- `parameters` is a comma-joined `KEY=VALUE` list.

`--json` prints the same matrix as a JSON array of row objects with the keys
`candidate`, `parameters`, `flow`, `steps`, `checklist`, `violations`, `qor`, `exit_code`.
An empty result set prints only the table header (exit 0).

### 4.6 explore rank

```bash
ecc explore rank --name NAME [--project DIR]
```

Prints the recorded result rows as JSON, sorted by the §8 rules (passed first, then
descending QoR). It is the machine-readable counterpart of `sweep compare` and re-ranks
nothing: the recorded statuses and scores are used as-is.

### 4.7 explore export

```bash
ecc explore export --name NAME [--format json|csv|markdown] [--output PATH] [--project DIR]
```

Exports the same ranked matrix used by `sweep compare`. The default format is `json`;
`csv` and `markdown` emit the fixed columns shown in §4.5. Without `--output`, the
formatted content is written to stdout. With `--output`, the content is written to that
file and stdout receives a one-line JSON status containing `status`, `format`, and the
resolved output path. An unsupported format is a usage error (exit `2`).

### 4.8 explore promote: candidate mode

```bash
ecc explore promote --name NAME --candidate CANDIDATE_ID [--project DIR]
```

Writes `winner.json` — `{"schema_version": 1, "candidate": "<id>", "selected_at": <unix
time>}` — after checking that the candidate exists **and** its recorded status is
`passed`. Anything else (unknown id, not yet run, failed/blocked) exits `2` and writes
nothing. Promotion is a record, not an action: applying the winning parameters to the
real project is an explicit follow-up (`ecc param set` / `ecc run --set`), and promoting
does not mutate the project manifest or the baseline workspace.

Candidate mode checks only that `results.json` contains a matching row for the candidate
and that its recorded `status` is `passed`. It does not re-read the current flow,
checklist, signoff report, metric evidence, or snapshot, so a stale cached row can still
be promoted.

### 4.9 explore promote: Pareto mode

```bash
ecc explore promote --name NAME --pareto \
  --objective ID:UNIT:minimize|maximize [--objective ...] \
  [--candidate CANDIDATE_ID | --weights W1[,W2,...]] [--project DIR]
```

Pareto mode accepts one to three distinct objectives. Each `ID` must belong to the ECC
metric registry (or be `qor_score`), and its unit and direction must match the registry.
After validating the requested objectives and selection arguments, the command writes
`pareto.json` before returning an empty-front exit. It revalidates each candidate against
current committed evidence rather than trusting the cached status:

- the candidate workspace must match the sweep binding and lie inside the project;
- committed parameters must equal the frozen candidate parameters;
- the full flow, checklist, and signoff evidence must currently be `passed`, with zero
  checker violations;
- every objective must have one unambiguous current metric value from verified metric
  evidence, and the engineering snapshot must not change while it is inspected.

Candidates that fail any check are listed under `excluded` with a reason. The report is
written with `front`, `ranking`, `objectives`, `excluded`, `safe_to_apply: false`, and a
selection record.

Without `--candidate` or `--weights`, Pareto mode exports the front only: it writes
`pareto.json`, does not write `winner.json`, and exits `0` when the front is non-empty.
An explicit `--candidate` must be a member of the verified front; `--weights` requires
one finite, non-negative weight per objective with a positive sum and selects the lowest
normalized weighted score with deterministic candidate-ID tie-breaking. Either explicit
selection writes `winner.json` in addition to `pareto.json`. If the verified front is
empty without an explicit selection, the command writes `pareto.json` and exits `7`. An
invalid explicit candidate or weight vector exits `2` before either file is written.

## 5. Plan contract (`sweep.json`)

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Currently `1` |
| `name` | str | Sweep name (the `experiments/<name>/` directory) |
| `parameters` | object | `KEY` → ordered value list, exactly as given to `create` |
| `candidates` | array | One `{id, parameters}` per grid point |
| `created_at` | int | Unix creation time |
| `plan_fingerprint` | str | SHA-256 over the canonical JSON of every field except `created_at` |

Candidate ids are `candidate_0001`… in grid order: the parameter keys are sorted, and
the product enumerates the last key's values fastest (in the example above:
`cts.max_fanout=16 + place.target_density=0.60` → `candidate_0001`).

`plan_fingerprint` lets two plans be compared for equality independent of creation time:
same parameters and same candidate order ⇒ same fingerprint.

## 6. Execution model

For each candidate (in plan order, bounded by `--max-candidates`):

1. If the candidate's project copy does not exist yet, the project is copied to
   `experiments/<name>/candidates/<id>/project/`, excluding `experiments/`, `.git`,
   `*.lock`, and `ws_*` entries. The copied `project.json` is rewritten so
   `root_path` points at the copy and `workspaces` / `runtime_processes` are empty —
   the copy starts as a clean single-workspace project.
2. If a previous result exists for the candidate with any of the four recorded statuses
   and its workspace directory is present, the recorded result is reused and nothing
   runs.
3. Otherwise the candidate runs as a subprocess:
   `ecc run --project <copy> --workspace <copy>/<candidate-id> --set KEY=VALUE …`,
   using the frozen per-candidate parameters.
4. Terminal evidence is collected and appended to `results.json` (§7).

Candidates never share state: each grid point gets its own project copy and its own
workspace, so a failed or blocked candidate cannot contaminate another. Deleting the
candidate directory removes the isolation copy; deleting the whole `experiments/<name>/`
directory removes the sweep.

## 7. Results contract (`results.json`)

One row per executed candidate:

| Field | Meaning |
|---|---|
| `id` / `workspace` | Candidate id and its workspace path inside the copy |
| `parameters` | The frozen per-candidate parameter map |
| `exit_code` | The candidate `ecc run` exit code |
| `status` | `passed / blocked / failed / unknown` (derivation below) |
| `step_statuses` | `[{name, status, checklist}]` from the persisted flow, falling back to `ecc status --json` |
| `qor_score` | First `qor_score` / `score` / `ppa_score` found in the workspace's report JSON files, else `null` |
| `violation_count` | From `ecc signoff check --json` (`violation_count` / `violations` / `error_count`), else `unknown` |
| `signoff_exit_code` / `workspace_status_exit_code` | Exit codes of the two evidence probes |

Status derivation, in priority order:

1. **blocked** — any step status or step checklist status is `blocked`;
2. **failed** — the run exited non-zero, or the signoff probe exited neither `0` nor `7`
   (`7` = required gates not rateable, which is evidence, not failure);
3. **passed** — steps were recorded (or `ecc status` exited 0) and neither of the above;
4. **unknown** — no step evidence at all.

The probes are read-only; `run` never re-runs EDA to fill evidence gaps. QoR and
violation values are whatever the workspace already contains. In particular, signoff
exit `7` alone does not make a candidate non-passed; the step/status rule above still
decides the recorded status.

## 8. Ranking rules

`sweep compare` and `explore rank` sort identically:

1. by status class: `passed` = `success` → 0, `blocked` → 1, `failed` → 2,
   `unknown` → 3;
2. within a class, by `qor_score` descending; a missing score sorts last.

Ties keep the recorded order. The ranking is a view over recorded evidence; it is not a
signoff decision (see the [QoR Reference](ecc-qor-ref.en.md) for what the score means).

## 9. Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (including an empty compare/rank result — an unknown or not-yet-run sweep name compares as empty) |
| 2 | Usage error or validation failure: unknown sweep name, unknown or non-passed candidate in candidate promotion, invalid objective/weight/export settings, duplicate name, or malformed `--param` |
| 6 | `sweep verify` found an integrity failure |
| 7 | Pareto mode produced no verified front |

The sweep commands have no `--plain`; JSON is the machine-readable form. Evidence
packaging and integrity checks for shared results are a separate command group — see
`ecc reproducible` in the [CLI User Guide §11.5](ecc-user-guide.en.md).

`sweep verify` checks only the stored plan fingerprint, unique result membership against
the plan, exact candidate-parameter equality, workspace-directory existence, and missing
results. It does not revalidate step states, QoR values, signoff, checklist contents, or
result field types. Use Pareto promotion for current full-flow evidence revalidation.

## 10. Relationship to other commands

- `ecc param` / `ecc config` — the parameter vocabulary swept by `--param`; see the
  [Configuration Reference](ecc-config-ref.en.md).
- `ecc report project` — the saved-QoR matrix across declared workspaces; sweep
  candidate workspaces live in isolated copies and are not part of the project manifest.
- `ecc reproducible export` — packages a workspace's evidence (including a sweep
  winner's) into a verifiable tar.gz.
