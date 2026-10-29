# ECC CLI User Guide (all currently supported commands)

`ecc` is the project-oriented command-line entry point of ECOS Chip Compiler, covering the full RTL-to-GDS flow: project creation, validation, execution, status/log/config inspection, parameter management, signoff, and reporting. This guide is aligned with the current source tree (v0.1.0-alpha.12); command outputs are either captured results or explicitly marked examples (run states in examples may be hand-crafted demo data).

- Source code: [chipcompiler/cli/](https://github.com/openecos-projects/ecc/tree/main/chipcompiler/cli/)
- For how to extend the CLI with new commands, see [development.md](https://github.com/openecos-projects/ecc/blob/main/docs/development.md#extending-the-cli)

## 0. Invocation

### One-shot setup (recommended)

Install the `ecc` CLI (Linux x86_64, glibc 2.34+):

```bash
curl -fsSL http://release.openecos.com/installers/ecc/latest/ecc-installer.sh | sh
```

Install Yosys (OSS CAD Suite with the slang frontend) and the ICS55 PDK as well:

```bash
curl -fsSL http://release.openecos.com/installers/ecc/latest/ecc-installer.sh | sh -s -- --with-toolchain
```

To install the latest nightly build (ecc, ecc-sizer, kepler-formal, and the ICS55 PDK) instead of the pinned stable release:

```bash
curl -fsSL http://release.openecos.com/installers/ecc/latest/ecc-installer.sh | sh -s -- --nightly
```

Add `--with-toolchain` to the same command to install Yosys (OSS CAD Suite) as well. Re-running the installer without `--nightly` switches back to the stable release; `--nightly-tag vX.Y.Z-nightly.YYYYMMDD` pins a specific nightly — browse the available tags on the [ecos-installer releases page](https://github.com/openecos-projects/ecos-installer/releases).

The wrapper installs to `~/.local/bin`. If that directory is not on your `PATH`, add it:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

The `--with-toolchain` wrapper exports `CHIPCOMPILER_OSS_CAD_DIR` and `CHIPCOMPILER_ICS55_PDK_ROOT`, so Yosys and the PDK are configured by the wrapper; when the toolchain is missing, re-run the installer with `--with-toolchain`. Check the environment with `ecc doctor`.

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

> This guide targets v0.1.0-alpha.12. Earlier releases do not provide the complete command surface documented here, including the bundled `ecc doc` guides, the `doctor`/`signoff`/`report` groups, and all workspace/range selectors. Check with `ecc --version`; when developing from this source tree, use `uv run ecc` as described in [development.md](https://github.com/openecos-projects/ecc/blob/main/docs/development.md#extending-the-cli).

> `ecc` resolves the project from the current directory by default (wherever `ecc.toml` lives), so "launch from any folder" is the normal usage; to operate on a project from elsewhere, add `--project <dir>`.

**Directory defaults:** omit `--project` inside a project root. Inside a managed workspace
root, omit both `--project` and `--workspace`: the CLI discovers the ancestor project and
uses the manifest's workspace ID, not the directory basename. Explicit selectors take
precedence. Multiple workspaces still require selection when invoked from the project root.
For an external workspace, pass `--project` to identify its owner. Standalone workspaces can
run workspace commands such as `status`, but project reports require a real manifest.
Discovery applies to roots only, never arbitrary project subdirectories or global searches.

Commands with both project and workspace scopes, such as `param` and `macro`, default to
workspace scope when invoked inside a workspace. Invoke them from the project root for
project scope. `process --workspace` can also be omitted there; cancellation still requires
`--run-id`. Explicit positional lifecycle arguments for create/import/delete/derive remain required.

### Running from source

```bash
# Nix (inside the ecc repository)
nix run . -- --help

# uv development environment (inside the ecc repository)
uv run ecc --help
```

## 1. General conventions

- Global: `ecc --version` (single version line), `ecc --help`.
- Project location: project-scoped commands accept `--project <dir>` (when the option is not given, the current directory is used). `--workspace <path>` accepts either a tool-managed, non-empty simple folder name or a complete absolute filesystem path. A name keeps the project-local `<project>/<workspace-id>` layout; an absolute path creates or selects an external workspace and uses its basename as the new ID unless the path is already registered. A fresh project creates `default` on bare `ecc run`; a project with one active workspace auto-selects it, while one with multiple active workspaces requires `--workspace`. A named workspace is created and registered in `project.json` before its files are created. Legacy `runs/` projects must be upgraded with `ecc migrate` before running a flow. Each project has one `ecc.toml`; workspace inputs are copied to its own `origin/` directory at creation time.
- Structured output: `init`, `check`, `run`, `status`, `log`, `config`, `migrate`, `doctor`, `rtl`, `param`, `macro`, `pdk`, `project`, `workspace`, `process`, `flow`, `signoff`, `report`, `compare`, `chipview`, and `gdsview` accept `--plain` where documented, with human-readable TEXT by default. The experiment groups do not share one output switch: `sweep create/list/run/verify`, `explore rank/promote`, and `reproducible export` emit JSON directly; `sweep compare`, `reproducible report`, and `diagnose run` default to text and accept `--json`; `sweep show` and `reproducible inspect/verify` emit JSON (their `--json` option is accepted but does not change the payload); `explore export` prints the selected JSON/CSV/Markdown content, or a one-line JSON status when `--output` is supplied. None of these groups supports `--plain`.
- Exit codes: 0 on success; 1 on business failure (error records look like `[error] error=<machine-readable-code>`). Complete registry:

| Exit code | Meaning | Emitted by |
|---|---|---|
| 0 | success (including advisory checks returning blocked/attention, a `no_op` run, and empty read-only queries) | all commands |
| 1 | business failure: validation, state, or execution error with a machine-readable error record on stdout/stderr | all commands |
| 2 | usage error: missing/invalid arguments, `--plain` combined with `--json`, unknown topic/profile/flow names | all commands |
| 6 | a required gate of a read-only quality check failed | `signoff check`, `sweep verify`, `diagnose run`, `reproducible verify` |
| 7 | at least one required gate is `unknown` and none failed, or no verified Pareto front was produced | `signoff check`, `explore promote --pareto` |
| 20 | `workspace_busy`: the target workspace is in use without `--no-wait` | mutating commands |
| 21 | `revision_conflict`: `--expected-revision` disagrees with the manifest revision | commands taking `--expected-revision` |
| 22 | `process_not_found`: the registered run process is stale and no live process holds the workspace lock | `ecc process` group |
| 23 | contract incompatible (reserved: the CLI itself never emits it; the GUI-side contract gate uses it when the runtime/CLI contract is unsupported) | — |
- Step tokens come in three vocabularies, distinguished by context:
  - **display names** (output and input of `ecc status` / `ecc log` / `ecc report step`, uniformly lowercase/underscore): `synthesis / lec / pre_floorplan / macro_placement / post_floorplan / preplace / placement / diff_sizing / cts / legalization / timing_optimization / routing / filler / lvs / drc / antennacheck / postroutelec / rcx / sta / poweranalysis / emir / harden`;
  - **persisted names** (the original names in `home/flow.json`; required by `--from`/`--only`/`--to` on existing workspaces, e.g. `place`, `CTS`, `Timing optimization`): `Synthesis / lec / preFloorplan / macroPlacement / postFloorplan / preplace / place / diff_sizing / CTS / legalization / Timing optimization / route / filler / lvs / drc / antennaCheck / postRouteLec / RCX / sta / powerAnalysis / emir / Harden`;
  - **aliases when creating a new range** (the first `--from A --to B` workspace creation normalizes aliases; both spellings are accepted): e.g. `cts`↔`CTS`, `route`↔`routing`, `timingopt`↔`Timing optimization`, `diffsizing`↔`diff_sizing`, `antenna`↔`antennacheck`, `postlec`↔`postRouteLec`.
  A misspelled name returns `unknown_step` with the full list of available step names — copy one of them as printed.

Command overview:

```
$ ecc --help
Commands:
  version       Show ECC runtime, component, and installed tool versions
  doc           Show a bundled guide (config = config reference, ug = user guide, tutorial)
  chipview       Open a workspace step's saved geometry snapshot in Chip Viewer
  gdsview       Open a workspace step's GDS in the KLayout viewer
  init          Create a new ECC project
  check         Validate the current project setup
  run           Run the configured RTL-to-GDS flow
  status        Show a quick run/step progress summary (full evidence: 'ecc report step')
  log           Show available logs or step log content
  config        Show resolved project or step configuration
  migrate       Migrate a legacy runs/ project to the manifest layout
  doctor        Check host environment: PDK, tools, and components
  check-update  Check whether a newer nightly build is available
  rtl           Import project RTL sources
  param         Manage EDA parameters
  flow          Inspect available ECC flows
  macro         Manage manual macro placement (macro_location.tcl)
  pdk           Show and configure the PDK path used by this project
  project       Edit project declarations in ecc.toml
  process       Inspect, cancel, or reconcile ECC run processes
  workspace     Import or refresh managed workspaces
  signoff       Inspect and export signoff packages
  report        Generate design-summary, QoR score, checklist, step reports, and saved snapshots
  compare       Compare saved Engineering Snapshots without running EDA tools
  reproducible  Export and verify reproducible ECC evidence packages
  sweep         Run deterministic parameter sweeps
  explore       Rank and select sweep candidates
  diagnose      Diagnose workspace flow, checklist, QoR, and recovery actions
```

## 1.5. doc — read the bundled guides in the terminal

`ecc doc` renders the bundled CLI guides directly in the terminal, so the full reference stays available offline inside packaged installations.

```bash
ecc doc config              # full configuration reference (rendered)
ecc doc ug --lang cn        # this guide, Chinese edition
ecc doc config --plain      # raw markdown, byte-for-byte
```

- Topics: `config` (config reference), `ug` (user guide), `tutorial`; `--lang` selects `en` (default) or `cn`.
- On a terminal the rendered guide opens in a pager with highlighting (`$PAGER`, falling back to `less`/`more`; `LESS=FRX` is defaulted when unset so colors survive `less`). When piped it prints in full without colors.
- Invalid topic/language values are rejected by argument validation (exit 2).
- Default output keeps the rendered unicode layout even when piped; `--plain` prints the raw markdown unchanged (script-friendly).

## 1.6. Shell completion

`ecc` ships built-in shell completion for bash, zsh, fish, and powershell. Print the activation script and load it into the current session:

```bash
eval "$(ecc --show-completion)"     # auto-detects the current shell
```

- Add that line to `~/.zshrc` / `~/.bashrc` (or home-manager `initExtra`) to enable completion permanently. zsh requires `compinit` to be initialized first.
- On NixOS or other declaratively managed setups, prefer the `eval` line over `--install-completion`: the latter rewrites `~/.zshrc` / `~/.bashrc` in place, which fails on read-only rc symlinks and conflicts with home-manager.

## 1.7. Command index

Every command and subcommand at a glance (semantics, options, and examples in the linked section; the shared `--project`/`--workspace`/`--plain`/`--json` selector conventions in §1 and §1.1):

| Command | Purpose | Section |
|---|---|---|
| `ecc version` | show runtime, component, and tool versions (`--json` emits the machine-readable contract) | §2 |
| `ecc doc TOPIC` | read the bundled guides in the terminal (`config` / `ug` / `tutorial`) | §1.5 |
| `ecc gdsview` | open a workspace step's GDS in KLayout | §13 |
| `ecc chipview` | open a workspace step's geometry snapshot in Chip Viewer | §14 |
| `ecc init NAME` | create a project skeleton | §3 |
| `ecc check` | validate project config, RTL sources, and PDK contents | §4 |
| `ecc run` | execute a flow (fresh/resume/range/single-step; project and workspace modes) | §5 |
| `ecc status` | quick run/step progress summary | §6 |
| `ecc log [STEP]` | list or view logs | §7 |
| `ecc config [STEP]` | view resolved project/step configuration | §8 |
| `ecc migrate` | migrate a legacy `runs/` layout | §5.4 |
| `ecc doctor` | environment self-check (9 components) | §4 |
| `ecc check-update` | check whether a newer nightly build is available | §2.5 |
| `ecc rtl import` | import RTL/filelist into the project's `rtl/` | §8.5 |
| `ecc param apply / list / show / set / unset / diff` | parameter management (project/workspace scopes) | §9 |
| `ecc flow list / show / validate` | inspect and validate registered flows | §8.6 |
| `ecc macro set / remove / import / show` | manual macro placement | §9.5 |
| `ecc pdk set-root / show / verify / unset` | PDK path configuration and content verification | §10 |
| `ecc project apply / baseline / reconcile / set / unset / add / remove / show / doctor` | edit `ecc.toml` declarations, select the QoR baseline, manifest health check | §8.5 |
| `ecc process inspect / cancel / reconcile` | inspect, cancel, or reconcile run processes | §6.5 |
| `ecc workspace create / import / derive / archive / delete / reset-flow / refresh / reconcile-deletes` | workspace lifecycle management | §8.5 |
| `ecc signoff inspect / check / export` | signoff readiness, quality gates, package export | §11 |
| `ecc report summary / qor / checklist / step / snapshot / project` | design summary, QoR score, checklist, per-step evidence, snapshots, project matrix | §12 |
| `ecc compare run` | compare two Engineering Snapshots | §12.6 |
| `ecc reproducible export / inspect / verify / report` | export/inspect/verify/summarize reproducible evidence packages | §11.5 |
| `ecc sweep create / show / list / run / compare / verify` | deterministic parameter sweeps | §11.5 |
| `ecc explore rank / export / promote` | rank, export, and promote candidates | §11.5 |
| `ecc diagnose run` | workspace diagnosis and recovery suggestions | §11.5 |

## 2. version — show versions

```bash
ecc version           # text
ecc version --json    # version and CLI contract as JSON
ecc --version         # single ecc version line
```

The first four lines are bundle metadata (Python package versions). The
`yosys` / `sizer` / `klayout` lines are resolved from the environment the
same way a flow run resolves them, and show the binary's own version, or
`not installed` / `unknown` when it is absent or cannot report one.

```console
$ ecc version
ecc 0.1.0a12
dreamplace 0.1.0a7
ecc_tools 0.1.0a13
runtime ECC CLI
yosys 0.69+24
sizer 0.1.0-alpha
klayout 0.30.2
```

`--json` emits the machine-readable contract: `schema_version` versions this JSON payload, `cli_contract` versions the CLI command-surface/exit-code contract (ECOS Studio checks both, plus `runtime`, to decide runtime compatibility), and `tools` lists tool versions resolved from the environment the same way a flow run resolves them:

```console
$ ecc version --json
{"schema_version": 2, "runtime": "ECC CLI", "ecc": "0.1.0a12", "dreamplace": "0.1.0a7", "ecc_tools": "0.1.0a13", "cli_contract": 1, "tools": {"yosys": "0.69+24", "sizer": "0.1.0-alpha", "klayout": "0.30.2"}}
```

## 2.5. check-update — check for a newer nightly build

```bash
ecc check-update [--plain]
```

Compares the current build identity with the newest published nightly release. The stable public CLI exposes only `--plain`; the desktop build also carries a hidden `--json` option that is not part of the documented CLI surface. `status` is one of `update_available`, `up_to_date`, or `unknown`. Network or release-metadata failures degrade to `unknown` with exit code `0`, so an offline update check never breaks an automation workflow.

```console
$ ecc check-update --plain
schema_version=1 status=update_available current_version=0.1.0a12 ...
```

## 3. init — create a project

```bash
ecc init <NAME> [--project-name TEXT] [--design-name TEXT] [--plain]
# ECOS Studio resource registration (optional, recorded into the generated manifest):
#   --mpc-resource-id / --mpc-display-name / --mpc-version / --mpc-root / --mpc-design-index
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
# Remove diff_opt to enable it; clear the list to also enable synthesis LEC.
skip_steps = ["lec", "diff_opt"]
```

## 4. check — validate the project configuration

```bash
ecc check [--project DIR] [--workspace NAME] [--plain]
```

Validates required `ecc.toml` fields (design/pdk/flow), the PDK name and contents (tech LEF/LEF/liberty), and every declared RTL source file (missing sources fail the check). With `--workspace NAME` the check runs against the effective configuration resolved for that declared workspace (manifest fallback and entry-layer range applied) instead of the bare project:

```console
$ ecc check        # PDK not ready
[check]
  fail pdk.root is required
  inspect: ecc check
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
  inspect: ecc check
rc=0
```

### Environment self-check: ecc doctor

`ecc doctor` checks every dependency in one command — 9 components total (PDK, yosys, yosys-slang, bundled ecc-tools/dreamplace, required Sizer, the kepler-formal and lec-dual LEC-equivalence probes, and optional KLayout) — reporting pass/fail per component with remediation hints; only **required** failures produce a non-zero exit:

```bash
ecc doctor [--project DIR] [--plain|--json]
```

```console
$ ecc doctor          # run inside the project (the PDK probe needs ecc.toml or --project)
[status]
  doctor: environment
  status: attention          # ok = all pass / attention = only optional failures (rc=0) / failed = required failure (rc=1)
  checked: 9
  failed: 0                  # `failed` counts required failures only; optional ones go to `attention`
  attention: 1
  run: ecc run
  component: yosys
  status: pass
  detail: ~/.local/oss-cad-suite/bin/yosys
  component: yosys-slang
  status: pass
  detail: read_slang frontend available
  component: ecc-tools       # remaining components: dreamplace / sizer / kepler-formal /
                             # lec-dual / pdk (required); klayout (optional)
  ...
```

- `kepler-formal` (required): the LEC/postRouteLec equivalence checker. Resolved from `CHIPCOMPILER_KEPLER_FORMAL_ROOT` first (the root-level `kepler-formal` wrapper or `bin/kepler-formal`), then from PATH.
- `lec-dual` (required): dual-engine LEC preflight probing both physical engines. Degraded mode is allowed — one missing engine still passes (the detail names the `degradation`; the step runs the available engine and the aggregate stays non-proven); only both missing fails.
- `klayout` (optional): its Python module supports legacy flow thumbnails, and
  its GUI executable is used by `gdsview`. The command accepts an explicit GUI
  executable through `KLAYOUT_BIN` and otherwise searches `PATH`.

`--json` emits a record array: a summary record first, then one record per component with `component`, `status`, `required`, and `detail`:

```console
$ ecc doctor --json
[
  {
    "doctor": "environment",
    "status": "ok",
    "checked": 9,
    "failed": 0,
    "attention": 0,
    "run": "ecc run"
  },
  {
    "component": "yosys",
    "status": "pass",
    "required": true,
    "detail": "~/.local/oss-cad-suite/bin/yosys"
  },
  ...
]
```

For a fresh or `--overwrite` target, `ecc run` preflights components derived from the target flow's actual step-tool mapping (steps skipped via `skip_steps` never have their tools probed): every flow preflights bundled ecc-tools; synthesis adds Yosys; placement/legalization adds DreamPlace; Timing optimization adds Sizer (including `rtl2gds`); an enabled LEC step probes only the selected `[flow] lec_engine` — default `kepler_formal` probes kepler-formal, `yosys_lec` probes Yosys, and `lec_dual` probes the composite dual engine. A missing component fails fast with `env_not_ready`:

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
- Reinstall/repair toolchain: re-run the section 0 installer (with `--with-toolchain`).

### Manual checklist (fallback when doctor is unavailable)

`ecc check` covers only "project config (required design/pdk/flow fields) + **PDK contents** (tech LEF / LEF / liberty) + every declared RTL source"; it **does not check external tools**. Verify manually:

| Dependency | Check command | Ready when |
|---|---|---|
| Python components (ecc-tools / dreamplace, bundled with the CLI) | `ecc version` | `ecc_tools` / `dreamplace` show a version instead of `unknown` |
| PDK (ics55) | `ecc check` | `status: checked`; if liberty is missing run `make unzip` per the README |
| Yosys (synthesis) | `which yosys && yosys -V`, or `echo $CHIPCOMPILER_OSS_CAD_DIR` | either works (`CHIPCOMPILER_OSS_CAD_DIR` pointing at OSS CAD Suite takes priority) |
| Yosys slang frontend | `yosys -Q -T -p "help read_slang"` | output does **not** contain `No such command` (builtin since yosys ≥ v0.67; older builds need a loadable slang plugin) |
| KLayout GUI (only needed by `gdsview`) | `KLAYOUT_BIN=/path/to/klayout ecc gdsview --help` or `command -v klayout` | executable resolves; run from a desktop session |
| Sizer (required by `ecc doctor`; needed by the Timing optimization step in the complete rtl2gds chain) | `which Sizer`; optionally `echo $CHIPCOMPILER_ECC_SIZER_ROOT` | both the executable and a root containing `src/sizer_os.tcl` must resolve; the root may be configured or discovered from the binary. Fresh or `--overwrite` `rtl2gds` targets preflight Sizer; existing workspaces and `--workspace` reruns skip preflight, so a missing binary can still fail mid-flow |
| kepler-formal (required by `ecc doctor`; probed when the selected range enables LEC/postRouteLec equivalence checks) | `echo $CHIPCOMPILER_KEPLER_FORMAL_ROOT`; `which kepler-formal` | either resolves the executable (the root-level wrapper or `bin/kepler-formal` under the root) |

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
  --workspace TEXT   create, select, or resume a workspace name or absolute path
  --resume           continue from the first non-successful step
  --from TEXT        re-execute from a step, or pair with --to for a new range workspace
  --to TEXT          inclusive final step for a bounded range (requires --from)
  --only TEXT        run exactly one persisted step
  --force            re-execute an already successful --only step
  --preset TEXT      flow preset override for this run only (not written back to ecc.toml), e.g. --preset syn_sta
  --overwrite        overwrite an existing run (only deletes genuine ECC run directories, with safety checks)
  --set KEY=VALUE    parameter override, repeatable (e.g. --set place.target_density=0.65), recorded in the run provenance
  --plain            key=value output for scripting
```

Automation options (used by ECOS Studio and CI drivers; optional for interactive use): `--expected-revision N` fails with `revision_conflict` (exit 21) when the workspace revision moved, `--command-id TEXT` stamps the mutation for idempotency/audit, `--no-wait` never blocks on a busy workspace (other mutation errors instead of waiting), `--run-id`/`--runtime-id` name the registered run process, and `--log-file PATH` redirects the whole run's stdout/stderr into a restricted-mode run log owned before preflight. The same revision/wait flags recur on other mutating commands (`param apply`, `macro import`, `workspace …`); `signoff export` accepts `--expected-revision` and `--no-wait`, but not `--command-id`. Runs registered this way are controlled with `ecc process` (§6.5).

For a fresh or `--overwrite` workspace, the pipeline reads `ecc.toml` → resolves only the design files required by the entry step plus PDK/parameters → preflights bundled ecc-tools plus the selected tools → records the workspace in `project.json` → creates it under `<project>/<workspace-name>` when the selector is a name, or at the exact absolute path when the selector is a path → copies its declared design inputs to `origin/`, writes the resulting step configuration, and executes the selected flow. An absolute workspace selector must be a complete external directory whose parent already exists; its basename becomes the new workspace ID unless the path is already registered. An existing valid workspace at an external path can be registered and resumed with the same command. A workspace never stores a second project input manifest. Existing workspaces resume their persisted flow without rewriting its inputs or step configuration. `rtl2gds` is the full step chain (Synthesis→lec (the `[flow] lec_engine` check, default kepler-formal; skipped by default — `[flow] skip_steps` defaults to `["lec", "diff_opt"]`, set `[]` to enable)→preFloorplan→macroPlacement→postFloorplan→preplace→place→diff_opt (skipped by default)→diff_sizing→CTS→legalization→Timing optimization (sizer)→route→filler→lvs→drc→antennaCheck→postRouteLec (the same selected LEC engine)→RCX→sta→powerAnalysis→emir→Harden; Harden emits GDS + Abstract LEF + timing LIB). `antennaCheck` and `emir` are advisory steps: an incomplete analysis is reported but does not by itself stop the remaining flow.

#### External workspace paths

Pass the complete absolute directory directly as the `--workspace` path argument when the workspace directory must live outside the project. It refers to the complete workspace directory, not a parent directory:

```bash
# Existing behavior: create and register the workspace below the project.
ecc run --project /projects/gcd --workspace <project-local-path>

# Create and run a tool-managed workspace outside the project.
ecc run --project /projects/gcd \
  --workspace /data/ecc-runs/gcd/archive

# Once registered, select the external workspace by its registered ID.
ecc run --project /projects/gcd --workspace archive --resume
ecc status --project /projects/gcd --workspace archive
```

The path must be absolute. `ecc` creates only the final directory, so its parent must already exist; an existing non-empty directory must already be a valid ECC workspace. The project root and its legacy `runs/` directory are protected targets, and a path that contains the project directory is rejected. A workspace ID cannot be rebound to another path, and a path already declared for another ID cannot be reused. Use `ecc workspace import` to register an existing workspace without running or modifying it.

The `synthesis_lec` preset requires the LEC the default policy skips, so this
example's project edits `ecc.toml` first (`sed -i 's/skip_steps = \["lec", "diff_opt"\]/skip_steps = []/' ecc.toml`
or any editor):

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

The run summary record carries `no_op: true` (visible in `--plain` output; the `--resume`/`--only` selector paths also carry an `executed_steps` list). If `ecc.toml` and the baseline values recorded in `project.json` effectively disagree (for example `pdk.root` resolving to a different PDK than the one recorded by the first run, or `flow.preset` differing from the workspace's declared range), a `warning: ...` line (`config_layer_diverged`) is prepended to the summary block; it does not affect the execution result.

**Target reconciliation on an existing workspace**: on a repeat `ecc run`, an explicit
start/end range in `home/params.toml` remains the target, including for bounded derived
workspaces in a project declaring `flow.preset`. Otherwise the project preset or the
workspace's persisted target governs. An explicit `--preset` overrides the saved range.
The CLI aligns the persisted ledger with that target:

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

When creating a range workspace, only the design inputs required by the **entry step** are validated: Synthesis needs `rtl`; lec/postRouteLec need `netlist` + `golden_netlist`; preFloorplan needs `netlist`; macroPlacement, postFloorplan, preplace, place, diff_sizing, CTS, legalization, Timing optimization, route, filler, RCX, drc, lvs, and Harden need `def` + `netlist`; sta additionally needs `spef`; `sdc` is validated only when declared. `antennaCheck`, powerAnalysis, and emir currently have no entry-input contract and rely on chained upstream artifacts, so begin such a range at an earlier validated checkpoint. Missing inputs report `step_input_missing`:

```console
$ ecc run --from cts --to route          # new range but def/netlist are missing
[error]
  step_input_missing step_input_missing: cts requires design.def
  step_input_missing step_input_missing: cts requires design.netlist
rc=1
```

For example, to reuse the post-floorplan artifacts from existing workspace `2` and create a workspace that runs only placement through routing, declare the **matching pair** of DEF and gate-level netlist as the new workspace's entry inputs before creating the range flow:

```bash
PROJECT=~/projects/benchmark/gcd
SOURCE="$PROJECT/2/postFloorplan_ecc/output"

ecc project set design.def "$SOURCE/gcd_postFloorplan.def.gz" --project "$PROJECT"
ecc project set design.netlist "$SOURCE/gcd_postFloorplan.v.gz" --project "$PROJECT"
ecc run --project "$PROJECT" --workspace floorplan-2-place-route \
  --from placement --to routing
```

`ecc run` has no `--def` or `--netlist` flag; a range entry reads `design.def` and `design.netlist` from `ecc.toml`. This registers `floorplan-2-place-route` in `project.json`, copies the two files into the new workspace's `origin/`, and runs placement through routing without rerunning postFloorplan. The first two commands change project-level `ecc.toml`, so they also affect later fresh workspaces. If those fields were previously absent, restore the default project entry after creation with `ecc project unset design.def --project "$PROJECT"` and `ecc project unset design.netlist --project "$PROJECT"`.

### 5.2 Workspace mode (debugging / re-runs)

```bash
ecc run [--workspace NAME] [--resume | --from STEP [--to STEP] | --only STEP [--force]]
```

- `--resume`: continue from the first non-successful step (the default when no selector is given);
- `--from STEP`: on an existing workspace, re-run a step and its suffix; pair it with `--to STEP` to run an inclusive persisted range;
- on a new workspace, `--from` and `--to` must be supplied together and dynamically build the inclusive flow range;
- `--only STEP [--force]`: run exactly one step; `--force` re-runs it even if it already succeeded;
- `--resume`, `--only`, and a range are mutually exclusive; a fresh range cannot be combined with `--preset`, `--resume`, `--only`, `--force`, or `--overwrite`; `--workspace` may be combined with `--project`;
- `--workspace` accepts either a single-segment name or an absolute path. Absolute paths create or register an external target; after registration, all workspace-scoped commands can use the manifest's declared ID;
- **`--from`/`--only`/`--to` on an existing workspace require the persisted names** (the original names in `home/flow.json`; see the vocabulary in section 1, e.g. `place`, `CTS`, `Timing optimization`); only a fresh range (`--from A --to B` given together) accepts the lowercase aliases. A misspelled name reports `unknown_step` with the full list of available names:

```console
$ ecc run --workspace default --from synthesis   # the persisted name is "Synthesis"
[error]
  unknown_step unknown step 'synthesis'; available steps: Synthesis, lec, preFloorplan,
  macroPlacement, postFloorplan, preplace, place, diff_sizing, CTS, legalization,
  Timing optimization, route, filler, lvs, drc, antennaCheck, postRouteLec, RCX, sta,
  powerAnalysis, emir, Harden
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

$ ecc run --workspace a/b     # a relative path is invalid; use a simple name or an absolute path
[error]
  invalid_workspace invalid_workspace: 'a/b' is not a single workspace name
```

### 5.3 run error-code quick reference

| Error code | Trigger | Remediation |
|---|---|---|
| `run_exists` | the target directory already exists but is not a valid ECC workspace (no `home/flow.json`) | `--overwrite` (with safety checks) or a different `--workspace` |
| `overwrite_refused` | the `--overwrite` target is not a genuine ECC workspace directory | inspect the directory contents and clean it up manually |
| `invalid_workspace` | the workspace name contains `/`, is a relative path, or is `.`/`..`; or the directory is not a loadable workspace | use a simple name (e.g. `myproject`) or a complete absolute path / inspect the directory (e.g. `/home/user/myproject`) |
| `workspace_required` | the project has multiple active workspaces but no `--workspace` was given | pass one of the names listed in the error |
| `workspace_not_declared` | the `--workspace` name does not match an id declared in `project.json` (including aliases pointing at a declared path) | use the declared id given in the error |
| `workspace_path_not_absolute` | the import path is not absolute | pass an absolute workspace directory to `workspace import` |
| `workspace_path_unsafe` | the path is the project root, the legacy `runs/` directory, contains the project directory, or has no existing parent | choose a safe directory whose parent already exists |
| `workspace_id_conflict` | the workspace ID is already declared at a different path | use the declared ID/path or choose another directory basename |
| `workspace_path_conflict` | the canonical path is already declared for another workspace ID | use the declared ID or choose another directory |
| `workspace_not_importable` | an existing directory is not a supported ECC workspace, or its design/PDK identity does not match the project | point to a valid workspace for this project |
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
ecc migrate [--project DIR] [--yes] [--plain]
```

Migrates a legacy `runs/`-layout project to the manifest layout: each safe `runs/<id>` workspace is moved to `<project>/<id>`, its workspace-internal paths are rebased, and it is registered in a generated or updated `project.json`. By default it prints the migration plan and asks for confirmation; `--yes` skips the prompt. The command is kept for the transition period (marked deprecated in code) and can be retired once existing projects have migrated. `run`/`check`/`status` attach a migration-hint record to their output on legacy projects.

## 6. status — show run and step status

```bash
ecc status [--project DIR] [--workspace NAME] [--plain|--json]
```

`status` is the lightweight progress check; for the full per-step evidence
report use `ecc report step` (§12.4). `--workspace` is the name of an existing
managed workspace and may be combined with `--project`. `--json` emits the
step records as a JSON record array.

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
    lec (kepler_formal) success 0:0:1
      log: ecc log lec --workspace default
    pre_floorplan (ecc) success 0:0:1
      log: ecc log pre_floorplan --workspace default
    macro_placement (dreamplace) success 0:0:5
      log: ecc log macro_placement --workspace default
    post_floorplan (ecc) success 0:0:1
      log: ecc log post_floorplan --workspace default
    placement (dreamplace) incomplete
      log: ecc log placement --workspace default
    cts (ecc) unstart
      log: ecc log cts --workspace default
    ...

$ ecc status --plain
workspace_id=default status=failed workspace=/tmp/gcd/default inspect_cmd="ecc status --workspace default" log_cmd="ecc log --workspace default"
step=synthesis tool=yosys status=success runtime=0:0:17 log_cmd="ecc log synthesis --workspace default"
step=lec tool=kepler_formal status=success runtime=0:0:1 log_cmd="ecc log lec --workspace default"
...
```

The run-level status aggregates all steps: `success / partial / failed / ongoing / unstart` (`missing / corrupt` when flow.json is absent or damaged; `partial` when a bounded rerun leaves a mix of successful and unstarted steps); the step-level states are `success / incomplete / unstart / ongoing / pending / invalid`. An unproven synthesis-level LEC fails the step and stops the flow.

## 6.5. process — inspect, cancel, or reconcile run processes

Runs launched with the automation options (`--run-id`, `--no-wait`, `--log-file`; §5.1) register
themselves in the project manifest so a detached or crashed run stays observable:

```bash
ecc process inspect [--run-id ID] [--project DIR] [--workspace NAME] [--plain]
ecc process cancel --run-id ID [--force] [--project DIR] [--workspace NAME] [--plain]
ecc process reconcile [--run-id ID] [--no-wait] [--project DIR] [--workspace NAME] [--plain]
```

- `inspect` reports the live runtime-process entry for the selected workspace (or one `--run-id`): run id, runtime id, pid, and log path — or `process_not_found` when the registered identity is stale and nothing live holds the workspace lock.
- `cancel` requests cancellation of the registered run: by default it sends a graceful, pid-verified cancel signal that takes effect at the next step boundary; `--force` sends SIGTERM to the run's whole process group (the run must still own its independent process group, otherwise `process_identity_changed`).
- `reconcile` repairs the persisted flow after a crashed or killed run: steps whose subprocess died without a terminal state are recovered to a consistent state and the stale registered entry is cleared; the record lists `recovered_steps`. Use it when a `workspace_busy` or stale-process error no longer reflects reality.

All three accept the standard `--project`/`--workspace` selectors; `--no-wait` on reconcile skips blocking on the manifest lock (returning `workspace_busy` instead of waiting).

```console
$ ecc process inspect --workspace trial     # no registered run process
[error]
  process_not_found No runtime process is registered
rc=22
```

## 7. log — view logs

```bash
ecc log [STEP] [--project DIR] [--workspace NAME] [--plain]
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
ecc config [STEP] [--project DIR] [--workspace NAME] [--plain|--json]
```

`--workspace` scopes the step view to an existing managed workspace; the project-level view remains
project-scoped and reads `ecc.toml` from the project directory. `lec`, `lvs`, `postroutelec`,
`poweranalysis`, and `harden` have no step-specific configuration (Tcl-driven, tool-default, or
reusing `db_ecc.json`).

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
  inspect: ecc config floorplan
    floorplan_ecc.json (config)
      path: default/config/floorplan_ecc.json
  inspect: ecc config floorplan
```

## 8.5. project / workspace — edit project declarations and refresh workspaces

`ecc project` updates the project-root `ecc.toml` and, for manifest projects, keeps `project.json.base_design` in sync; it does not touch already-created workspace snapshots. Legacy/virgin projects write only `ecc.toml`. The supported keys cover `[design]` `name`, `top`, `rtl`, `netlist`, `golden_netlist`, `def`, `sdc`, `spef`, `clock_port`, and `frequency_mhz`, plus `pdk.name`, `pdk.root`, and `flow.preset`:

```bash
ecc project set <KEY> <VALUES...>     # set one declaration (rtl takes a list and replaces it wholesale)
ecc project unset <KEY>               # remove one declaration
ecc project add design.rtl <FILES...>     # append RTL sources (design.rtl only)
ecc project remove design.rtl <FILES...>  # remove RTL sources (design.rtl only)
ecc project show [KEY]                # show declarations stored in ecc.toml
ecc project apply [--set KEY=VALUE...] [--unset KEY...] [--add-rtl FILE...] [--remove-rtl FILE...]
                                      # atomically apply several edits in one manifest revision
ecc project baseline <WORKSPACE_ID> [--reason TEXT]   # select the workspace whose saved QoR is the project baseline
ecc project reconcile                 # repair provable project intermediate states (e.g. half-finished deletes)
ecc project doctor [--fix]            # cross-check project.json against workspace directories; --fix repairs
```

For manifest projects, `project set`/`unset`/`add`/`remove` use the same atomic update path
and immediately sync `project.json.base_design`. `project apply` batches multiple edits so
they land in a single atomic manifest update (no half-applied combination on failure). `project
baseline` records which declared workspace's saved QoR later runs compare against. `project
doctor` (not to be confused with the environment `ecc doctor`, §4) reports missing
directories, unreadable workspaces, and unregistered workspace directories. Execution
state, flow ranges, and parameters are owned by workspace files; cached manifest fields
are not compared or rewritten. It exits 1 while inconsistencies remain. `--fix` removes
missing-directory entries and registers unregistered directories; unreadable workspace
files require manual restoration and their registrations are preserved.

### Importing RTL into a project

`ecc rtl import` copies design inputs into the project-owned `rtl/`
directory and updates both `ecc.toml` and `project.json`. This is the preferred
setup before opening the project in ECOS Studio, because a later Workspace can
use project-local inputs without depending on the original source directory:

```bash
ecc rtl import \
  --filelist /designs/gcd/sources/sources.f \
  --project /projects/gcd

ecc rtl import \
  --verilog /designs/gcd/top/gcd.v \
  --verilog /designs/gcd/common/defs.vh \
  --project /projects/gcd
```

For a filelist, paths are resolved relative to the filelist's directory. The
filelist and referenced files are copied below `<project>/rtl/` while retaining
their relative layout. The copied filelist is rewritten to reference only
project-local paths. Existing targets are rejected unless `--force` is passed.
Unsupported recursive/library filelist options (`-f`, `-v`, and `-y`) must be
expanded before import.

The command writes `design.rtl` in `ecc.toml` and updates
`project.json.base_design.rtl_list` plus the origin input metadata. Verify the
project before creating a Workspace:

```bash
ecc check --project /projects/gcd
ecc workspace create default --project /projects/gcd
```

If a Workspace already exists, importing new RTL does not mutate that
Workspace. Rebuild it explicitly from the updated project inputs:

```bash
ecc workspace refresh default --project /projects/gcd
```

ECOS Studio can then open `/projects/gcd/project.json`; its Workspace creation
flow consumes the project-local RTL declarations. Do not delete or move the
`rtl/` directory after import without updating `ecc.toml`.

All subcommands accept `--project DIR` and `--plain`. Real outputs:

```console
$ ecc project set design.def inputs/gcd.def
[status]
  project field: design.def
  value: inputs/gcd.def
  status: set
  source: ecc.toml

$ ecc project add design.rtl rtl/alu.sv
[status]
  project field: design.rtl
  value: ['rtl/gcd.v', 'rtl/alu.sv']
  status: added
  source: ecc.toml

$ ecc project remove design.rtl rtl/alu.sv
[status]
  project field: design.rtl
  value: ['rtl/gcd.v']
  status: removed
  source: ecc.toml

$ ecc project unset design.def
[status]
  project field: design.def
  status: unset
  source: ecc.toml

$ ecc project set design.bogus x      # unknown key
[error]
  unknown_project_field
  key: design.bogus
rc=1

$ ecc project add design.name x       # add/remove exist only for the rtl list
[error]
  unsupported_project_collection only design.rtl supports add/remove
  key: design.name
rc=1
```

`ecc workspace import WORKSPACE --path DIR --project PROJECT` registers an existing ECC workspace in `project.json` without running it, changing files below it, or moving it. `WORKSPACE` is the logical ID used by all later commands; `--path` is required and must be an absolute complete workspace directory. Import inspects the persisted flow, status, design, PDK, and parameter state read-only before atomically registering the path:

```bash
ecc workspace import archive \
  --project /projects/gcd \
  --path /data/ecc-runs/gcd/archive

# The imported workspace is now selected by ID.
ecc status --project /projects/gcd --workspace archive
ecc run --project /projects/gcd --workspace archive --resume
```

Import rejects malformed or incompatible workspaces, duplicate IDs/paths, protected paths, and legacy projects that still require `ecc migrate`. If an `ecc.toml` project has no `project.json` yet, a successful import creates the schema-v1 manifest before registering the workspace.

`ecc workspace refresh NAME --project DIR` rebuilds a workspace already declared in `project.json` from the current `ecc.toml`, without running the flow. It replaces the workspace's copied inputs, tool configuration, state, and artifacts at the path already declared in the manifest; run `ecc run --workspace NAME` afterwards. Before replacing anything, it compares the managed JSON configs and `macro_location.tcl` with `home/config-derived-manifest.json`. If one changed since the last derivation, refresh returns `derived_configs_modified`, lists the files, and leaves the workspace intact. Review the edit and either express it through `ecc param`/`ecc macro`/`ecc.toml` or pass `--force` to discard it. A workspace predating the manifest has no comparison baseline, so its first refresh proceeds. `ecc run --workspace NAME --overwrite` remains the explicit rebuild-and-run shortcut:

```console
$ ecc workspace refresh default
[status]
  workspace id: default
  status: refreshed
  workspace: /tmp/gcd/default
  run: ecc run --workspace default

$ ecc workspace refresh nosuch
[error]
  workspace_not_declared workspace_not_declared: unknown workspace 'nosuch'; declared workspaces: default
rc=1

$ ecc workspace refresh default --force   # intentionally discard detected config edits
$ ecc workspace refresh default --keep-backup   # keep the replaced tree as an archived .replace-backup-* sibling
```

Changes to entry inputs, PDK paths, and `flow.preset` must go through refresh, because they alter the workspace's input snapshot or flow structure. For parameter-only tweaks on an existing workspace there is also `ecc param set KEY VALUE --workspace NAME` (§9), which does not touch `ecc.toml`.

### Workspace lifecycle: create, derive, archive, delete, reset

The remaining `ecc workspace` subcommands manage the declared lifecycle without running the flow:

```bash
ecc workspace create <NAME> [--path DIR] [--from STEP] [--to STEP] [--set KEY=VALUE...]
                                    # create and register an empty managed workspace (no run)
ecc workspace derive <SOURCE> <TARGET> [--from STEP] [--to STEP]
                                    # branch a new workspace from an existing one's completed state
ecc workspace archive <NAME>        # mark the workspace archived: kept on disk, out of auto-selection
ecc workspace delete <NAME> [--delete-directory]
                                    # remove the manifest entry; --delete-directory also removes the files
ecc workspace reset-flow <NAME>     # clear persisted flow state so the next run starts from scratch
ecc workspace reconcile-deletes     # finish half-completed workspace deletions after a crash
```

`create` is what `ecc run` does before executing, split out for GUI/automation flows that
register the ID first; `--from/--to` declare a bounded range and `--set` records parameter
overrides at creation (the same fresh-run semantics as `ecc run --set`). `derive` copies the
source workspace into `<project>/<TARGET>` and registers the branch relationship in
`project.json`. `--from STEP` resets that step and all later steps, retaining earlier
completed states and outputs. To continue from a selected output, pass the **next runnable
step**; for example, `ecc workspace derive source trial --from preFloorplan` retains the
Synthesis output. Without `--from`, all steps are reset.
Adding `--to STEP` creates a bounded flow: `home/flow.json` contains only the inclusive
`--from`/`--to` range (or starts at the source's first step if `--from` is omitted).
The entry step's inherited netlist/DEF and constraints are copied into `origin/`, so the
flow can resume without putting earlier steps back into the ledger. For example,
`ecc workspace derive source trial --from preFloorplan --to macroPlacement` creates
exactly those two steps, using the source Synthesis output as input.
The derived snapshot uses the target
Workspace ID and starts at revision 1. Workspace-local parameter changes can then be applied
with `ecc param apply --workspace trial --set KEY=VALUE ...`, without modifying the source.
`archive` is the preferred way to
retire a workspace from auto-selection (instead of editing `project.json` by hand); `delete`
unregisters it and optionally removes the directory. The automation flags apply where
relevant (`--expected-revision` on archive/delete/reset-flow; `--command-id` and `--no-wait`
on the creating/branching subcommands; §5.1), and a mutation on an in-use workspace fails
with `workspace_busy` (exit 20).

```console
$ ecc workspace create trial
[status]
  workspace id: trial
  status: refreshed
  workspace: /tmp/gcd/trial
  run: ecc run --workspace trial

$ ecc workspace create trial    # entry inputs missing (create validates them like run)
[error]
  step_input_missing step_input_missing: design.rtl does not exist: /tmp/gcd/rtl/gcd.v
rc=1

$ ecc project baseline trial --reason "first experiment"
[status]
  project: baseline
  status: selected
  workspace: trial

$ ecc workspace derive trial branch_a
[status]
  workspace id: branch_a
  status: derived
  workspace: /tmp/gcd/branch_a
  workspace revision: 1
```

## 8.6. flow — inspect the registered flow catalog

```bash
ecc flow list [--plain|--json]
ecc flow show <FLOW_ID> [--project DIR] [--plain|--json]
ecc flow validate [--flow FLOW_ID] [--project DIR] [--plain|--json]
```

`flow list` prints every registered flow preset and its ordered steps (`rtl2gds`, `syn_sta`,
`synthesis_lec`) as `flow_step` records with `ordinal`, `skippable`, and `default skipped`
flags — the same catalog `ecc run --preset` selects from. `flow show FLOW_ID` filters to one
preset (`unknown_flow`, exit 2, for an unregistered name). `flow validate` checks the flow
definitions and step metadata and emits one `flow_validation` record per flow; all three are
read-only and need no running workspace.

```console
$ ecc flow show rtl2gds
[result]
  record: flow_step
  flow id: rtl2gds
  step id: Synthesis
  ordinal: 0
  skippable: False
  default skipped: False
  ...                            # all canonical steps in order; lec and diff_opt are skipped by default

$ ecc flow validate
[status]
  record: flow_validation
  status: valid
  flow id: rtl2gds
  step count: 22
  ...                            # one record per remaining flow

$ ecc flow list --json
[
  {
    "record": "flow_step",
    "flow_id": "rtl2gds",
    "step_id": "Synthesis",
    "ordinal": 0,
    "skippable": false,
    "default_skipped": false
  },
  ...
]
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
ecc param apply [--set KEY=VALUE...] [--unset KEY...]   # atomic batch of set/unset edits
ecc param set KEY VALUE --workspace NAME   # workspace-local override; ecc.toml is not touched
```

`list`, `show`, and `diff` also accept `--json` for a record-array view. `param apply` batches
several `set`/`unset` edits — project scope by default, or one workspace with `--workspace NAME` —
so the whole batch lands in one atomic update and one invalidation; a mid-batch validation
failure writes nothing. In the workspace scope `--step STEP` additionally restricts the batch to
parameters configurable at that step (`parameter_not_applicable` otherwise), and
`--expected-revision`/`--command-id`/`--no-wait` carry the automation contract (§5.1).

Common options: `--project DIR`, `--plain`. `list`, `show`, `set`, `unset`, and `diff` also accept `--workspace NAME`. With the selector, the value is written to that workspace's `home/params.toml` (not `ecc.toml`), its generated step configuration is refreshed, and the owning step plus its suffix are marked for re-run; a later `ecc run --workspace NAME` continues from that step. Workspace-local values are recorded in `workspace_param_overrides` with the pre-edit `baseline` — `param diff --workspace NAME` compares against that baseline and `param unset KEY --workspace NAME` restores it. Only reviewed parameters from `ecc param list --all` can be set locally, the parameter's owning step must exist in the workspace's persisted flow (otherwise `workspace_param_refresh_failed` — e.g. `place.*` on a synthesis-only workspace), and `pdk.*` path fields still require changing `ecc.toml` plus `ecc workspace refresh`:

```console
$ ecc param set design.frequency_mhz 150 --workspace default --plain
param=design.frequency_mhz value=150.0 status=set source=workspace workspace=default from_step=Synthesis invalidated_steps=['Synthesis']

$ ecc param list --workspace default      # workspace scope: only local overrides
    design.frequency_mhz           150.0  (workspace)

$ ecc param show design.frequency_mhz --workspace default
  design.frequency_mhz
    value          150.0
    source         workspace

$ ecc param diff --workspace default --plain
param=design.frequency_mhz value=150.0 baseline=100.0 source=workspace workspace=default

$ ecc param unset design.frequency_mhz --workspace default --plain
param=design.frequency_mhz value=100.0 status=unset source=workspace workspace=default from_step=Synthesis invalidated_steps=['Synthesis']
```

```console
$ ecc param list
  design
    design.frequency_mhz           100.0  (ecc.toml)
  floorplan
    floorplan.core_util            0.4
    floorplan.core_margin          [2, 2]
    floorplan.aspect_ratio         1.0
  cts
    cts.max_fanout                 32
  place
    place.target_density           0.4
    place.target_overflow          0.1
    place.global_right_padding     0
    place.cell_padding_x           200
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
  place.target_density           0.65 (was 0.4, ecc.toml)

$ ecc param show place.target_density
  place.target_density
    value          0.65
    default        0.4
    source         ecc.toml
    type           float
    applies        placement
    maps to        DreamPlace.target_density
    description    Target placement density
    range          [0.1, 1.0]
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
| `cts.max_fanout` | int | 32 | [1, 200] | cts |
| `place.target_density` | float | 0.4 | [0.1, 1.0] | placement |
| `place.target_overflow` | float | 0.1 | [0.0, 1.0] | placement |
| `place.global_right_padding` | int | 0 | [0, 100] | placement |
| `place.cell_padding_x` | int | 200 | [0, 10000] | placement |
| `place.routability_opt` | int | 1 | {0, 1} | placement |
| `route.bottom_layer` | str | MET2 | MET1–MET5 | routing |
| `route.top_layer` | str | MET5 | MET2–MET6 | routing |
| `sta.max_paths` | int | 1000 | [1, 100000] | sta |

Priority: CLI `--set` > `ecc.toml` `[params.*]` > template defaults. `pdk.*` path parameters write to `[pdk.overrides]`: `pdk.tech`, `pdk.lefs`, `pdk.libs`, and `pdk.mapping_file` resolve relative to `pdk.root`, while `pdk.sdc` and `pdk.spef` resolve relative to the project directory; all are file-validated.

## 9.5. macro — manual macro placement

```bash
ecc macro set INSTANCE --x X --y Y --orient ORIENT [--project DIR] [--workspace NAME] [--plain]
ecc macro remove INSTANCE [--project DIR] [--workspace NAME] [--plain]
ecc macro import PATH [--project DIR] [--workspace NAME] [--expected-revision N] [--command-id TEXT] [--no-wait] [--plain]
ecc macro show [--project DIR] [--workspace NAME] [--plain]
```

A design with hard macros (SRAMs, analog blocks) places them automatically with DreamPlace in the `macroPlacement` step, writing `config/macro_location.tcl`. `ecc macro` manages the manual-placement parameter `macro.placements`: coordinates are in microns and instances are committed `fixed`. While the parameter is non-empty, `macroPlacement` keeps its load/save flow but skips DreamPlace, and `postFloorplan` commits the macros from the file. Orientations: `R0`, `R90`, `R180`, `R270`, `MX`, `MY`, `MX90`, `MY90`; setting the same instance again updates it in place. `import` parses a `placeInstance` handoff file (microns, R-notation; comments and `setInstancePlacementStatus` lines are skipped) and replaces `macro.placements` wholesale; an empty file clears the parameter, and a malformed statement fails the import without writing anything.

Both `ecc param` scopes apply:

- project (default): stored in `ecc.toml` `[params.macro]`, rendered into the Tcl on the next fresh workspace (`ecc run` / `--overwrite`) or `ecc workspace refresh`;
- `--workspace NAME`: written to that workspace's `home/params.toml`; the Tcl is regenerated immediately and `macroPlacement` and its suffix are marked pending, so the next `ecc run --workspace NAME` resumes from `macroPlacement`.

`ecc macro show --workspace NAME` additionally parses the current `config/macro_location.tcl` and reports `file_placements` plus `diverged` (whether the file disagrees with the parameter), which surfaces hand-edited files or an import that has not landed.

```console
$ ecc macro set u_ram0 --x 10 --y 20.5 --orient R0
[status]
  param: macro.placements
  instance: u_ram0
  x: 10.0
  y: 20.5
  orientation: R0
  placements: [{'instance': 'u_ram0', 'x': 10.0, 'y': 20.5, 'orientation': 'R0'}]
  status: set
  source: ecc.toml

$ ecc macro set u_ram1 --x 150 --y 20.5 --orient MY
$ ecc macro show
[result]
  param: macro.placements
  placements: [{'instance': 'u_ram0', 'x': 10.0, 'y': 20.5, 'orientation': 'R0'}, {'instance': 'u_ram1', 'x': 150.0, 'y': 20.5, 'orientation': 'MY'}]
  source: ecc.toml

$ ecc macro remove u_ram1
[status]
  param: macro.placements
  instance: u_ram1
  placements: [{'instance': 'u_ram0', 'x': 10.0, 'y': 20.5, 'orientation': 'R0'}]
  status: removed
  source: ecc.toml
```

Adjusting macro positions on an existing workspace and re-running the affected segment:

```bash
ecc macro set u_ram0 --x 120.0 --y 80.0 --orient MY --workspace default
ecc run --workspace default                 # resumes from macroPlacement; downstream steps re-run
ecc macro remove u_ram0 --workspace default # removing the last entry restores DreamPlace auto placement; resume again for the automatic result
```

Importing an existing `macro_location.tcl` (for example from another project or a Chip Viewer manual-placement export) as the manual placements:

```bash
ecc macro import /path/to/macro_location.tcl --workspace default
ecc macro show --workspace default          # file_placements matches placements and diverged is False
ecc run --workspace default                 # skips DreamPlace; postFloorplan commits the macros from the file
```

Instance names must exist in the design and every hard macro must be listed — `postFloorplan` fails with the missing instance names otherwise. `macro_location.tcl` is a generated file and hand-editing it is unsupported (re-running `macroPlacement` without the parameter regenerates it). See [floorplan-flow.en.md](floorplan-flow.en.md) for the handoff format and staged-floorplan details, and the [Configuration Reference §1.5](ecc-config-ref.en.md) for the parameter.

## 10. pdk — PDK path configuration

The PDK itself comes from the install script (`--with-toolchain`; see the
tutorial) or a manual clone. Wire a ready checkout into the project with
`ecc pdk set-root` — `[pdk] root` in `ecc.toml` (the path is expanded to
absolute form; the directory must already exist). Incomplete contents (e.g.
`make unzip` not run yet) do not block the setting — a hint is emitted instead:

All `pdk` subcommands accept `--project DIR` and `--plain`.

```bash
ecc pdk set-root ~/pdk/icsprout55-pdk   # wire in a ready PDK checkout
ecc pdk show                             # effective root, its source (ecc.toml / env / repo default), contents check
ecc pdk show --json                      # same, as a JSON record array
ecc pdk verify                           # verify the resolved PDK contents without changing configuration
ecc pdk unset                            # clear root; falls back to env vars / repo default
ecc pdk set-root /bad/path               # -> [error] invalid_pdk_path (not a directory)
```

`pdk verify` re-runs the resolved-PDK contents check read-only (the same probe `pdk show`
reports) but enforces the outcome: a contents check that does not pass exits 1
(`pdk_contents_unavailable` when the resolved root is unavailable) — this is the form the
packaged smoke test uses. `show` and `verify` both accept `--json`.

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

`ecc signoff export` requires a ready Harden signoff package. `ecc signoff inspect` can assess a partially completed workspace. Both subcommands accept `--project DIR` and an optional managed `--workspace NAME`, plus `--plain`.

### 11.1 inspect — readiness review

```bash
ecc signoff inspect [--project DIR] [--workspace NAME] [--plain|--json]
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
    config         ready      (3/3)
    harden         blocked    (1/3)
    sta            blocked    (3/6)
    ...

  risks:
    [blocked] Harden signoff requirements block export
              Current-output analysis refresh failed: ...
```

### 11.2 check — read-only quality gates

```bash
ecc signoff check [--profile rtl2gds] [--project DIR] [--workspace NAME] [--plain]
ecc signoff check --json
```

`check` is read-only: it does not refresh analysis, launch EDA, or modify the workspace.
It evaluates the saved flow, QoR, checklist, and DRC/LVS/STA evidence and reports each
gate as `pass`, `fail`, or `unknown`. Missing evidence never becomes a pass. The overall
status is `pass` only when every gate passes, `fail` when any gate fails, and `unknown`
otherwise. The initial `rtl2gds` profile contains `flow_complete`, `qor_available`,
`checklist_ready`, `drc_clean`, `lvs_clean`, `sta_setup_clean`, and `sta_hold_clean`.

With `--json`, the command returns a record array whose gate records use the stable contract
`gate`, `required`, `status`, `reason`, `source`, `failed_items`, `violation_count`, `stale`,
and `provisional`. Artifact gates may additionally include `bytes` and `sha256`. The
`physical_signoff` profile additionally checks `lec_proven`,
`final_gds_available`, and `final_netlist_available`:

```bash
ecc signoff check --profile physical_signoff --json
```

It reads the postRouteLec proven result and Harden/filler final outputs, but does not hash
file contents. Missing or ambiguous artifacts return `unknown`. This is an assessment of
saved evidence, not tapeout approval. The physical profile marks QoR and checklist as
informational (`required=false`); missing QoR alone does not block its physical gate result.
Unknown profiles return `unknown_signoff_profile`; argument errors use exit code 2.

### 11.3 export — export the signoff package tar.gz (gated)

```bash
ecc signoff export -o <path>.tar.gz [--include-debug] [--additional-files -] [--project DIR] [--workspace NAME] [--plain]
```

`--additional-files -` reads a tar stream from stdin and embeds its regular files into the
archive next to the collected deliverables (relative POSIX paths only; at most 256 entries,
16 MiB per file, 64 MiB total — this is the channel ECOS Studio uses for user-selected extra
files). The command also accepts the automation flags `--expected-revision` and `--no-wait`
(§5.1).

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

### 11.5 Reproducible evidence export, sweeps, and diagnosis

Command contracts for `reproducible` and `diagnose`:

| Command | Required | Optional | Purpose |
|---|---|---|---|
| `ecc reproducible export` | `--output PATH` | `--project DIR`, `--workspace NAME` | export a read-only evidence tar.gz for a workspace; prints JSON |
| `ecc reproducible inspect` | `--package PATH` | `--files`, `--type all\|rtl\|config\|flow\|checklist\|signoff`, `--json` | offline package inspection with file-type filtering; prints JSON |
| `ecc reproducible verify` | `--package PATH` | `--json` | verify package schema, SHA-256 checksums, and fingerprints; prints JSON |
| `ecc reproducible report` | `--package PATH` | `--json` | summarize files, fingerprints, inputs, runtime, and verification status; text by default, JSON with `--json` |
| `ecc diagnose run` | — | `--project DIR`, `--workspace NAME` (default `default`), `--json` | one command combining flow, checklist, QoR, missing artifacts, and recovery suggestions; text by default |

The experiment groups do not provide `--plain`. Commands that emit JSON directly still expose the flags shown above; for `sweep show` and `reproducible inspect/verify`, `--json` is accepted but the payload is JSON either way. Real output examples:

```console
$ ecc reproducible export --workspace trial --output evidence.tar.gz
{
  "file_count": 19,
  "package": "/path/to/evidence.tar.gz",
  "status": "success"
}

$ ecc reproducible verify --package evidence.tar.gz
{"errors": [], "package": "/path/to/evidence.tar.gz", "status": "pass"}

$ ecc diagnose run --workspace trial --json
{
  "checklist": {"blocked_count": 27, "blocked_items": ["artifact.synthesis.netlist", "..."], "status": "blocked"},
  "errors": [],
  "flow": {"failed_steps": [], "status": "unstart"},
  "missing_artifacts": [],
  "next_actions": [
    "ecc report checklist --project /path/to/project --workspace trial",
    "ecc run --project /path/to/project --workspace trial --resume"
  ],
  "project": "/path/to/project",
  "qor": {"available": false, "score": "unknown"},
  "status": "blocked",
  "workspace": "/path/to/project/trial"
}
rc=6                        # failed or blocked diagnostics exit 6 (see the §1 exit-code table)
```

Create a deterministic parameter sweep. Repeated `--param` options define the Cartesian product; candidates are recorded under `experiments/<name>/` and do not modify the project manifest or baseline workspace. The full sweep/explore reference — plan and results schemas, execution isolation, and ranking rules — is documented in the [Sweep Reference](ecc-sweep-ref.en.md):

```bash
ecc sweep create --project /path/to/project --name density --param place.target_density=0.60,0.65 --param cts.skew_bound=0.08,0.10
ecc sweep list --project /path/to/project                  # JSON array of existing sweep names
ecc sweep show --project /path/to/project --name density    # the sweep plan (sweep.json)
ecc sweep run --project /path/to/project --name density [--max-candidates N]
ecc sweep compare --project /path/to/project --name density # candidate | flow | steps | checklist | violations | qor | exit | parameters
ecc explore rank --project /path/to/project --name density
ecc explore promote --project /path/to/project --name density --candidate candidate_0002
```

`--max-candidates N` bounds `sweep run` to the first N candidates of the plan (useful for a
smoke pass over a large product). `sweep run` is resumable: a candidate with one of the four
recorded statuses and an existing workspace is reused without re-running or recollecting
evidence. `sweep show` and `explore rank` print JSON directly; `sweep compare` prints a human
table by default and switches to JSON with `--json`. Rows sort passed-first and by descending
QoR score. Candidate-mode `explore promote` writes `experiments/<name>/winner.json` after
checking only the cached row and its `passed` status; it does not revalidate current evidence.
Use `explore promote --pareto --objective ...` to revalidate the current full flow, checklist,
signoff, metric registry, parameters, and snapshot before exporting the front. Pareto mode
always writes `pareto.json` on a successful export, writes `winner.json` only for an explicit
`--candidate` or `--weights` selection, and exits `7` when there is no verified front.

The first implementation is deterministic and evidence-oriented. It does not provide automatic optimization, distributed scheduling, multi-SDC, or automatic replacement of a baseline.

Reproducible exports include the ECC runtime version, an aggregate file fingerprint,
and fingerprints for project configuration and RTL inputs. Sweep plans include a
stable `plan_fingerprint` so two parameter plans can be compared independently of
creation time.

`ecc reproducible verify` audits the package schema, manifest entry types and duplicate paths,
archive file sizes, SHA-256 checksums, aggregate file fingerprint, input fingerprints, and
unsafe archive paths. Manifest or evidence tampering returns exit code `6`.

The reproducible manifest also records ECC, ECC-Tools, DreamPlace, Yosys, Sizer,
KLayout, and PDK identity/presence metadata so an evidence package can be compared
across environments.

A reproducible package can be copied to another directory and verified there; `inspect` and
`verify` use the package manifest and do not require the original project path to be present.

Offline package inspection is available without the original workspace:

```bash
ecc reproducible inspect --package evidence.tar.gz --files --json
ecc reproducible report --package evidence.tar.gz --json
```

The report summarizes package files, fingerprints, inputs, runtime metadata, and verification status.

Offline reports also support readable text output and file filtering:

```bash
ecc reproducible report --package evidence.tar.gz
ecc reproducible inspect --package evidence.tar.gz --files --type checklist --json
```

Supported file types are `all`, `rtl`, `config`, `flow`, `checklist`, and `signoff`.

The offline report also summarizes flow status, checklist status, QoR, and checker violation
count from evidence files. Missing or legacy evidence is reported as `unknown`.

Offline summary fields include evidence `sources` and `reasons` (`ok`, `missing`, or `invalid`),
while the value remains `unknown` when the evidence cannot be rated.

CI design-matrix legs run a lightweight packaged CLI smoke after the product flow. The smoke
uses an isolated temporary evidence workspace and checks reproducible export, verify, report,
and sweep-plan creation without running a second full EDA flow.

The CI packaged smoke can optionally consume the E2E output directory. When a real
`home/flow.json` is found, it additionally validates `status`, reproducible export,
and verification against that real workspace; otherwise it keeps the isolated contract smoke.

Verify sweep integrity before comparing or promoting candidates:

```bash
ecc sweep verify --project /path/to/project --name density_test
```

The command checks only the plan fingerprint, unique result membership, candidate-parameter
equality, workspace-directory existence, and missing results. It returns exit code `6` on
integrity errors. It does not audit step states, QoR validity, signoff, checklist contents,
or result field types. Candidate-mode `explore promote` likewise trusts the cached row;
Pareto promotion is the mode that revalidates current evidence and excludes stale candidates.

Export ranked sweep results for CI artifacts, GUI, or spreadsheets:

```bash
ecc explore export --project /path/to/project --name density_test --format csv --output density.csv
ecc explore export --project /path/to/project --name density_test --format markdown
```

Supported formats are `json`, `csv`, and `markdown`. Without `--output`, the content goes to
stdout. With `--output`, the file is written and stdout contains a one-line JSON status with
`status`, `format`, and the resolved output path.

Packaged CI smoke also verifies sweep result integrity and exports ranked results as JSON, CSV,
and Markdown. The files are uploaded under the design's `cli-contract` evidence directory.

Diagnose a workspace in one command:

```bash
ecc diagnose run --project /path/to/project --workspace ws_0012 --json
```

The result combines flow state, failed steps, blocked checklist items, QoR availability,
missing artifacts, and suggested recovery commands. Failed or blocked diagnostics return exit code `6`.

When the packaged CLI smoke receives an E2E output directory and finds a real workspace, it also
runs `diagnose run`, `report step`, `report project`, and `signoff check`. Their JSON evidence is
written under the design's `cli-contract` artifact directory as `diagnose.json`,
`report-step.json`, `report-project.json`, and `signoff.json`. Signoff quality failures may return
`6` or `7` and are preserved as evidence; invalid CLI usage still fails the smoke.
The isolated packaged smoke also creates deterministic candidate evidence and exercises
`sweep verify` plus `explore export` in JSON, CSV, and Markdown formats without launching a second
EDA flow.

Resuming `sweep run` reuses cached rows without recollecting step states, checklists, or QoR.
`qor_score` is the first `qor_score`/`score`/`ppa_score` number found in any workspace JSON
file. Signoff exit `7` is not itself a failure; the recorded status follows the step/status
rules in the [Sweep Reference](ecc-sweep-ref.en.md#7-results-contract-resultsjson).
Packaged smoke compares complete exports against the compare matrix and rejects malformed
fields and promotion of blocked/failed/unknown candidates. A real E2E workspace is also
collected through an isolated cached `sweep run` candidate, checking step states, overall QoR
and signoff exit codes. It writes `real-sweep-verify.json` and `real-sweep-results.json`
while keeping the original workspace read-only.

Diagnostics and offline evidence summaries derive flow status from step `state`, read checklist
`checklist/state/blocked/policy` fields, and use QoR `scalar_summary.score`. Legacy simplified
formats remain supported. The signoff QoR gate uses the same score reader. Missing, unrated,
or invalid scores are unavailable; corrupt checklists are never diagnosed as passed. Flow
completion and blocked checklist results are reported separately.

## 12. report — design summary, QoR score, checklist, and step evidence

```bash
ecc report summary    [-o PATH] [--project DIR] [--workspace NAME] [--plain]
ecc report qor        [-o PATH] [--project DIR] [--workspace NAME] [--plain]
ecc report checklist  [-o PATH] [same selector and output options]
ecc report step       [STEP] [--section feature|analysis|checklist|outputs]... [same selector and output options]
ecc report snapshot --output PATH [--project DIR] [--workspace NAME] [--plain|--json]
ecc report project [--project DIR] [--plain|--json]
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

Runs the ECC-QoR V3 engine over the current workspace. It separates three questions: five physical-quality coordinates (`timing`, `interconnect`, `area`, `power`, `robustness`), seven zero-tolerance feasibility gates, and evidence completeness. ECOS Studio consumes the same versioned `home/qor_report.json`; it does not maintain a second scoring table.

The scalar score uses the selected `qor_profile` weights (balanced by default) and **renormalizes over dimensions that can actually be evaluated**. Thus an undeclared power budget makes `power` null without compressing the remaining score. A failed feasibility gate forces score `0` / `FAIL`; an unexecuted gate stage or corrupt gate evidence produces `NOT_RATED` instead of a fabricated score. Status bands are `GREEN >= 90`, `YELLOW >= 75`, `ORANGE >= 60`, and `RED < 60`. The text report is written to `<workspace>/signoff/<design>_qor_report.txt` by default. An abridged `--plain` response using the reference fixture looks like this:

```console
$ ecc report qor --project gcd --plain
report=qor path=.../signoff/gcd_qor_report.txt bytes=... design=gcd \
  overall_score=98.96 qor_status=GREEN gate_status=PASS \
  dimensions="[{'dimension': 'timing', 'score': 100.0, 'state': 'OPPORTUNITY', 'features': ...}, ...]" \
  view="cat .../gcd_qor_report.txt" status=written
```

The report contains the composite/profile, five-dimension breakdown, feasibility gates, evidence state, deterministic diagnoses, and prioritized intervention hypotheses. See the [ECC QoR Reference](ecc-qor-ref.en.md) for formulas, profiles, thresholds, and the JSON contract.

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

Step tokens follow `ecc log` (`synthesis/pre_floorplan/macro_placement/post_floorplan/placement/cts/...`); flow-internal names (`Timing optimization`) and directory-name variants (`timing_optimization`) are accepted too. An unknown token returns `unknown_step` with the list of valid tokens.

```console
$ ecc report step --workspace default
[report step]
  workspace : /tmp/gcd/default
  steps     : 17

  step                   tool         status    runtime  peak MB  metrics quality  checklist
  synthesis              yosys        success   0:0:17   1165.89  10      pass     ready
  lec                    kepler_formal success   0:0:1    0.164    -       -        ready
  pre_floorplan          ecc          success   0:0:1    97.516   -       -        ready
  macro_placement        dreamplace   success   0:0:5    97.516   -       -        ready
  post_floorplan         ecc          success   0:0:1    97.516   11      pass     ready
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

#### Querying one step's outputs (`outputs`)

The DEF and Verilog outputs registered in the Engineering Snapshot can be queried explicitly:

```bash
ecc report step place --workspace <workspace> --section outputs
ecc report step sta --workspace <workspace> --section outputs --json
```

The default report still shows only feature, analysis, and checklist, preserving the existing
behavior. `outputs` runs no tools, does not migrate the snapshot or refresh the workspace, and
does not scan directories; a missing or damaged index returns `unavailable` without generating
a new one.

- `exists` and `bytes` check the in-workspace file at query time; a cached `exists` is not trusted.
- `availability` is `available`, `missing`, or `outside_workspace`; external references are not touched on the filesystem.
- `validity` is `not_current` for a step that did not succeed; even a successful step is only `unknown` — file existence plus step success do not prove hash, corner, or input consistency.
- This release only queries DEF/Verilog outputs registered in the snapshot; it does not promise a complete GDS, log, or report listing.

`report qor --json` currently still returns a report-generation summary and writes the report
file; it is not a read-only complete metrics API. Do not treat that output as the full QoR
schema.

### 12.5 snapshot — save a committed run snapshot

```bash
mkdir -p comparisons
ecc report snapshot --workspace default -o comparisons/before.json
ecc run --workspace default --only placement
ecc report snapshot --workspace default -o comparisons/after.json --json
ecc compare run --baseline comparisons/before.json --current comparisons/after.json
```

Saves the committed `home/engineering-snapshot.json` projection without loading or migrating
the workspace, refreshing its snapshot, running EDA, or copying artifact content.
`--output/-o` is required. Its parent directory must already exist, the destination must
be outside the source workspace, and existing files, directories, or symlinks are rejected.
Relative output paths are resolved against the current directory. Existing schema versions
2/3/4 and workspace revisions are preserved; the file size limit is 16 MiB.

Text, `--plain`, and `--json` return save metadata, not the snapshot body. JSON uses the
standard record array with `report=snapshot`, `status=written`, `path`, `source`, `bytes`,
`schema_version`, `workspace_id`, and `workspace_revision`. Read, destination, or write
failures return 1; argument errors return 2. Publication is atomic and never overwrites a
destination, with no non-atomic fallback. Temporary files are removed on failure.
Prefer saving while the workspace is idle; this command does not wait for EDA completion.

## 12.6. compare run — compare two saved run snapshots

```bash
ecc compare run --baseline before.json --current after.json
ecc compare run --baseline before.json --current after.json --json
ecc compare run --baseline before.json --current after.json --plain
```

Both arguments are saved copies of `home/engineering-snapshot.json`, not run IDs or workspace
names. The command does not run EDA tools, load workspaces, generate reports or modify inputs.
Save a copy before and after a run while the workspace is idle; automatic run history is not provided.

The comparison includes flow records, metric deltas, saved QoR, parameters, checklist/signoff
and artifact indexes. Missing values are never replaced by zero; incompatible units produce no
delta. Metric polarity comes from the existing registry. Different constraints, flow definitions,
PDK metadata, workspaces or unknown polarity produce unknown trends. QoR score comparison requires
the same scoring engine and profile. Overall summarizes numeric metrics and QoR score only;
it is not a signoff or tapeout decision.

JSON uses the shared record-array contract with a `run_comparison` record containing
`baseline/current`, `summary`, `compatibility`, `steps`, `metrics`, `qor`, `parameter_changes`,
`configuration_changes`, `signoff`, `checklist`, `artifacts` and `warnings`.
Artifact IDs identify paths, not file contents: `content_comparison` is always unknown.
Matching indexes do not prove matching contents; saved metadata does not verify RTL/PDK/SDC contents.

A completed comparison returns 0, including regressed or unknown results. Invalid snapshots or
duplicate comparison keys return 1; argument errors return 2. Compressed JSON is not accepted;
the existing 16 MiB snapshot limit applies, and older schemas are not migrated.
Use `--json` for nested automation results; it cannot be combined with `--plain`.

### 12.7 project — workspace QoR / step / checker matrix

```bash
ecc report project --project /path/to/project
# Inside the project or one of its managed workspace roots:
ecc report project --json
ecc report project --plain
```

Lists all manifest-declared workspaces, including archived entries, in descending saved
QoR score order, with overall flow, manifest status and per-step/tool state columns.
Ties retain manifest order. Real zero scores remain valid; missing, invalid, NOT_RATED
or stale scores come last without fabricated zeros or ranks. Columns form the union of
flow steps: absent steps show N/A; unreadable flows show unknown. This is a wide table;
use a wider terminal or JSON for automation.

QoR comes from `home/qor_report.json`, flow state from `home/flow.json`. Workspace identity
or flow-state mismatches invalidate a score for ranking. Running data is provisional.
Different profiles emit a comparability warning; numeric ordering is not a signoff decision.

A real first JSON record (excerpt; the `columns`/`workspaces` arrays expand in flow order):

```json
[
  {
    "report": "project",
    "schema_version": 1,
    "project": "/path/to/project",
    "design": "gcd",
    "status": "partial",
    "sort": "qor_score_descending_missing_last_manifest_order_ties",
    "columns": [
      {"step": "Synthesis", "token": "synthesis", "tool": "yosys"},
      {"step": "preFloorplan", "token": "pre_floorplan", "tool": "ecc"}
    ],
    "warnings": []
  }
]
```

Checker categories follow ECC metadata. DRC/LVS show explicit counts and clean/violated;
STA keeps setup and hold counts separate without summing across corners. Unfinished
checkers never reuse stale zero counts. LEC only shows a saved proven verdict, without
verifying netlist content or inventing a count. RCX/powerAnalysis without a supported
violation count show N/A. Execution success is separate from checker cleanliness.

No workspace loading/migration, EDA execution, QoR/snapshot refresh or file writing occurs.
JSON uses the shared record array with `report=project` and `columns/workspaces/warnings`.
Plain mode emits related project_report, step_column, workspace, workspace_step,
checker_count and warning records. Workspace-local gaps retain the row and yield partial
status with exit 0; invalid project metadata returns 1; argument errors return 2.
`--workspace` is not accepted by this project-wide report.

## 13. gdsview — open a step GDS in KLayout

```bash
ecc gdsview --project <project> --workspace <workspace> --step <step>
```

Opens the GDS published by the selected workspace step in KLayout's interactive
`LayoutView`. The command searches that step's `output` directory for exactly one
`*.gds` or `*.gds.gz` file, loads it, fits the hierarchy, and keeps the KLayout
window open until it is closed. It does not create a PNG.

The command launches the KLayout GUI executable and passes it the selected GDS;
it does not add a separate PyQt/PySide dependency to the ECC CLI or change the
ECOS Studio AppImage. KLayout supplies its own Qt runtime. The executable is
looked up only when `gdsview` runs.

Not every flow step publishes GDS. If the selected step has no GDS, the command
returns `gds_view_unavailable` and lists the steps in the workspace that do have
GDS outputs. If more than one GDS is present, it returns
`gds_view_ambiguous` with the candidate paths. A missing KLayout GUI executable
or Linux display returns a separate diagnostic instead of silently selecting
another step.

```bash
ecc gdsview --workspace default --step Harden
```

## 14. chipview — open a saved geometry snapshot

```bash
ecc chipview --project <project> --workspace <workspace> --step <step>
```

This opens the same native Chip Viewer used by ECOS Studio's layout thumbnail.
The command reads `<step>/output/geometry/geometry.manifest` and its sidecar
files; it does not read GDS or generate a PNG. Run it from ECOS Studio's
AppImage terminal so `ECOS_CHIP_VIEWER_BIN` points at the packaged
`chip-viewer-native`. An explicit executable path can be supplied with that
variable when using a development checkout.

The command checks the project, workspace, flow step, geometry manifest, Viewer
binary, and Linux display environment before spawning the detached Viewer. If
any prerequisite is missing, it returns a diagnostic with the expected path and
the remediation. Viewer stdout and stderr are saved under
`<workspace>/.chip-viewer/logs/`.

The command accepts `--plain` for one stable key-value result and `--json` for a
JSON record array. A successful result includes `status=started`, the selected
step, the manifest path, the resolved Viewer path, the Viewer PID, and the two
log paths. It returns exit code `1` for a missing or invalid workspace/geometry,
an unavailable Viewer or display, or a Viewer that exits during startup. The
most useful error codes are `chipview_step_not_found`,
`chipview_geometry_invalid`, `chipview_viewer_unavailable`,
`chipview_display_unavailable`, and `chipview_launch_failed`.

The AppImage itself is not parsed as a GDS input. The command only needs the
packaged executable to be discoverable through `ECOS_CHIP_VIEWER_BIN` (injected
by the ECOS Studio built-in terminal),
`ECOS_ELECTRON_RESOURCES_PATH/binaries/chip-viewer-native`, or `PATH`. If none
is executable, run the command from the AppImage's built-in terminal or set
`ECOS_CHIP_VIEWER_BIN` explicitly. The command never falls back to
`gdsview`.

Only steps in the geometry-snapshot set publish this manifest (for example
`pre_floorplan`, `macro_placement`, `post_floorplan`, `placement`,
`diff_sizing`, `cts`, `timing_optimization`, `legalization`, `routing`,
`filler`, `lvs`, `drc`, `rcx`, and `sta`). Harden does not publish a geometry
snapshot, so select a step that does when opening Chip Viewer:

```bash
ecc chipview --workspace default --step filler
```

## 15. Typical end-to-end workflow

```bash
ecc init gcd && cd gcd
# drop in RTL, edit ecc.toml (top/clock/frequency, pdk.root, flow.preset) —
# or set the declarations without opening an editor:
ecc project set design.top gcd && ecc project add design.rtl rtl/gcd.v
ecc pdk set-root ~/pdk/icsprout55-pdk   # (optional) wire in a manually downloaded PDK
ecc doctor                         # environment check (PDK/yosys/slang/components)
ecc check                          # validate the project config before running
ecc run --preset rtl2gds           # run the full chain in one shot (Synthesis→…→Harden)
ecc run                            # run again: all successful → no_op; interrupted/failed → auto-resume
ecc status                         # step status; on failure:
ecc log placement                  # the failing step's log (TEXT mode highlights error lines)
ecc param set place.target_density 0.55   # tune a parameter and re-run
ecc run --overwrite --preset rtl2gds
ecc param set place.target_density 0.65 --workspace default   # or tweak one workspace locally, no ecc.toml change
ecc run --workspace default        # continues from the invalidated step
ecc run --workspace default --only place --force   # or re-run a single step in place (--force needed once successful)
ecc run --workspace default --from CTS --to route  # or re-run a range in place (persisted names)
ecc workspace refresh default      # re-apply ecc.toml inputs/PDK/preset changes to the workspace without running
ecc config place                   # config files actually in effect for that step
ecc signoff inspect                # signoff readiness (blocked still exits 0)
ecc signoff export -o gcd_signoff.tar.gz    # export the signoff package once ready
ecc report summary                 # text design summary (signoff/<design>_design_summary.txt)
ecc report qor                     # QoR overall score report (signoff/<design>_qor_report.txt)
ecc report checklist               # signoff checklist report (signoff/checklist_report.txt)
ecc report step drc                # preview one step's feature/analysis/checklist (read-only)
ecc gdsview --workspace default --step Harden
ecc chipview --workspace default --step filler
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
ecc run --workspace pnr --from prefloorplan --to route
```

A design with hard macros can switch to manual placement instead (full contract in §9.5):

```bash
ecc macro set u_ram0 --x 10 --y 20.5 --orient R0 --workspace default
ecc run --workspace default   # resumes from macroPlacement: DreamPlace is skipped, the manual positions are committed
ecc macro show --workspace default
```

Once `project.json` exists, project-scoped inspection, signoff, and report commands select among declared workspaces; a single active workspace is auto-selected, while multiple active workspaces require an explicit `--workspace NAME` (otherwise `workspace_required` is reported, listing the available names). A workspace no longer in use can be dropped from auto-selection by changing its `status` to `archived` in `project.json`.

## 16. Automation and safety boundaries

This section adds operating rules for automation, agents, and batch experiments; the command contracts above still apply.

### 16.1 Public boundaries and state claims

- Change project, workspace, parameter, macro, PDK, run, report, and signoff state only through the public `ecc` CLI.
- Never bypass the CLI by editing `ecc.toml`, `project.json`, `home/params.toml`, `home/flow.json`, managed JSON/Tcl, analysis reports, or checklists directly.
- If the CLI does not expose a field, report the capability gap — do not invent commands or force-write internal files. Parse `--plain` output as repeated `key=value` records; it is not JSON, and never `eval` or `source` it.
- Report four things separately: CLI success, completion of the requested flow, QoR/signoff gate results, and export reproducibility. Missing data is not zero, and ECC export-ready is not foundry tapeout certification.

### 16.2 Experiments, recovery, and diagnosis

Run serially by default — never run, tune, refresh, or export the same workspace concurrently. Give every new candidate its own workspace, and record its inputs, PDK/library, tool versions, parameter overrides, seed, thread count, device, resource budget, and raw reports. Before recovering a run, look at `status`, `log`, and the ledger; prefer `--resume` or an exact range rerun, and never `--overwrite`, delete directories, or kill unrelated processes without confirmation. On failure, keep the first error and its context, then check in order: versions, project declaration, workspace registration, `doctor`, PDK/library files, entry inputs, and the failed step's log. Do not manufacture success by relaxing constraints, lowering frequency, dropping corners, or skipping verification.
### 16.3 Automation contract: exit codes and packaged smoke

`ecc signoff check` always prints its JSON records, including when a gate is not
clean. Automation should inspect both the summary record and the process exit code:
`0` means pass, `6` means a required gate failed, and `7` means the required gates
could not be rated because evidence is missing, stale, or ambiguous. Usage errors
remain `2`; the existing workspace/process codes (`20`–`23`) are unchanged.

A packaged executable can be checked against a real project without importing the
source tree:

```bash
python packaging/cli_smoke.py \
  --binary dist/ecc \
  --project /path/to/gcd \
  --workspace default
```

The smoke runner checks `status`, `report step`, `report project`, `signoff check`,
and `pdk verify`, requires each command to emit a non-empty JSON record array, and
preserves non-zero quality-gate codes for CI reporting.
