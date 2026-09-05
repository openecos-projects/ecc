# ECC CLI User Guide (all currently supported commands)

`ecc` is the project-oriented command-line entry point of ECOS Chip Compiler, covering the full RTL-to-GDS flow: project creation, validation, execution, status/log/config inspection, parameter management, signoff, and reporting. This guide is based on the current source tree (v0.1.0-alpha.11); all example outputs are real execution results (run states in the examples are hand-crafted demo data).

- Source code: [chipcompiler/cli/](../chipcompiler/cli/)
- For how to extend the CLI with new commands, see [ecc-cli-dev.en.md](ecc-cli-dev.en.md)
- RPC sidecar protocol: [workspace-cli.md](workspace-cli.md)

## 0. Invocation

### One-shot setup (recommended)

The repository ships an install script, [ecc-cli-setup.sh](ecc-cli-setup.sh) (in this directory): it downloads and installs the ecc CLI, configures PATH, runs an environment self-check, and fills in any missing dependencies — the PDK (icsprout55-pdk + liberty/GDS), Yosys (latest OSS CAD Suite with the slang frontend; LEC reuses that yosys), and Sizer for Timing optimization (the script installs a prebuilt ecc-sizer package when one is available). It is idempotent: re-running skips anything already in place.

```bash
bash ecc-cli-setup.sh                 # install + self-check + fill in dependencies
bash ecc-cli-setup.sh --check-only    # environment check only, installs nothing
bash ecc-cli-setup.sh --force         # force reinstall of the ecc CLI
bash ecc-cli-setup.sh --skip-pdk --skip-tools --skip-sizer   # install only the ecc CLI; the final check fails until required dependencies are ready
bash ecc-cli-setup.sh --no-shell-rc   # do not touch shell rc files (by default a load line is added idempotently)
```

Configuration knobs (override via environment variables; change these when versions/URLs change — no script edits needed):

