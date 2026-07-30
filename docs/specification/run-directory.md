# Configurable Run Directory

## Status

Implemented on branch `emin/support-runs-folder-specify`.

## Motivation

`ecc run` wrote every flow into a hardcoded `runs/default/` under the project
directory. Users want to direct output elsewhere — a named run under `runs/`, a
path outside the project, or a sweep layout like `sweeps/sweep_001/run_004`.

The read side already resolves arbitrary run targets via
`resolve_run_dir(project_dir, run_id)` for `--run-id` on `status`/`log`/`config`
(`cli/inspection/discovery.py`). The write side now resolves through the same
path, and the `SUPPORTED_FLOW_RUNS = {"default"}` gate that rejected any
non-default `[flow] run` is gone.

## QoR is unaffected

QoR output is not a run-root sibling; it is per-step, nested inside each step
directory (`tools/ecc/builder.py`). Every QoR path is derived from
`workspace.directory`; no code reconstructs a QoR path from
`project_dir + "runs/default"`. When the run root moves, the QoR tree moves
with it and its relative structure is unchanged.

## Requirements

R1. A user can set the run directory in `ecc.toml` via `[flow] run`, and
`ecc run` writes the flow there instead of `runs/default`.

R2. `run` accepts three forms, matching what `resolve_run_dir` already
implements for `--run-id`:
- a bare name (`exp1`) → `<project>/runs/exp1`
- a relative path with a separator (`sweeps/s1/r4`) → `<project>/sweeps/s1/r4`
- an absolute path (`/data/runs/x`) → used verbatim

R3. `ecc run` accepts `--run-id`, overriding `[flow] run` for a single
invocation, with the same three forms as R2. Precedence: `--run-id` >
`[flow] run` > `default`.

R4. The write side and read side resolve identically. Resolution is centralized
in `build_context` (`cli/core/invocation.py`), which computes the effective run
for every command from `--run-id` first, then `[flow] run`, then default. After
`ecc run --run-id exp1`, bare `ecc status` with `[flow] run = "exp1"` targets
the same directory.

R5. `--overwrite` deletes only a run directory ECC recognizes (see Overwrite
safety below).

R6. Backward compatibility: with no `[flow] run` and no `--run-id`, behavior is
byte-for-byte identical to before (`runs/default`, run id `None`).

## Design

### Centralized resolution in `build_context`

`resolve_run_dir(project_dir, run_id)` remains the single path resolver.
`build_context` computes the effective run id once for every command:

```python
cli_run_id = command_input.project.run_id
configured = config_run_id(project_dir)   # None | str | InvalidFlowRun
if isinstance(configured, InvalidFlowRun):
    if cli_run_id is None:
        config_error = configured.problem  # strict, see below
    configured = None
run_dir, run_id = resolve_run_dir(
    project_dir, cli_run_id if cli_run_id is not None else configured
)
```

One presence rule governs both the suppression gate and resolution:
`cli_run_id is None`. The `is not None` form preserves the pre-existing
collapse of an empty `--run-id ""` to the default run inside
`resolve_run_dir`; a truthiness-based `cli_run_id or configured` would
reroute `""` to the configured run, and a truthiness-based suppression gate
would refuse `""` with a `config_error` even though it resolves to the
default run.

The resolver also preserves selector presence: an absent selector returns
`(runs/default, None)`, while an explicit empty selector returns
`(runs/default, "")`. The directory and the displayed effective name are
identical in both cases; only the disclosed commands differ (see below).

`config_run_id` (`cli/project/config.py`) is the config-owned reader of
`[flow] run`, applying one canonical rule shared with
`validate_project_config`, so resolution and validation never disagree:

- key absent, `"default"`, or config unreadable (missing, malformed TOML,
  `OSError`, or invalid UTF-8 on read) → `None` (collapse to default)
- present but empty / whitespace-only / leading-trailing whitespace /
  NUL-containing / non-string → `InvalidFlowRun(problem)`
- otherwise → the string value

The `run` handler consumes `ctx.run_dir` / `ctx.run_id` directly; no code path
recomputes `os.path.join(project_dir, "runs", "default")`.

`build_context` parses ecc.toml once (`load_run_config`) and carries the
snapshot on `ctx.config`; `ecc run` and `ecc check` validate that same parse,
so run selection and execution can never read different configurations. The
`ecc config` strictness gate applies the same canonical rule to the snapshot
(`config_run_id_from`). As a side effect, `run`/`check` report
`missing_config` for an unreadable ecc.toml instead of crashing.

### Effective run identity

One identity is used everywhere: `effective_run_name = ctx.run_id or "default"`.
It appears in the run success / `run_exists` / `workspace_failed` /
`flow_failed` records, in the `inspect_cmd` / `log_cmd` disclosure hints, and
in the run progress header (replacing the old `os.path.basename(run_dir)`
label, which mislabeled `sweeps/s1/r4` as `r4`).

