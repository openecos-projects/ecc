# ECC CLI User Guide (all currently supported commands)

`ecc` is the project-oriented command-line entry point of ECOS Chip Compiler, covering the full RTL-to-GDS flow: project creation, validation, execution, status/log/config inspection, and parameter management. This guide is based on the current source tree (v0.1.0-alpha.11); all example outputs are real execution results (run states in the examples are hand-crafted demo data).

- Source code: [chipcompiler/cli/](../chipcompiler/cli/)
- For how to extend the CLI with new commands, see [ecc-cli-dev.en.md](ecc-cli-dev.en.md)
- RPC sidecar protocol: [workspace-cli.md](workspace-cli.md)

## 0. Invocation

### One-shot setup (recommended)

The repository ships an install script, [ecc-cli-setup.sh](ecc-cli-setup.sh) (in this directory): it downloads and installs the ecc CLI, configures PATH, runs an environment self-check, and fills in any missing dependencies — the PDK (icsprout55-pdk + liberty/GDS) and Yosys (latest OSS CAD Suite). It is idempotent: re-running skips anything already in place.

```bash
bash ecc-cli-setup.sh                 # install + self-check + fill in dependencies
bash ecc-cli-setup.sh --check-only    # environment check only, installs nothing
bash ecc-cli-setup.sh --force         # force reinstall of the ecc CLI
bash ecc-cli-setup.sh --skip-pdk --skip-tools   # install only the ecc CLI itself
bash ecc-cli-setup.sh --no-shell-rc   # do not touch shell rc files (by default a load line is added idempotently)
```

Configuration knobs (override via environment variables; change these when versions/URLs change — no script edits needed):