| Variable | Default | Description |
|---|---|---|
| `ECC_VERSION` | `latest` | ecc release tag (e.g. `v0.1.0-alpha.11`) |
| `ECC_RELEASE_BASE` | Official ecc Releases page | Release page URL (change for a mirror or a different repository) |
| `ECC_ASSET_NAME` | `ecc-cli-linux-x86_64.tar.gz` | Asset name (change if the layout changes) |
| `ECC_CLI_URL` | empty | Full direct URL or local archive path; highest priority |
| `ECC_INSTALL_DIR` | `~/.local/ecc` | Installation directory |
| `ECC_PDK_DIR` | `~/.local/icsprout55-pdk` | PDK directory (repository URL is fixed: https://github.com/openecos-projects/icsprout55-pdk.git) |
| `ECC_OSS_CAD_DIR` | `~/.local/oss-cad-suite` | OSS CAD Suite directory (Yosys) |
| `OSS_CAD_URL` | empty | Full direct URL override for OSS CAD Suite (defaults to the latest release) |
| `OSS_ARCH_PATTERN` | `linux-x64` | OSS CAD Suite asset architecture pattern (change for non-x86_64 hosts) |
| `ECC_SIZER_DIR` | `~/.local/ecc-sizer` | Sizer install root (holds `bin/Sizer` and `src/sizer_os.tcl`) |
| `ECC_SIZER_URL` | empty | Full direct URL override for the ecc-sizer prebuilt package (set manually while no official Release exists) |
| `GH_PROXY` | empty | GitHub download proxy prefix (e.g. `https://gh-proxy.org/`), for restricted networks |

The script produces `~/.ecc-env.sh` (PATH (including the Sizer bin directory) + `CHIPCOMPILER_ICS55_PDK_ROOT` + `CHIPCOMPILER_OSS_CAD_DIR` + `CHIPCOMPILER_ECC_SIZER_ROOT` when Sizer is installed), idempotently makes `~/.bashrc`/`~/.zshrc` (and `~/.profile` for bash login shells) load it, and creates a `~/.local/bin/ecc` symlink. Example for a restricted network:

```bash
GH_PROXY=https://gh-proxy.org/ bash ecc-cli-setup.sh
```

### Local source-built bundle

To install a bundle built from the local checkout, build it first, then point the
installer at the archive. `ECC_CLI_URL` accepts an absolute local path or a
`file://` URL; local files are copied directly and never use `GH_PROXY`.

```bash
cd ecc
bash docs/ecc-cli-local-build.sh

# Replace the CLI and provision any required dependencies.
ECC_CLI_URL="$PWD/dist/release/ecc-cli-linux-x86_64.tar.gz" \
  bash docs/ecc-cli-setup.sh --force
```

When the PDK, Yosys, and Sizer are already ready, replace only the CLI:

```bash
ECC_CLI_URL="file://$PWD/dist/release/ecc-cli-linux-x86_64.tar.gz" \
  bash docs/ecc-cli-setup.sh --force --skip-pdk --skip-tools --skip-sizer
```

The final self-check still fails until every required dependency is ready.

### Pre-built CLI bundle (manual install)

Download `ecc-cli-linux-x86_64.tar.gz` from [GitHub Releases](https://github.com/openecos-projects/ecc/releases) and extract it to a fixed directory:

```bash
mkdir -p ~/.local/ecc
tar -xzf ecc-cli-linux-x86_64.tar.gz -C ~/.local/ecc
~/.local/ecc/ecc --version    # self-check
```

The extracted payload is an `ecc` executable plus an `_internal/` directory (PyInstaller layout); **the two must stay together** (do not copy the `ecc` binary elsewhere alone). To run `ecc` from any directory, put the extraction directory on your `PATH` — pick one:

```bash
# Option A: add to your shell config (~/.bashrc for bash, ~/.zshrc for zsh)
echo 'export PATH="$HOME/.local/ecc:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Option B: symlink into ~/.local/bin, which is on PATH by default on Ubuntu
mkdir -p ~/.local/bin
ln -s ~/.local/ecc/ecc ~/.local/bin/ecc

# Option C: system-wide install (shared by multiple users)
sudo tar -xzf ecc-cli-linux-x86_64.tar.gz -C /opt/ecc
sudo ln -s /opt/ecc/ecc /usr/local/bin/ecc
```

Verify and upgrade:

```bash
which ecc && ecc --version          # from any directory, should print ecc <version>
# Upgrading = overwrite the extraction directory with the new bundle; symlinks from options B/C need no change
```

> The latest official release (v0.1.0-alpha.11 — what `ecc-cli-setup.sh` installs by default) already ships every command in this guide, including `doctor`/`signoff`/`report` and the `run` workspace/range selectors. When the source tree is ahead of the last release (behavior added between releases), build locally with [ecc-cli-local-build.sh](ecc-cli-local-build.sh) and install via `ECC_CLI_URL` (procedure in [ecc-cli-dev.en.md §6](ecc-cli-dev.en.md)); re-running `bash ecc-cli-setup.sh --force` reinstalls the official release, and unreleased behavior disappears with it — the expected rollback.

> `ecc` resolves the project from the current directory by default (wherever `ecc.toml` lives), so "launch from any folder" is the normal usage; to operate on a project from elsewhere, add `--project <dir>`.

### Running from source

```bash
# Nix (inside the ecc repository)
nix run . -- --help

# uv development environment (inside the ecc repository)
uv run ecc --help
```

## 1. General conventions

- Global: `ecc --version` (single version line), `ecc --help`.
- Project location: project-scoped commands accept `--project <dir>` (defaults to the current directory). `--workspace <name>` is a managed, non-empty single path segment in that project, never a filesystem path. A fresh project creates `default` on bare `ecc run`; a project with one active workspace auto-selects it, while one with multiple active workspaces requires `--workspace`. A named workspace is created and registered in `project.json` before its files are created. Legacy `runs/` projects must be upgraded with `ecc migrate` before running a flow. Each project has one `ecc.toml`; workspace inputs are copied to its own `origin/` directory at creation time.
- Structured output: `init`, `check`, `run`, `status`, `log`, `config`, `migrate`, `doctor`, `param`, `pdk`, `signoff`, and `report` accept `--json` (`{"records":[...]}`), `--jsonl` (one JSON record per line), and `--plain` (`key=value`, for scripting), with human-readable TEXT by default. `ecc version` supports the same flags with its version-specific schema; `rpc serve` and `layout-image` use their own protocols instead.
- Exit codes: 0 on success; 1 on business failure (error records look like `[error] error=<machine-readable-code>`).
- Step tokens come in three vocabularies, distinguished by context:
  - **display names** (output and input of `ecc status` / `ecc log` / `ecc report step`, uniformly lowercase/underscore): `synthesis / lec / floorplan / placement / cts / legalization / timing_optimization / routing / filler / rcx / sta / lvs / postroutelec / drc / harden`;
  - **persisted names** (the original names in `home/flow.json`; required by `--from`/`--only`/`--to` on existing workspaces, e.g. `place`, `CTS`, `Timing optimization`): `Synthesis / lec / Floorplan / place / CTS / legalization / Timing optimization / route / filler / RCX / sta / lvs / postRouteLec / drc / Harden`;
  - **aliases when creating a new range** (the first `--from A --to B` workspace creation normalizes aliases; both spellings are accepted): e.g. `cts`↔`CTS`, `route`↔`routing`, `timingopt`↔`Timing optimization`, `postlec`↔`postRouteLec`.
  A misspelled name returns `unknown_step` with the full list of available step names — copy one of them as printed.

Command overview:

```
$ ecc --help
Commands:
  version       Show ECC runtime, component, and installed tool versions
  layout-image  Render a GDS file into a layout image
  init          Create a new ECC project
  check         Validate the current project setup
  run           Run the configured RTL-to-GDS flow
  status        Show a quick run/step progress summary (full evidence:...)
  log           Show available logs or step log content
  config        Show resolved project or step configuration
  migrate       Migrate a legacy runs/ project to the manifest layout
  doctor        Check host environment: PDK, tools, and components
  param         Manage EDA parameters
  pdk           Show and configure the PDK path used by this project
  signoff       Inspect and export signoff packages
  report        Generate design-summary, QoR score, checklist, and step reports
  rpc           Run the private ECC JSON-RPC runtime
```

## 2. version — show versions

```bash
ecc version           # text
ecc version --json    # JSON (schema_version/ecc/dreamplace/ecc_tools/tools)
ecc version --jsonl   # one {"component", "version"} object per line
ecc version --plain   # one key=value record
ecc --version         # single ecc version line
```

The first four lines are bundle metadata (Python package versions). The
`yosys` / `sizer` / `klayout` lines are resolved from the environment the
same way a flow run resolves them, and show the binary's own version, or
`not installed` / `unknown` when it is absent or cannot report one.

```console
$ ecc version
ecc 0.1.0a11
dreamplace 0.1.0a7
ecc_tools 0.1.0a12
runtime ECC CLI
yosys 0.68+132
sizer not installed
klayout 0.30.2

$ ecc version --json
{"schema_version": 1, "runtime": "ECC CLI", "ecc": "0.1.0a11", "dreamplace": "0.1.0a7", "ecc_tools": "0.1.0a12", "tools": {"yosys": "0.68+132", "sizer": "not installed", "klayout": "0.30.2"}}
```

## 3. init — create a project

```bash
ecc init <NAME> [--json | --jsonl | --plain]
```

Creates an `ecc.toml`, `rtl/`, and `constraints/` skeleton under `NAME/` (the workspace is created by the first `ecc run`):

```console
$ ecc init gcd
[init]
  project: gcd
  status: created
  path: gcd
  check: ecc check --project gcd
  run: ecc run --project gcd
```

The generated `ecc.toml` (edit `design.*` and `pdk.root` as needed):

```toml
[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/gcd.v"]      # a single Verilog file, or one filelist for multiple sources (e.g. rtl/filelist.f)
# Optional entry inputs for non-RTL ranges:
# netlist = "inputs/gcd.v"
# golden_netlist = "inputs/gcd-golden.v"
# def = "inputs/gcd.def"
# sdc = "constraints/gcd.sdc"
# spef = "inputs/gcd.spef"
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"           # ics55 is the currently supported PDK
root = ""                # icsprout55-pdk path; empty falls back to CHIPCOMPILER_ICS55_PDK_ROOT / ICS55_PDK_ROOT

[flow]
# preset: rtl2gds | syn_sta | synthesis_lec
preset = "rtl2gds"
```

## 4. check — validate the project configuration

```bash
ecc check [--project DIR] [--json | --jsonl | --plain]
```

Validates required `ecc.toml` fields (design/pdk/flow), the PDK name and contents (tech LEF/LEF/liberty); manifest projects declaring multiple RTL sources also validate every source. Existence of a single RTL source file is validated by `ecc run` per the entry step when it creates the workspace (reported as `step_input_missing`):

```console
$ ecc check        # PDK not ready
[check]
  fail pdk.root is required
  inspect: ecc check --json
rc=1

$ ecc check        # once everything is ready
[check]
  project: gcd
  status: checked
  config: ecc.toml
  inspect: ecc status
  run: ecc run
  rtl: pass
    path: rtl/gcd.v
  inspect: ecc check --json
rc=0
```

### Environment self-check: ecc doctor

`ecc doctor` checks every dependency in one command (PDK, yosys including the slang frontend, bundled ecc-tools/dreamplace, required Sizer, and optional KLayout), reporting pass/fail/skip per component with remediation hints; only **required** failures produce a non-zero exit:

```bash
ecc doctor [--project DIR] [--json | --jsonl | --plain]
```

```console
$ ecc doctor          # run inside the project (the PDK probe needs ecc.toml or --project)
[status]
  doctor: environment
  status: attention          # ok = all pass / attention = only optional failures (rc=0) / failed = required failure (rc=1)
  checked: 7
  failed: 0                  # `failed` counts required failures only; optional ones go to `attention`
  attention: 1
  run: ecc run
  component: yosys
  status: pass
  detail: ~/.local/oss-cad-suite/bin/yosys
  component: yosys-slang
  status: pass
  detail: read_slang frontend available
  component: ecc-tools       # remaining components: dreamplace / klayout / sizer / pdk
  ...
```

For a fresh or `--overwrite` target, `ecc run` preflights bundled ecc-tools plus Yosys for presets containing synthesis, DreamPlace for presets containing placement/legalization, and Sizer for presets containing Timing optimization (including `rtl2gds`). A missing component fails fast with `env_not_ready`:

```console
$ ecc run
[error]
  env_not_ready
  reason: yosys: Yosys executable not found. ...
  preset: rtl2gds
  doctor: ecc doctor
rc=1
```

Notes:

- PDK root resolution priority: `pdk.root` in `ecc.toml` > `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT` > the repo default `<ecc checkout>/../pdk/icsprout55-pdk` (ecos-studio workspace layout; used by the data layer and `ecc pdk show`. `ecc check`/`ecc run` still require one of the first three and report `pdk.root is required` otherwise).
- The synthesis step still fails fast internally on slang problems (the log reports `yosys slang frontend check failed`); inspect afterwards with `ecc log synthesis`.
- Setup/repair script: `bash docs/ecc-cli-setup.sh` (see section 0; `--check-only` checks only).

### Manual checklist (fallback when doctor is unavailable)

`ecc check` covers only "project config (required design/pdk/flow fields) + **PDK contents** (tech LEF / LEF / liberty)"; it **does not check external tools**, nor the existence of a single RTL source file (that is validated by `ecc run` when it creates the workspace). Verify manually:

| Dependency | Check command | Ready when |
|---|---|---|
| Python components (ecc-tools / dreamplace, bundled with the CLI) | `ecc version` | `ecc_tools` / `dreamplace` show a version instead of `unknown` |
| PDK (ics55) | `ecc check` | `status: checked`; if liberty is missing run `make unzip` per the README |
| Yosys (synthesis) | `which yosys && yosys -V`, or `echo $CHIPCOMPILER_OSS_CAD_DIR` | either works (`CHIPCOMPILER_OSS_CAD_DIR` pointing at OSS CAD Suite takes priority) |
| Yosys slang frontend | `yosys -Q -T -p "help read_slang"` | output does **not** contain `No such command` (builtin since yosys ≥ v0.67; older builds need a loadable slang plugin) |
| KLayout (only needed by `layout-image`) | `python3 -c "from klayout import lay"` | no ImportError |
| Sizer (required by `ecc doctor`; needed by the Timing optimization step in the complete rtl2gds chain) | `which Sizer`; optionally `echo $CHIPCOMPILER_ECC_SIZER_ROOT` | both the executable and a root containing `src/sizer_os.tcl` must resolve; the root may be configured or discovered from the binary. Fresh or `--overwrite` `rtl2gds` targets preflight Sizer; existing workspaces and `--workspace` reruns skip preflight, so a missing binary can still fail mid-flow |

A copy-paste self-check snippet:

```bash
ecc version                                                     # 1. Python components
ecc check                                                       # 2. config + RTL + PDK
which yosys >/dev/null || [ -x "$CHIPCOMPILER_OSS_CAD_DIR/bin/yosys" ] \
  && echo "yosys: OK" || echo "yosys: missing (install OSS CAD Suite and export CHIPCOMPILER_OSS_CAD_DIR)"
yosys -Q -T -p "help read_slang" 2>&1 | grep -q "No such command" \
  && echo "slang frontend: missing (needs yosys >= v0.67 or a working slang plugin)" \
  || echo "slang frontend: OK"
```

Notes:

- PDK root resolution priority: `pdk.root` in `ecc.toml` > `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT` > the repo default `<ecc checkout>/../pdk/icsprout55-pdk` (`ecc check`/`ecc run` still require one of the first three).
- ECC-Tools / DreamPlace ship as Python wheels (`ecc-tools-bin`, `ecc-dreamplace`) bundled in the CLI package; a normal install is all they need.

## 5. run — execute a flow

### 5.1 Project mode (regular)

```bash
ecc run [OPTIONS]
  --project TEXT     project directory (defaults to cwd)
  --workspace TEXT   create, select, or resume a managed workspace name
  --resume           continue from the first non-successful step
  --from TEXT        re-execute from a step, or pair with --to for a new range workspace
  --to TEXT          inclusive final step for a bounded range (requires --from)
  --only TEXT        run exactly one persisted step
  --force            re-execute an already successful --only step
  --preset TEXT      flow preset override for this run only (not written back to ecc.toml), e.g. --preset syn_sta
  --overwrite        overwrite an existing run (only deletes genuine ECC run directories, with safety checks)
  --set KEY=VALUE    parameter override, repeatable (e.g. --set place.target_density=0.65), recorded in the run provenance
  --json / --jsonl / --plain
```

For a fresh or `--overwrite` workspace, the pipeline reads `ecc.toml` → resolves only the design files required by the entry step plus PDK/parameters → preflights bundled ecc-tools plus the selected tools → records the workspace in `project.json` → creates it under `<project>/<workspace-name>` → copies its declared design inputs to `origin/`, writes the resulting step configuration, and executes the selected flow. A workspace never stores a second project input manifest. Existing workspaces resume their persisted flow without rewriting its inputs or step configuration. `rtl2gds` is the full 15-step chain (Synthesis→LEC (Yosys equivalence check)→Floorplan→place→CTS→legalization→Timing optimization (sizer)→route→filler→RCX→sta→LVS→postRouteLec (Yosys equivalence check)→DRC→Harden; Harden emits GDS + abstract LEF + timing LIB).

A summary is printed when the run finishes (real output):

```console
$ ecc run --preset synthesis_lec
[workspace]
  workspace id: default
  status: success
  workspace: /tmp/gcd/default
  inspect: ecc status --workspace default
  log: ecc log --workspace default

$ ecc run --workspace default          # everything already succeeded → nothing to do (no_op)
[workspace]
  workspace id: default
  status: success
  workspace: /tmp/gcd/default
  inspect: ecc status --workspace default
  log: ecc log --workspace default
```

The `--json` output carries `no_op: true` (the `--resume`/`--only` selector paths also carry an `executed_steps` list). If `ecc.toml` and the baseline values recorded in `project.json` effectively disagree (for example `pdk.root` resolving to a different PDK than the one recorded by the first run, or `flow.preset` differing from the workspace's declared range), a `warning: ...` line (`config_layer_diverged`) is prepended to the summary block; it does not affect the execution result.

**Target reconciliation on an existing workspace**: on a repeat `ecc run`, the CLI aligns the workspace's persisted flow with the current target (the `flow.preset` from `ecc.toml`, or the start/end range declared for that workspace in `project.json`):

- the persisted steps are a **prefix** of the target and not finished yet → resume, **auto-extending** to the target end when necessary (for example a workspace first created with `--preset synthesis_lec` while `ecc.toml` says `rtl2gds`: a subsequent bare `ecc run` continues from the current progress and completes the physical flow);
- the persisted range ⊇ the target and every step succeeded → `no_op` (a default resume never re-runs the wider persisted range past the target end);
- the target and the persisted flow **diverge** (neither a prefix nor a superset) → `flow_mismatch`; rebuild with `--overwrite` as the error suggests, or use a new `--workspace`.

Parameter and selector boundaries:

- `--set KEY=VALUE` only takes effect when **creating** a workspace and is recorded in `home/cli-param-overrides.json`; on an existing workspace it reports `set_requires_fresh_run` (suggesting `--overwrite` or a new `--workspace`);
- `[params.*]` in `ecc.toml` likewise no longer applies to an existing workspace (the workspace reuses the `home/params.toml` captured at creation), in which case a `params_ignored_on_existing_run` warning is attached;
- `--preset` only affects the target of the current invocation and is **not written back** to `ecc.toml`:

```console
$ ecc run --preset bogus  # invalid preset (ecc.toml is not modified)
[error]
  unsupported_preset
  preset: bogus
  presets: rtl2gds, syn_sta, synthesis_lec
  inspect: ecc config
rc=1
```

Typical usage:

```bash
ecc run                                        # create default; auto-select and resume when a single active workspace exists
ecc run --workspace baseline --preset rtl2gds  # create a named complete-flow workspace
ecc run --workspace syn-only --preset syn_sta  # synthesis-only single-step workspace
ecc run --workspace cts-only --from cts --to cts      # new range workspace (alias spellings are fine)
ecc run --workspace cts-route --from cts --to routing # same; both ends accept aliases
```

When creating a range workspace, only the design inputs required by the **entry step** are validated: Synthesis needs `rtl`; LEC/postRouteLec need `netlist` + `golden_netlist`; Floorplan needs `netlist`; the physical steps (place/CTS/legalization/timing optimization/route/filler/rcx/drc/lvs/harden) need `def` + `netlist`; sta additionally needs `spef`; `sdc` is validated only when declared. Missing inputs report `step_input_missing`:

```console
$ ecc run --from cts --to route          # new range but def/netlist are missing
[error]
  step_input_missing step_input_missing: cts requires design.def
  step_input_missing step_input_missing: cts requires design.netlist
rc=1
```

### 5.2 Workspace mode (debugging / re-runs)

```bash
ecc run [--workspace NAME] [--resume | --from STEP [--to STEP] | --only STEP [--force]]
```

- `--resume`: continue from the first non-successful step (the default when no selector is given);
- `--from STEP`: on an existing workspace, re-run a step and its suffix; pair it with `--to STEP` to run an inclusive persisted range;
- on a new workspace, `--from` and `--to` must be supplied together and dynamically build the inclusive flow range;
- `--only STEP [--force]`: run exactly one step; `--force` re-runs it even if it already succeeded;
- `--resume`, `--only`, and a range are mutually exclusive; a fresh range cannot be combined with `--preset`, `--resume`, `--only`, `--force`, or `--overwrite`; `--workspace` may be combined with `--project`;
- **`--from`/`--only`/`--to` on an existing workspace require the persisted names** (the original names in `home/flow.json`; see the vocabulary in section 1, e.g. `place`, `CTS`, `Timing optimization`); only a fresh range (`--from A --to B` given together) accepts the lowercase aliases. A misspelled name reports `unknown_step` with the full list of available names:

```console
$ ecc run --workspace default --from synthesis   # the persisted name is "Synthesis"
[error]
  unknown_step unknown step 'synthesis'; available steps: Synthesis, lec, Floorplan,
  place, CTS, legalization, Timing optimization, route, filler, RCX, sta, lvs,
  postRouteLec, drc, Harden
  workspace: /tmp/gcd/default
```

- the workspace is modified in place: the re-run steps' `output/` is replaced and downstream steps are marked `Unstart` (output files are retained for later runs). When a step's subdirectory was never created (for example a missing tool left it `Incomplete`), selectors refuse to run and report `step_unavailable`.

```bash
ecc run --workspace default --resume               # continue from the first non-successful step
ecc run --workspace default --from CTS --to route  # re-run an inclusive range
ecc run --workspace default --only place           # run exactly one step (no_op if already successful)
ecc run --workspace default --only place --force   # force a re-run of that step even if successful
ecc run --workspace default --from Synthesis       # re-run the whole persisted suffix from the top
```

Misused selectors produce clear errors (all rc=1):

```console
$ ecc run --resume            # the project has no workspaces yet
[error]
  selector_requires_workspace

$ ecc run --to route          # --to cannot appear on its own, without --from
[error]
  flow_range_requires_pair

$ ecc run --from cts          # on a fresh target --from must be paired with --to
[error]
  flow_range_requires_pair

$ ecc run --force             # --force belongs to --only alone
[error]
  force_requires_only

$ ecc run --from cts --to route --preset rtl2gds   # a fresh range conflicts with other selectors
[error]
  selector_conflict

$ ecc run --workspace a/b     # a workspace must be a single name, never a path
[error]
  invalid_workspace invalid_workspace: 'a/b' is not a single workspace name
```

### 5.3 run error-code quick reference

| Error code | Trigger | Remediation |
|---|---|---|
| `run_exists` | the target directory already exists but is not a valid ECC workspace (no `home/flow.json`) | `--overwrite` (with safety checks) or a different `--workspace` |
| `overwrite_refused` | the `--overwrite` target is not a genuine ECC workspace directory | inspect the directory contents and clean it up manually |
| `invalid_workspace` | the workspace name contains `/`, is an absolute path, or is `.`/`..`; or the directory is not a loadable workspace | use a compliant name / inspect the directory |
| `workspace_required` | the project has multiple active workspaces but no `--workspace` was given | pass one of the names listed in the error |
| `workspace_not_declared` | the `--workspace` name does not match an id declared in `project.json` (including aliases pointing at a declared path) | use the declared id given in the error |
| `workspace_conflict` | a workspace with the same name is already declared at another path | choose a different name |
| `workspace_registration_failed` | registering the new workspace in `project.json` failed (unwritable manifest, …) | make `project.json` writable and retry |
| `legacy_workspace_migration_required` | `ecc run` on a legacy `runs/` project | run `ecc migrate` first (the hint record carries the full command) |
| `selector_requires_workspace` | `--resume`/`--only` used directly on a brand-new project | run `ecc run` once first |
| `selector_conflict` | `--resume`/`--from`/`--only` combined, or a fresh range combined with `--preset` etc. | keep a single selector |
| `flow_range_requires_pair` | `--to` appears alone; or `--from` without `--to` on a fresh target | supply the missing pair argument |
| `force_requires_only` | `--force` without `--only` | add `--only STEP` |
| `unsupported_preset` | `--preset` is not in the supported list | pick from the `presets:` listed in the error |
| `step_input_missing` | the entry step of a fresh target is missing inputs such as `rtl`/`netlist`/`def`/`spef` | fill in the corresponding `[design]` fields in `ecc.toml` |
| `unknown_step` | the selector step name is not in the persisted flow | copy an available step name from the error |
| `step_unavailable` | the selected step has no usable subdirectory in the workspace (its creation failed earlier) | fix the environment first (`ecc doctor`), then rebuild with `--overwrite` |
| `flow_mismatch` | the target flow diverges from the workspace's persisted flow | rebuild with `--overwrite`, or use a new `--workspace` |
| `set_requires_fresh_run` | `--set` used on an existing workspace | `--overwrite` or a new `--workspace` |
| `env_not_ready` | the preflight of a fresh/`--overwrite` target finds a required tool missing | fix per the `ecc doctor` output |
| `config_error` other than `step_input_missing` | `ecc.toml`/manifest parameter validation failed | use `ecc check` to see the offending fields |

### 5.4 migrate — legacy-layout migration (transitional command)

```bash
ecc migrate [--project DIR] [--yes] [--json | --jsonl | --plain]
```

Migrates a legacy `runs/`-layout project to the manifest layout: each safe `runs/<id>` workspace is moved to `<project>/<id>`, its workspace-internal paths are rebased, and it is registered in a generated or updated `project.json`. By default it prints the migration plan and asks for confirmation; `--yes` skips the prompt. The command is kept for the transition period (marked deprecated in code) and can be retired once existing projects have migrated. `run`/`check`/`status` attach a migration-hint record to their output on legacy projects.

## 6. status — show run and step status

```bash
ecc status [--project DIR] [--workspace NAME] [--json | --jsonl | --plain]
```

`status` is the lightweight progress check; for the full per-step evidence
report use `ecc report step` (§12.4). `--workspace` is the name of an existing
managed workspace and may be combined with `--project`.

```console
$ ecc status
[status]
  workspace id: default
  status: failed
  workspace: /tmp/gcd/default
  inspect: ecc status --workspace default
  log: ecc log --workspace default

  steps:
    synthesis (yosys) success 0:0:17
      log: ecc log synthesis --workspace default
    lec (yosys_lec) success 0:0:1
      log: ecc log lec --workspace default
    floorplan (ecc) success 0:0:1
      log: ecc log floorplan --workspace default
    placement (dreamplace) incomplete
      log: ecc log placement --workspace default
    cts (ecc) unstart
      log: ecc log cts --workspace default
    ...

$ ecc status --jsonl
{"workspace_id": "default", "status": "failed", "workspace": "/tmp/gcd/default", "inspect_cmd": "ecc status --workspace default", "log_cmd": "ecc log --workspace default"}
{"step": "synthesis", "tool": "yosys", "status": "success", "runtime": "0:0:17", "log_cmd": "ecc log synthesis --workspace default"}
{"step": "lec", "tool": "yosys_lec", "status": "success", "runtime": "0:0:1", "log_cmd": "ecc log lec --workspace default"}
...
```

The run-level status aggregates all steps: `success / warning / failed / ongoing / unstart` (`missing / corrupt` when flow.json is absent or damaged); the step-level states are `success / warning / incomplete / unstart / ongoing / pending / invalid`. An unproven synthesis-level LEC is reported as `warning`, while its evidence is retained and the physical flow continues.

## 7. log — view logs

```bash
ecc log [STEP] [--project DIR] [--workspace NAME] [--json | --jsonl | --plain]
```

Without STEP it lists all log files (the run-level flow log plus each step's log, with tail previews); with STEP it prints that step's log content (TEXT mode highlights ERROR/WARNING lines). STEP accepts both the display name (`synthesis`) and the persisted name (`Synthesis`); a step that has not run yet (no log file) reports `log status: missing`, and a misspelled name reports `unknown_step`.

```console
$ ecc log
[logs]
  run  log/gcd.2026-09-03_17-34-35
    tail:
      flow : /path/gcd/default/home/flow.json
      name | tool | state | runtime
      Synthesis | yosys | Success | 0:0:15
  inspect: ecc log --workspace default
  synthesis  Synthesis_yosys/log/Synthesis.log
    tail:
      synthesizing gcd...
  inspect: ecc log synthesis --workspace default

$ ecc log synthesis
[log] step=synthesis
  source: Synthesis_yosys/log/Synthesis.log
        synthesizing gcd...
  inspect: ecc log synthesis --workspace default

$ ecc log nosuchstep
[error]
  error
  step: nosuchstep
  status: unknown_step
  inspect: ecc status --workspace default
rc=1
```

## 8. config — view the resolved configuration

```bash
ecc config [STEP] [--project DIR] [--workspace NAME] [--json | --jsonl | --plain]
```

`--workspace` scopes the step view to an existing managed workspace; the project-level view remains
project-scoped and reads `ecc.toml` from the project directory.

Without STEP it prints the project-level configuration (`ecc.toml` keys + resolved absolute paths); with STEP it lists the configuration files actually in effect for that step under the workspace's `config/`.

```console
$ ecc config --plain    # project level (excerpt)
config=design.name scope=project value=gcd resolved=gcd source=ecc.toml
config=design.top scope=project value=gcd resolved=gcd source=ecc.toml
config=pdk.name scope=project value=ics55 resolved=ics55 source=ecc.toml
...

$ ecc config floorplan  # step level
[config]
  step:
    db_ecc.json (config)
      path: default/config/db_ecc.json
  inspect: ecc config floorplan --json
    floorplan_ecc.json (config)
      path: default/config/floorplan_ecc.json
  inspect: ecc config floorplan --json
```

## 9. param — parameter management

```bash
ecc param list                      # concise list: legacy parameters and explicit direct overrides
ecc param list --step cts           # list the reviewed schemas for one step
ecc param list --all                # list the complete schema registry
ecc param show KEY                  # show one parameter (value/default/source/type/range/mapping)
ecc param set KEY VALUE             # write into ecc.toml (comments and formatting preserved)
ecc param unset KEY                 # remove the override, restoring the default
ecc param diff                      # show only parameters that differ from their defaults
```

Common options: `--project DIR`, `--json / --jsonl / --plain`.

```console
$ ecc param list
  design
    design.frequency_mhz           100.0  (ecc.toml)
  floorplan
    floorplan.core_util            0.4
    floorplan.core_margin          [2, 2]
    floorplan.aspect_ratio         1.0
  cts
    cts.max_fanout                 20
  place
    place.target_density           0.2
    place.target_overflow          0.1
    place.global_right_padding     0
    place.cell_padding_x           300
    place.routability_opt          1
  route
    route.bottom_layer             MET2
    route.top_layer                MET5
  sta
    sta.max_paths                  1000

$ ecc param set place.target_density 0.65
  set place.target_density = 0.65 (ecc.toml)

$ ecc param set cts.skew_bound 0.05
  set cts.skew_bound = 0.05 (ecc.toml)

$ ecc param set pdk.tech prtech/techLEF/N551P6M_ecos.lef
  set pdk.tech = prtech/techLEF/N551P6M_ecos.lef (ecc.toml)

$ ecc param diff
  place.target_density           0.65 (was 0.2, ecc.toml)

$ ecc param show place.target_density
  place.target_density
    value          0.65
    default        0.2
    source         ecc.toml
    type           float
    applies        placement
    maps to        DreamPlace.target_density
    description    Target placement density
    range          [0.1, 0.95]
    ...

$ ecc param set route.top_layer MET9     # invalid value
[error]
  invalid_value value 'MET9' not in allowed choices ('MET2', 'MET3', 'MET4', 'MET5', 'MET6') for route.top_layer
  param: route.top_layer
rc=1
```

`set` maintains the corresponding group table at the end of `ecc.toml`; `unset` cleans it up:

```toml
[params.place]
target_density = 0.65

[params.floorplan.die_builder]
mode = "die_size"

[pdk.overrides]
tech = "prtech/techLEF/N551P6M_ecos.lef"
```

The 13 legacy semantic parameters retain their names and behavior. Every reviewed static tool-template field is supplied by a per-step `config_params/*.py` schema. Use `ecc param list --step <step>` or `ecc param list --all` for the version-specific complete list and types. List and object values use JSON literals, for example `ecc param set cts.routing_layer '[4, 5]'`.

Legacy semantic parameters:

| Parameter | Type | Default | Constraint | Effective step |
|---|---|---|---|---|
| `design.frequency_mhz` | float | 100.0 | [1e-6, 10000] MHz | synthesis |
| `floorplan.core_util` | float | 0.4 | [0.01, 1.0] | floorplan |
| `floorplan.core_margin` | list[int] | [2, 2] | — | floorplan |
| `floorplan.aspect_ratio` | float | 1.0 | [0.1, 10.0] | floorplan |
| `cts.max_fanout` | int | 20 | [1, 200] | cts |
| `place.target_density` | float | 0.2 | [0.1, 0.95] | placement |
| `place.target_overflow` | float | 0.1 | [0.0, 1.0] | placement |
| `place.global_right_padding` | int | 0 | [0, 100] | placement |
| `place.cell_padding_x` | int | 300 | [0, 10000] | placement |
| `place.routability_opt` | int | 1 | {0, 1} | placement |
| `route.bottom_layer` | str | MET2 | MET1–MET5 | routing |
| `route.top_layer` | str | MET5 | MET2–MET6 | routing |
| `sta.max_paths` | int | 1000 | [1, 100000] | sta |

Priority: CLI `--set` > `ecc.toml` `[params.*]` > template defaults. `pdk.*` path parameters write to `[pdk.overrides]`: `pdk.tech`, `pdk.lefs`, `pdk.libs`, and `pdk.mapping_file` resolve relative to `pdk.root`, while `pdk.sdc` and `pdk.spef` resolve relative to the project directory; all are file-validated.

## 10. pdk — PDK path configuration

Two ways to attach a PDK: `ecc pdk setup` does everything (auto clone + `make unzip`,
skipping downloads for an already-complete checkout), or `ecc pdk set-root` wires in
a ready-made checkout directly — `[pdk] root` in `ecc.toml` (the path is expanded to
absolute form; the directory must already exist). Incomplete contents (e.g.
`make unzip` not run yet) do not block the setting — a hint is emitted instead:

All `pdk` subcommands accept `--project DIR` and `--json/--jsonl/--plain`.

```bash
ecc pdk setup [~/pdk/icsprout55-pdk]     # all-in-one: clone (if missing) -> make unzip (if liberty missing, honors GH_PROXY + retries) -> wire in; defaults to ~/.local/icsprout55-pdk
ecc pdk set-root ~/pdk/icsprout55-pdk   # wire in only (for an already-ready PDK)
ecc pdk show                             # effective root, its source (ecc.toml / env / repo default), contents check
ecc pdk unset                            # clear root; falls back to env vars / repo default
ecc pdk set-root /bad/path               # -> [error] invalid_pdk_path (not a directory)
```

```console
$ ecc pdk set-root ~/pdk/icsprout55-pdk
[status]
  pdk: set-root
  status: set
  path: /home/user/pdk/icsprout55-pdk
  config: ecc.toml
  check: ecc check
```

The resolution priority is unchanged: `ecc.toml [pdk] root` > `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT` > the repo default `<ecc checkout>/../pdk/icsprout55-pdk` (ecos-studio workspace layout). Keep `pdk.root` on `ecc pdk set-root`; `pdk.tech`, `pdk.lefs`, `pdk.libs`, `pdk.mapping_file`, `pdk.sdc`, and `pdk.spef` use `ecc param set KEY VALUE`, which writes `[pdk.overrides]`.

## 11. signoff — signoff package

`ecc signoff export` requires a ready Harden signoff package. `ecc signoff inspect` can assess a partially completed workspace. Both subcommands accept `--project DIR` and an optional managed `--workspace NAME`, plus `--json/--jsonl/--plain`.

### 11.1 inspect — readiness review

```bash
ecc signoff inspect [--project DIR] [--workspace NAME] [--json | --jsonl | --plain]
```

Refreshes completed-step analysis and `home/checklist.json`, then prints the signoff package readiness status (`ready / attention / blocked`), the seven groups (initial/config/harden/final_design/sta/spef/reports), and the risk list. **blocked still exits with rc=0** (inspection is advisory; the gate lives in export):

```console
$ ecc signoff inspect --workspace default
[signoff]
  status    : blocked
  workspace : default
  export    : ecc signoff export -o <path>
  report    : ecc report summary

  groups:
    initial        ready      (2/2)
    config         ready      (4/4)
    harden         blocked    (1/3)
    sta            blocked    (3/6)
    ...

  risks:
    [blocked] Harden signoff requirements block export
              Current-output analysis refresh failed: ...
```

### 11.2 export — export the signoff package tar.gz (gated)

```bash
ecc signoff export -o <path>.tar.gz [--include-debug] [--project DIR] [--workspace NAME] [--json | --jsonl | --plain]
```

For an existing workspace, for example:

```bash
ecc signoff export --project /path/to/gcd --workspace default -o /path/to/gcd_signoff_package.tar.gz
```

Same source as the GUI's "export signoff package": refreshes analysis → collects every deliverable under initial/config/harden/final → atomically writes `<design>_signoff_package.tar.gz`. When readiness is insufficient the export is refused (no partial archive is produced):

```console
$ ecc signoff export -o gcd.tar.gz --project gcd
[error]
  signoff_incomplete signoff package is incomplete: quality.drc.clean, artifact.lvs.report, ...
  inspect: ecc signoff inspect
rc=1

$ ecc signoff export -o gcd.tar.gz --project gcd     # once ready
[export]
  signoff: export
  status: exported
  path: /abs/path/gcd.tar.gz
```

## 12. report — design summary, QoR score, checklist, and step evidence

```bash
ecc report summary    [-o PATH] [--project DIR] [--workspace NAME] [--json | --jsonl | --plain]
ecc report qor        [-o PATH] [--project DIR] [--workspace NAME] [--json | --jsonl | --plain]
ecc report checklist  [-o PATH] [same selector and output options]
ecc report step       [STEP] [--section feature|analysis|checklist]... [same selector and output options]
```

### 12.1 summary — text design summary

Generates a design summary with the same layout as the GUI's "export report (text)" (8 sections: physical / timing / clock / multi-corner / routing / power / verification / execution cost), by default written to `<workspace>/signoff/<design>_design_summary.txt`. The report does not require a completed flow; it summarizes whatever has run so far.

```console
$ ecc report summary --project gcd
[status]
  report: summary
  status: written
  path: /path/gcd/default/signoff/gcd_design_summary.txt
  design: gcd
  bytes: 3789
  view: cat /path/.../gcd_design_summary.txt
```

Report excerpt (metrics without data show `—`; conditional rows collapse automatically):

```
===================  ECOS STUDIO — DESIGN SUMMARY REPORT  ====================
Design Name        : gcd
PDK / Node         : ics55
...
[ 2. TIMING CLOSURE & PERFORMANCE ]
  Target Clock Period                  5.0 ns              Target freq: 200.0 MHz
  Setup Slack (WNS / TNS)              -0.25 ns / -1.2 ns  VIOLATION
...
[ 8. FLOW EXECUTION COST ]
  Stage              Tool                  Runtime     Peak Mem  State
  Synth              yosys                     18s          512MB  Success
```

Notes: inspect/export refresh each step's analysis first (matching the GUI);
the report extracts the current state by default (the engine API
`generate_text_report(workspace, refresh_analysis=True)` requests a refresh).

### 12.2 qor — overall QoR score report

Scores the current workspace by the GUI project-dashboard rules: every v3 `qor_metrics.json` metric is converted to 0-100 against fixed fail thresholds (slack metrics linearly, core_utilization against the [0.45, 0.70] target window, lower/higher_is_better proportionally), averaged per dimension, then combined with the dimension weights (Timing 0.35 / Power 0.25 / Routability 0.2 / Area 0.1 / Clock-DFM 0.1) into the overall score — **absent dimensions are not renormalized** (matching the GUI; missing dimensions lower the score); 60 is the pass line. By default written to `<workspace>/signoff/<design>_qor_report.txt`:

```console
$ ecc report qor --project gcd --plain
report=qor path=.../signoff/gcd_qor_report.txt bytes=1717 design=gcd \
  overall_score=61.8 qor_status=Green gate_status=pass \
  dimensions="[{'dimension': 'Timing', 'score': 75.0, 'weight': 0.35, 'metrics': 2}, ...]" \
  view="cat .../gcd_qor_report.txt" status=written
```

The report contains: the overall score and verdict (PASS/BELOW THRESHOLD/NOT RATED), the flow status color (Green/Yellow/Orange/Red/Blocked) and gate (DRC/LVS/RCX/STA step states), the area scoring step (the last successful step carrying area metrics), the dimension table, and the per-metric detail (corners scored independently).

### 12.3 checklist — signoff checklist report

Reads `home/checklist.json` (the schema-v3 signoff checklist maintained by flow steps / `ecc signoff inspect`) and renders a status report: the overview (passed/blocked/attention/unavailable), **BLOCKED item details** (with failure reasons and evidence paths), ATTENTION items, and the full table. When the checklist does not exist it returns `checklist_unavailable`. By default written to `<workspace>/signoff/checklist_report.txt`.

```bash
ecc signoff inspect --project gcd    # refresh the checklist first (if not present yet)
ecc report checklist --project gcd
```

### 12.4 step — per-step feature / analysis / checklist report (read-only preview)

Previews the **current step artifacts** of one workspace directly in the terminal. It writes no files and refreshes nothing (unlike `report qor/checklist` it does not load a Workspace, so no config migration or workspace log is appended). This is the deep-dive counterpart of `ecc status`: `status` answers "where is the run", `report step` answers "what exactly happened in this step":

- Without arguments: an overview table of all steps (state, runtime, peak memory, metric count, quality, checklist status)
- With `STEP`: the step's three detail sections
  - `feature`: run facts from `feature/<Step>.step.json` (state/runtime/peak_memory/constraints) plus tool facts, and the grouped design stats from `feature/<Step>.db.json` (Design Layout / Statis / Instances)
  - `analysis`: every metric of `analysis/qor_metrics.json` (value/unit/category/role) plus the quality status and quality gates of `analysis/qor_summary.json` (e.g. `qor.drc.clean — drc_count=336 == 0`)
  - `checklist`: `<step>/checklist.json` (the v3 contract; falls back to `home/checklist.json` filtered by step when missing)
- `--section` may be repeated to select sections; a section whose artifacts are missing renders as `unavailable`

Step tokens follow `ecc log` (`synthesis/floorplan/placement/cts/...`); flow-internal names (`Timing optimization`) and directory-name variants (`timing_optimization`) are accepted too. An unknown token returns `unknown_step` with the list of valid tokens.

```console
$ ecc report step --workspace default
[report step]
  workspace : /tmp/gcd/default
  steps     : 15

  step                   tool         status    runtime  peak MB  metrics quality  checklist
  synthesis              yosys        success   0:0:17   1165.89  10      pass     ready
  lec                    yosys_lec    success   0:0:1    0.164    -       -        ready
  floorplan              ecc          success   0:0:1    97.516   11      pass     ready
  ...
  drc                    ecc          success   0:0:3    42.0     12      blocked  blocked (1 blocked)

$ ecc report step Synthesis
[report step]
  step      : synthesis (Synthesis)
  tool      : yosys
  status    : success
  runtime   : 0:0:17, peak 1165.89 MB
  workspace : /tmp/gcd/default

  feature:
    run.peak_memory_mb                           1165.89
    run.runtime_seconds                          17.233
    run.state                                    Success
    ...

$ ecc report step drc --section analysis
  analysis:
    quality: blocked  (12 metrics, 0 missing)
    ...
    [BLOCK] qor.drc.clean — drc_count=336 == 0
```

## 13. rpc — JSON-RPC runtime sidecar (private)

```bash
ecc rpc serve --stdio [--persistent-db]
```

A JSON-RPC 2.0 service for front ends such as the GUI, framed with `Content-Length` over stdio. `--persistent-db` additionally exposes `db.ensure` / `db.release` plus the `layout.edit.*` / `floorplan.edit.*` method families. Handshake and call examples (full method list and parameters in [workspace-cli.md](workspace-cli.md)):

```console
→ {"jsonrpc":"2.0","method":"rpc.hello","params":{"version":1},"id":"hello-1"}
← {"jsonrpc":"2.0","result":{"version":1,"eccVersion":"0.1.0a11","capabilities":["rpc.hello","rpc.ping","rpc.shutdown","runtime.v2","operation.events","workspace.create","workspace.open","workspace.close","workspace.home","workspace.info","workspace.refresh_config","workspace.sync_config","workspace.reset_flow","workspace.export_signoff","workspace.inspect_signoff","flow.run","flow.run_step","operation.start_flow","operation.start_step","operation.status","operation.cancel","operation.ack_step_rendered","workspace.snapshot","workspace.recover_interrupted"]},"id":"hello-1"}

→ {"jsonrpc":"2.0","method":"rpc.ping","params":{},"id":"ping-1"}
← {"jsonrpc":"2.0","result":{"ok":true},"id":"ping-1"}
```

## 14. layout-image — render a GDS to an image

```bash
ecc layout-image --gds <in.gds> --image <out.png> [--width N] [--height N]
```

Renders a GDS layout snapshot via KLayout (default 1920×1920; KLayout must be available):

```bash
ecc layout-image --gds default/Harden_ecc/output/gcd_Harden.gds --image layout.png --width 2560 --height 1600
```

## 15. Typical end-to-end workflow

```bash
ecc init gcd && cd gcd
# drop in RTL, edit ecc.toml (top/clock/frequency, pdk.root, flow.preset)
ecc pdk set-root ~/pdk/icsprout55-pdk   # (optional) wire in a manually downloaded PDK
ecc doctor                         # environment check (PDK/yosys/slang/components)
ecc check                          # validate the project config before running
ecc run --preset rtl2gds           # run the full chain in one shot (Synthesis→…→Harden)
ecc run                            # run again: all successful → no_op; interrupted/failed → auto-resume
ecc status                         # step status; on failure:
ecc log placement                  # the failing step's log (TEXT mode highlights error lines)
ecc param set place.target_density 0.55   # tune a parameter and re-run
ecc run --overwrite --preset rtl2gds
ecc run --workspace default --only place --force   # or re-run a single step in place (--force needed once successful)
ecc run --workspace default --from CTS --to route  # or re-run a range in place (persisted names)
ecc config place                   # config files actually in effect for that step
ecc signoff inspect                # signoff readiness (blocked still exits 0)
ecc signoff export -o gcd_signoff.tar.gz    # export the signoff package once ready
ecc report summary                 # text design summary (signoff/<design>_design_summary.txt)
ecc report qor                     # QoR overall score report (signoff/<design>_qor_report.txt)
ecc report checklist               # signoff checklist report (signoff/checklist_report.txt)
ecc report step drc                # preview one step's feature/analysis/checklist (read-only)
ecc layout-image --gds default/Harden_ecc/output/gcd_Harden.gds --image gcd.png
```

Creating multiple managed workspaces for comparison experiments (each an independent directory, no interference):

```bash
# Choose the id before the first run so the generated manifest registers it.
ecc init gcd && cd gcd
ecc run --workspace baseline --preset rtl2gds                 # baseline: default parameters
ecc run --workspace exp1 --preset rtl2gds --set place.target_density=0.65
ecc status --workspace exp1
ecc log --workspace exp1
ecc report qor --workspace baseline    # compare the QoR reports of the two runs
ecc report qor --workspace exp1

# With a ready-made synthesis netlist, a range workspace can also start from an
# intermediate step (entry-input requirements in §5.1):
ecc run --workspace pnr --from floorplan --to route
```

Once `project.json` exists, project-scoped inspection, signoff, and report commands select among declared workspaces; a single active workspace is auto-selected, while multiple active workspaces require an explicit `--workspace NAME` (otherwise `workspace_required` is reported, listing the available names). A workspace no longer in use can be dropped from auto-selection by changing its `status` to `archived` in `project.json`.