Disclosure hints include `--run-id <id>` whenever a selector was explicitly
given — including the empty form, rendered as `--run-id ''` — and stay bare
only when no selector was given at all. An explicit `--run-id ""` therefore
inspects the default run AND produces commands that resolve back to the
default run, instead of silently falling through to a configured
`[flow] run`.

`ecc check` keeps printing `runs/default` for default projects and shows the
configured/resolved directory only for non-default runs: project-relative when
the resolved directory is canonically inside the project (`..foo/run` displays
relatively; a path escaping via `..` or through a symlinked component displays
absolute). The relative form is computed in canonical coordinates —
`relpath(realpath(run_dir), realpath(project_dir))` — so a symlinked
`--project` with an absolute real in-project run still displays
`runs/<name>`, never a `../...` path.

### `ecc run --run-id`

`run_cmd` declares `run_id: RunIdOption = None` exactly like
`status_cmd`/`log_cmd`/`config_cmd` and threads it through the existing
`project_options(project, run_id)` → `ProjectOptions.run_id` channel. `RunInput`
did not gain a duplicate `run_id` field.

### Shape validation replaces the allowlist

`SUPPORTED_FLOW_RUNS` is deleted. `validate_project_config` rejects `[flow] run`
values that cannot name a run directory, using the same canonical rule as
`config_run_id` (the parse stores the rejection on
`ProjectConfig._flow_run_error`). The message shape stays
`unsupported flow.run: <value>`.

When `[flow] run` is present but invalid and no `--run-id` is given, the
inspection commands (`status`/`log`/`config`) fail with a `config_error`
record carrying the reason and exit non-zero, instead of silently falling back
to the default run. An explicit `--run-id` (including the empty form) bypasses
the broken key for `status`/`log`. `ecc config` — project- and step-scoped
alike — always fails on the invalid key: the handler consults the config-owned
rule before choosing a view, independent of the selector, so no config view
can silently succeed on a broken `[flow] run`. `ecc run`/`ecc check` already
report it through full config validation.

### Overwrite safety (R5)

Two independent checks run before any `chmod`/`rmtree`:

1. **Alias refusal** (unconditional, before `run_exists`): a run id that
   resolves to the project directory or the `runs/` container is rejected with
   `error=invalid_run_id`. The comparison checks both the normalized spelling
   (`normpath`, catching `.` / `..` / `runs/default/..`) and the canonical path
   (`realpath`, catching symlink spellings such as a `runs/sneaky -> runs`
   link).
2. **Overwrite guard** (with `--overwrite`, when the target exists): refuse
   with `error=overwrite_refused` ("target is not an ECC run directory") when
   - the target does not resolve canonically where its spelling claims —
     `realpath` is compared against the normalized spelling, anchored at the
     project directory for in-project paths (so a project reached through a
     symlinked parent keeps working, while any symlink in the untrusted tail
     fails the check, including one hidden behind `..` segments, which
     `normpath` would collapse textually but the kernel resolves through the
     link); external or escaping paths must equal their normalized spelling;
   - or the target is not an empty directory and does not contain a real
     (non-symlinked) `home/flow.json` sentinel. A directory that cannot be
     inspected (e.g. no read permission) is refused the same way instead of
     failing with a traceback.

A nonexistent target proceeds (no-op guard), an empty directory proceeds, and
a sentinel-bearing directory proceeds. Refusals leave the target bit-for-bit
untouched: no `chmod` walk and no `rmtree` run. No new marker file is
introduced; `home/flow.json` is what `read_flow_json` already keys on.

A target directory that already exists is never written into: after the
overwrite step the run handler attempts `os.makedirs(run_dir)`, and a
`FileExistsError` stops the run with a `run_exists` record (same shape and
overwrite disclosure as the flow.json check). Ownership is therefore
exclusive — exactly one process ever writes into the target, so when the
owner's `create_workspace` fails (`workspace_failed`), removing the partial
tree can only ever delete its own output, and a concurrent loser stops
before writing instead of racing the winner. A deliberate side effect: a
pre-existing directory without `home/flow.json` (including an empty one) no
longer proceeds without `--overwrite`; the disclosure leads to
`--overwrite`, whose guard allows the empty case and refuses foreign
content.

### Init template

`ecc init` keeps writing `run = "default"` in the generated `[flow]` block — it
documents the key and is the no-op value.

## Decisions (resolved during planning)

- DEC-1: bare inspection follows `[flow] run` when no `--run-id` is given —
  accepted; it is the point of centralizing resolution in `build_context`.
- DEC-2: `[flow] run` may hold absolute or `..`-escaping paths, same rules as
  `--run-id`; no project-local restriction on committed config.
- DEC-3: invalid `[flow] run` strictly blocks inspection commands with a config
  error (no silent fallback to default).
- DEC-6: `--overwrite` refuses non-ECC directories; only nonexistent, empty, or
  `home/flow.json`-bearing targets are deleted.