| Variable | Default | Description |
|---|---|---|
| `ECC_VERSION` | `latest` | ecc release tag (e.g. `v0.1.0-alpha.11`) |
| `ECC_RELEASE_BASE` | Official ecc Releases page | Release page URL (change for a mirror or a different repository) |
| `ECC_ASSET_NAME` | `ecc-cli-linux-x86_64.tar.gz` | Asset name (change if the layout changes) |
| `ECC_CLI_URL` | empty | Full direct URL; highest priority |
| `ECC_INSTALL_DIR` | `~/.local/ecc` | Installation directory |
| `ECC_PDK_DIR` | `~/.local/icsprout55-pdk` | PDK directory (repository URL is fixed: https://github.com/openecos-projects/icsprout55-pdk.git) |
| `ECC_OSS_CAD_DIR` | `~/.local/oss-cad-suite` | OSS CAD Suite directory (Yosys) |
| `OSS_CAD_URL` | empty | Full direct URL override for OSS CAD Suite (defaults to the latest release) |
| `GH_PROXY` | empty | GitHub download proxy prefix (e.g. `https://gh-proxy.org/`), for restricted networks |

The script produces `~/.ecc-env.sh` (PATH + `CHIPCOMPILER_ICS55_PDK_ROOT` + `CHIPCOMPILER_OSS_CAD_DIR`), idempotently makes `~/.bashrc`/`~/.zshrc` load it, and creates a `~/.local/bin/ecc` symlink. Example for a restricted network:

```bash
GH_PROXY=https://gh-proxy.org/ bash ecc-cli-setup.sh
```

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

> Note the difference between the **official release** and a **source-built bundle**: the newer commands (`ecc doctor / signoff / report`) currently exist only in source-built bundles (they have not shipped in an official Release yet). After local code changes you can rebuild with PyInstaller and overwrite `~/.local/ecc` (procedure in [ecc-cli-dev.en.md §6](ecc-cli-dev.en.md)); re-running `bash ecc-cli-setup.sh --force` reinstalls the official release (the new commands disappear with it — that is the expected rollback behavior).

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
- Project location: most commands accept `--project <dir>` (defaults to the current directory, which must contain `ecc.toml`) and `--run-id <id>` (defaults to `[flow] run` from `ecc.toml`, then `default`, mapping to `runs/<id>/`; absolute paths and relative paths containing `/` are also accepted).
- Output modes (shared by inspection commands): `--json` (`{"records":[...]}`), `--jsonl` (one JSON record per line), `--plain` (`key=value`, for scripting), and human-readable TEXT by default.
- Exit codes: 0 on success; 1 on business failure (error records look like `[error] error=<machine-readable-code>`).
- Step tokens are normalized to lowercase in display: `synthesis / floorplan / placement / cts / legalization / routing / drc / lvs / filler / postroutelec / rcx / sta / harden`; `--from`/`--only` require the exact names from `home/flow.json` (e.g. `place`, `CTS`).

Command overview:

```
$ ecc --help
Commands:
  version       Show ECC runtime and component versions
  layout-image  Render a GDS file into a layout image
  init          Create a new ECC project
  check         Validate the current project setup
  run           Run the configured RTL-to-GDS flow
  status        Show run and step status
  log           Show available logs or step log content
  config        Show resolved project or step configuration
  doctor        Check host environment: PDK, tools, and components
  param         Manage EDA parameters
  pdk           Show and configure the PDK path used by this project
  signoff       Inspect and export signoff packages
  report        Generate QoR score and signoff checklist reports
  rpc           Run the private ECC JSON-RPC runtime
```

## 2. version — show versions

```bash
ecc version          # text
ecc version --json   # JSON (schema_version/ecc/dreamplace/ecc_tools/tools)
ecc --version        # single ecc version line
```

The first four lines are bundle metadata (Python package versions). The
`yosys` / `sizer` / `klayout` lines are resolved from the environment the
same way a flow run resolves them, and show the binary's own version, or
`not installed` / `unknown` when it is absent or cannot report one.

```console
$ ecc version
ecc 0.1.0-alpha.11
dreamplace 0.1.0a7
ecc_tools 0.1.0a11
runtime ECC CLI
yosys 0.68+132
sizer not installed
klayout 0.30.2

$ ecc version --json
{"schema_version": 1, "runtime": "ECC CLI", "ecc": "0.1.0-alpha.11", "dreamplace": "0.1.0a7", "ecc_tools": "0.1.0a11", "tools": {"yosys": "0.68+132", "sizer": "not installed", "klayout": "0.30.2"}}
```

## 3. init — create a project

```bash
ecc init <NAME> [--plain]
```

Creates an `ecc.toml`, `rtl/`, `constraints/`, and `runs/` skeleton under `NAME/`:

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
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"           # ics55 is the currently supported PDK
root = ""                # icsprout55-pdk path; empty falls back to CHIPCOMPILER_ICS55_PDK_ROOT / ICS55_PDK_ROOT

[flow]
# preset: rtl2gds | rcx | harden | syn_sta
preset = "rtl2gds"
run = "default"          # run id, maps to runs/<id>/
```

## 4. check — validate the project configuration

```bash
ecc check [--project DIR] [--json | --plain]
```

Validates required `ecc.toml` fields, RTL path/filelist validity, and the PDK name and contents (tech LEF/LEF/liberty):

```console
$ ecc check        # while RTL is not ready
[check]
  fail pdk.root is required
  inspect: ecc check --json
  fail rtl path does not exist: rtl/gcd.v
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

`ecc doctor` checks every dependency in one command (PDK, yosys including the slang frontend, bundled ecc-tools/dreamplace, optional klayout/sizer), reporting pass/fail/skip per component with remediation hints; only **required** failures produce a non-zero exit:

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

In addition, `ecc run` preflights the tools required by the chosen preset (yosys ↔ presets containing synthesis, dreamplace ↔ placement/legalization) and fails fast when any is missing:

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

- PDK root resolution priority: `pdk.root` in `ecc.toml` > `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT`.
- The synthesis step still fails fast internally on slang problems (the log reports `yosys slang frontend check failed`); inspect afterwards with `ecc log synthesis`.
- Setup/repair script: `bash docs/ecc-cli-setup.sh` (see section 0; `--check-only` checks only).

### Manual checklist (fallback when doctor is unavailable)

`ecc check` covers "project config + RTL + **PDK contents** (tech LEF / LEF / liberty)" but **not external tools**. Verify manually:

| Dependency | Check command | Ready when |
|---|---|---|
| Python components (ecc-tools / dreamplace, bundled with the CLI) | `ecc version` | `ecc_tools` / `dreamplace` show a version instead of `unknown` |
| PDK (ics55) | `ecc check` | `status: checked`; if liberty is missing run `make unzip` per the README |
| Yosys (synthesis) | `which yosys && yosys -V`, or `echo $CHIPCOMPILER_OSS_CAD_DIR` | either works (`CHIPCOMPILER_OSS_CAD_DIR` pointing at OSS CAD Suite takes priority) |
| Yosys slang frontend | `yosys -Q -T -p "help read_slang"` | output does **not** contain `No such command` (builtin since yosys ≥ v0.67; older builds need a loadable slang plugin) |
| KLayout (only needed by `layout-image`) | `python3 -c "from klayout import lay"` | no ImportError |
| Sizer (only needed by some flows) | `which Sizer` | prints a path |

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

- PDK root resolution priority: `pdk.root` in `ecc.toml` > `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT`.
- ECC-Tools / DreamPlace ship as Python wheels (`ecc-tools-bin`, `ecc-dreamplace`) bundled in the CLI package; a normal install is all they need.

## 5. run — execute a flow

### 5.1 Project mode (regular)

```bash
ecc run [OPTIONS]
  --project TEXT     project directory (defaults to cwd)
  --run-id TEXT      run id (defaults to [flow] run / default)
  --preset TEXT      flow preset override for this run only (not written back to ecc.toml), e.g. --preset harden
  --overwrite        overwrite an existing run (only deletes genuine ECC run directories, with safety checks)
  --set KEY=VALUE    parameter override, repeatable (e.g. --set place.target_density=0.65), recorded in the run provenance
  --json / --jsonl / --plain
```

Pipeline: read `ecc.toml` → resolve RTL/PDK/parameters → preflight the preset's required tools → create the workspace under `runs/<run-id>/` → build and execute the steps for the preset (`rtl2gds | rcx | harden | syn_sta | synthesis_lec`; progress rendering on a TTY). `harden` is the full 13-step chain (Synthesis→…→DRC→LVS→filler→postRouteLec (Yosys equivalence check)→RCX→sta→Harden; Harden emits GDS + abstract LEF + timing LIB).

```console
$ ecc run                # refuses to overwrite an existing run
[error]
  run_exists
  run: default
  workspace: /path/gcd/runs/default
  overwrite: ecc run --overwrite
rc=1

$ ecc run --preset bogus  # invalid preset (ecc.toml is not modified)
[error]
  unsupported_preset
  preset: bogus
  presets: harden, rcx, rtl2gds, syn_sta, synthesis_lec
  inspect: ecc config --resolved
rc=1
```

Typical usage:

```bash
ecc run                                        # first run (uses the preset from ecc.toml)
ecc run --preset harden                        # run all the way to Harden in one shot (GDS/LEF/LIB)
ecc run --run-id exp1 --set place.target_density=0.65
ecc run --run-id exp1 --overwrite              # re-run a run of the same name
```

### 5.2 Workspace mode (debugging / re-runs)

```bash
ecc run --workspace <dir> [--resume | --from STEP | --only STEP [--force]]
```

- `--resume`: continue from the first non-successful step (the default when no selector is given);
- `--from STEP`: re-run a step and every step after it;
- `--only STEP [--force]`: run exactly one step; `--force` re-runs it even if it already succeeded;
- the three selectors are mutually exclusive; `--workspace` cannot be combined with `--project/--run-id/--overwrite/--set/--preset`; STEP names must match `home/flow.json` exactly (e.g. `place`, `CTS`);
- the workspace is modified in place: the re-run steps' `output/` is replaced and downstream steps are marked `Unstart`.

```bash
ecc run --workspace runs/default --resume
ecc run --workspace runs/default --from CTS
ecc run --workspace runs/default --only place --force
```

Using a selector in project mode by mistake gives a clear error:

```console
$ ecc run --resume
[error]
  selector_requires_workspace
rc=1
```

## 6. status — show run and step status

```bash
ecc status [--project DIR] [--run-id ID] [--json | --jsonl | --plain]
```

```console
$ ecc status
[status]
  run: default
  status: failed
  workspace: /tmp/gcd/runs/default
  inspect: ecc status
  log: ecc log

  steps:
    synthesis (yosys) success 0:00:18
      log: ecc log synthesis
    floorplan (ecc) success 0:00:04
      log: ecc log floorplan
    placement (dreamplace) incomplete 0:00:31
      log: ecc log placement
    cts (ecc) unstart

$ ecc status --jsonl
{"run": "default", "status": "failed", "workspace": "/tmp/gcd/runs/default", "inspect_cmd": "ecc status", "log_cmd": "ecc log"}
{"step": "synthesis", "tool": "yosys", "status": "success", "runtime": "0:00:18", "log_cmd": "ecc log synthesis"}
{"step": "floorplan", "tool": "ecc", "status": "success", "runtime": "0:00:04", "log_cmd": "ecc log floorplan"}
...
```

The run-level status aggregates all steps: `success / failed / ongoing / unstart / missing / corrupt`.

## 7. log — view logs

```bash
ecc log [STEP] [--project DIR] [--run-id ID] [--json | --jsonl | --plain]
```

Without STEP it lists all log files (with a tail preview); with STEP it prints that step's log content (TEXT mode highlights ERROR/WARNING lines).

```console
$ ecc log
[logs]
  synthesis  Synthesis_yosys/log/synthesis.log
    tail:
      synthesizing gcd...
  inspect: ecc log synthesis

$ ecc log synthesis
[log] step=synthesis
  source: Synthesis_yosys/log/synthesis.log
        synthesizing gcd...
  inspect: ecc log synthesis

$ ecc log nosuchstep
[error]
  error
  step: nosuchstep
  status: unknown_step
  inspect: ecc status
rc=1
```

## 8. config — view the resolved configuration

```bash
ecc config [STEP] --resolved [--project DIR] [--run-id ID] [--json | --jsonl | --plain]
```

`--resolved` is required. Without STEP it prints the project-level configuration (`ecc.toml` keys + resolved absolute paths); with STEP it lists the configuration files actually in effect for that step under `runs/<id>/config/`.

```console
$ ecc config --resolved --plain    # project level (excerpt)
config=design.name scope=project value=gcd resolved=gcd source=ecc.toml
config=design.top scope=project value=gcd resolved=gcd source=ecc.toml
config=pdk.name scope=project value=ics55 resolved=ics55 source=ecc.toml
...

$ ecc config floorplan --resolved  # step level
[config]
  step:
    db_ecc.json (config)
      path: runs/default/config/db_ecc.json
  inspect: ecc config floorplan --resolved --json
    floorplan_ecc.json (config)
      path: runs/default/config/floorplan_ecc.json
  inspect: ecc config floorplan --resolved --json
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

Priority: CLI `--set` > `ecc.toml` `[params.*]` > template defaults. `pdk.*` path parameters write to `[pdk.overrides]` and retain the PDK's relative-path resolution and file validation.

## 10. pdk — PDK path configuration

Two ways to attach a PDK: `ecc pdk setup` does everything (auto clone + `make unzip`,
skipping downloads for an already-complete checkout), or `ecc pdk set-root` wires in
a ready-made checkout directly — `[pdk] root` in `ecc.toml` (the path is expanded to
absolute form; the directory must already exist). Incomplete contents (e.g.
`make unzip` not run yet) do not block the setting — a hint is emitted instead:

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

The resolution priority is unchanged: `ecc.toml [pdk] root` > `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT` > the in-repo default. Keep `pdk.root` on `ecc pdk set-root`; `pdk.tech`, `pdk.lefs`, `pdk.libs`, `pdk.mapping_file`, `pdk.sdc`, and `pdk.spef` use `ecc param set KEY VALUE`, which writes `[pdk.overrides]`.

## 11. signoff — signoff package and design report

Use after the flow completes (all steps of the harden preset in Success). All three subcommands accept `--project DIR`/`--run-id ID` (locating `runs/<id>`) or `--workspace PATH` (pointing at a workspace directly), plus `--json/--jsonl/--plain`.

### 11.1 inspect — readiness review (changes nothing)

```bash
ecc signoff inspect [--project DIR | --workspace PATH]
```

Prints the signoff package readiness status (`ready / attention / blocked`), the seven groups (initial/config/harden/final_design/sta/spef/reports), and the risk list. **blocked still exits with rc=0** (inspection is advisory; the gate lives in export):

```console
$ ecc signoff inspect --workspace runs/default
[signoff]
  status    : blocked
  workspace : runs/default
  export    : ecc signoff export -o <path>
  report    : ecc signoff report

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
ecc signoff export -o <path>.tar.gz [--include-debug] [--project DIR | --workspace PATH]
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

### 11.3 report — text design summary

```bash
ecc signoff report [-o PATH] [--project DIR | --workspace PATH]
```

Generates a design summary with the same layout as the GUI's "export report (text)" (8 sections: physical / timing / clock / multi-corner / routing / power / verification / execution cost), by default written to `<workspace>/signoff/<design>_design_summary.txt`:

```console
$ ecc signoff report --project gcd
[status]
  signoff: report
  status: written
  path: /path/gcd/runs/default/signoff/gcd_design_summary.txt
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

Notes: inspect/export refresh each step's analysis first (matching the GUI); report extracts the current state by default (the engine API `generate_text_report(workspace, refresh_analysis=True)` requests a refresh). The report does not require a completed flow — it summarizes whatever has run so far.

## 12. report — QoR score and checklist reports

```bash
ecc report qor        [-o PATH] [--project DIR | --run-id ID | --workspace PATH]
ecc report checklist  [-o PATH] [same options]
```

### 12.1 qor — overall QoR score report

Scores the current workspace by the GUI project-dashboard rules: every v3 `qor_metrics.json` metric is converted to 0-100 against fixed fail thresholds (slack metrics linearly, core_utilization against the [0.45, 0.70] target window, lower/higher_is_better proportionally), averaged per dimension, then combined with the dimension weights (Timing 0.35 / Power 0.25 / Routability 0.2 / Area 0.1 / Clock-DFM 0.1) into the overall score — **absent dimensions are not renormalized** (matching the GUI; missing dimensions lower the score); 60 is the pass line. By default written to `<workspace>/signoff/<design>_qor_report.txt`:

```console
$ ecc report qor --project gcd --plain
report=qor path=.../signoff/gcd_qor_report.txt bytes=1717 design=gcd \
  overall_score=61.8 qor_status=Green gate_status=pass \
  dimensions="[{'dimension': 'Timing', 'score': 75.0, 'weight': 0.35, 'metrics': 2}, ...]" \
  view="cat .../gcd_qor_report.txt" status=written
```

The report contains: the overall score and verdict (PASS/BELOW THRESHOLD/NOT RATED), the flow status color (Green/Yellow/Orange/Red/Blocked) and gate (DRC/LVS/RCX/STA step states), the area scoring step (the last successful step carrying area metrics), the dimension table, and the per-metric detail (corners scored independently).

### 12.2 checklist — signoff checklist report

Reads `home/checklist.json` (the schema-v3 signoff checklist maintained by flow steps / `ecc signoff inspect`) and renders a status report: the overview (passed/blocked/attention/unavailable), **BLOCKED item details** (with failure reasons and evidence paths), ATTENTION items, and the full table. When the checklist does not exist it returns `checklist_unavailable`. By default written to `<workspace>/signoff/checklist_report.txt`.

```bash
ecc signoff inspect --project gcd    # refresh the checklist first (if not present yet)
ecc report checklist --project gcd
```

## 13. rpc — JSON-RPC runtime sidecar (private)

```bash
ecc rpc serve --stdio [--persistent-db]
```

A JSON-RPC 2.0 service for front ends such as the GUI, framed with `Content-Length` over stdio. `--persistent-db` additionally exposes the `db.ensure` / `db.release` methods. Handshake and call examples (full method list and parameters in [workspace-cli.md](workspace-cli.md)):

```console
→ {"jsonrpc":"2.0","method":"rpc.hello","params":{"version":1},"id":"hello-1"}
← {"jsonrpc":"2.0","result":{"version":1,"eccVersion":"0.1.0-alpha.11","capabilities":["rpc.hello","rpc.ping","rpc.shutdown","runtime.v2","operation.events","workspace.create","workspace.open","workspace.close","workspace.home","workspace.info","workspace.refresh_config","workspace.sync_config","workspace.reset_flow","workspace.export_signoff","workspace.inspect_signoff","flow.run","flow.run_step","operation.start_flow","operation.start_step","operation.status","operation.cancel","operation.ack_step_rendered","workspace.snapshot"]},"id":"hello-1"}

→ {"jsonrpc":"2.0","method":"rpc.ping","params":{},"id":"ping-1"}
← {"jsonrpc":"2.0","result":{"ok":true},"id":"ping-1"}
```

## 14. layout-image — render a GDS to an image

```bash
ecc layout-image --gds <in.gds> --image <out.png> [--width N] [--height N]
```

Renders a GDS layout snapshot via KLayout (default 1920×1920; KLayout must be available):

```bash
ecc layout-image --gds runs/default/GDS_ecc/result.gds --image layout.png --width 2560 --height 1600
```

## 15. Typical end-to-end workflow

```bash
ecc init gcd && cd gcd
# drop in RTL, edit ecc.toml (top/clock/frequency, pdk.root, flow.preset)
ecc pdk set-root ~/pdk/icsprout55-pdk   # (optional) wire in a manually downloaded PDK
ecc doctor                         # environment check (PDK/yosys/slang/components)
ecc check                          # validate the project config before running
ecc run --preset harden            # run the full chain in one shot (Synthesis→…→Harden)
ecc status                         # step status; on failure:
ecc log place                      # the failing step's log (TEXT mode highlights error lines)
ecc param set place.target_density 0.55   # tune a parameter and re-run
ecc run --overwrite --preset harden
ecc run --workspace runs/default --only place --force   # or re-run a single step in place
ecc config place --resolved        # config files actually in effect for that step
ecc signoff inspect                # signoff readiness (blocked still exits 0)
ecc signoff export -o gcd_signoff.tar.gz    # export the signoff package once ready
ecc signoff report                 # text design summary (signoff/<design>_design_summary.txt)
ecc report qor                     # QoR overall score report (signoff/<design>_qor_report.txt)
ecc report checklist               # signoff checklist report (signoff/checklist_report.txt)
ecc layout-image --gds runs/default/Harden_ecc/result.gds --image gcd.png
```

Comparing multiple runs:

```bash
sed -i 's/^run = "default"/run = "exp1"/' ecc.toml   # or simply pass --run-id exp1
ecc run --run-id exp1 --set place.target_density=0.65
ecc status --run-id exp1
ecc log --run-id exp1
```