Non-goals this iteration: `~`/`$VAR` expansion for run paths; CLI-side
`--run-id` shape validation for NUL and other invalid filesystem inputs (only
`[flow] run` is shape-validated). `ecc check` displays the resolved directory
for any valid-shape `[flow] run` — including alias values like `.` or the
absolute project directory that the write side refuses with `invalid_run_id`
— because the alias refusal is a write-side safety guard (DEC-2/DEC-6), not a
config shape rule; read-side display of such aliases is intentional. Changes
under `tools/`, `engine/`, or `data/workspace/`; QoR changes of any kind. The
guard-to-`rmtree` TOCTOU window is accepted under the single-user local-CLI
threat model.

## Files touched

- `cli/project/config.py` — `load_run_config`, `config_run_id_from`,
  `config_run_id`, `InvalidFlowRun`, canonical shape rule, `_flow_run_error`
  on `ProjectConfig`; `SUPPORTED_FLOW_RUNS` deleted.
- `cli/core/invocation.py` — `build_context` parses ecc.toml once, resolves
  the effective run id from the snapshot, and carries `config_error` and the
  snapshot.
- `cli/core/types.py` — `CommandContext.config_error` and `.config`.
- `cli/command_handlers/inspect.py` — status/log fail fast on
  `ctx.config_error`; `config` consults `config_run_id` directly so both
  views reject an invalid `[flow] run` under any selector.
- `cli/inspection/discovery.py` — `resolve_run_dir` preserves selector
  presence (`"" -> (runs/default, "")`).
- `cli/inspection/config_view.py` — project view reports `invalid_config`
  instead of crashing on an unreadable ecc.toml (`OSError` or invalid UTF-8).
- `cli/core/output.py` — `disclosure_cmd` appends `--run-id` on presence
  (`is not None`), quoting the empty form as `''`.
- `cli/command_handlers/project.py` — run handler consumes `ctx.run_dir` +
  effective run name and validates the `ctx.config` snapshot; alias refusal
  and overwrite guard (unreadable targets refused safely); an existing target
  stops with `run_exists`; failed `create_workspace` removes only the
  atomically owned target; `ecc check` run-aware display.
- `cli/commands/project.py` — `--run-id` on `run_cmd`.
- `cli/rendering/progress.py` — progress header labeled by effective run name.
- `docs/specification/cli-design.md` — run-writer paragraph and validation note.

## Testing

- `test/cli/commands/test_run_directory.py` — write targets for all three path
  forms, config-driven runs, precedence, `run_exists`/overwrite records for
  named runs and for the explicit empty selector (generated commands carry
  `--run-id ''`), a write-read symmetry regression: real
  `create_workspace`/`EngineFlow` persist `runs/exp1/home/flow.json` (only
  external step execution stubbed), then bare `ecc status` reads that same
  directory with no test-created artifacts in between, and a single-snapshot
  regression asserting `ecc run` parses ecc.toml exactly once.
- `test/cli/commands/test_overwrite_guard.py` — the alias refusals (textual
  and symlink spellings) and the overwrite guard: foreign non-empty dir,
  symlink target, plain file, empty dir, unreadable dir, symlinked
  `home`/`flow.json`, symlink-redirected targets (ancestor symlink to empty
  and sentinel-bearing dirs, `..` after a symlink component, `..` escape
  through a symlinked project dir), and a default run under a symlinked
  project dir, with refusal-before-mutation assertions on content, modes, and
  zero chmod/rmtree calls; `_canonically_inside` unit tests; recovery
  semantics: an existing target without `--overwrite` stops with `run_exists`
  (foreign content, concurrent winner's partial tree, and empty dir alike,
  with preservation assertions), and a failed `create_workspace` removes the
  atomically owned fresh or guarded-overwritten target.
- `test/cli/commands/conftest.py` — shared `flow_mocks` fixture
  (create_workspace capture + DummyFlow engine) used by the run tests.
- `test/cli/project/test_config_run_id.py` — `config_run_id` returns `None`
  for an unreadable or non-UTF-8 config.
- `test/cli/inspect/test_run_id.py` — config-derived bare inspection for
  status/log/config, `--run-id` override of config, strict `config_error` on
  invalid `[flow] run`, `--run-id` bypass, explicit-empty selector records
  carrying `--run-id ''`, and the unreadable/non-UTF-8 config fallback to the
  default run.
- `test/cli/inspect/test_config_strict.py` — step-scoped
  `ecc config --resolved` rejects empty and non-string `[flow] run` under
  explicit non-empty and empty selectors, with real step artifacts present;
  project view reports `invalid_config` for an unreadable or non-UTF-8
  ecc.toml.
- `test/cli/commands/test_check.py` — shape validation accept/reject matrix
  and `run_dir` display (default/configured/absolute/`..foo`/parent-escaping/
  symlink-escaping).
- `test/cli/inspect/test_config.py` — named run accepted, invalid run rejected
  through `ecc config --resolved`.
- `test/cli/test_typer_cli.py` — `run_cmd` threads `--run-id` via
  `ProjectOptions.run_id`.
- `test/cli/rendering/test_progress.py` — progress header uses the effective
  run name for path-form run ids.
