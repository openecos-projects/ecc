# CLI Design Specification

This document defines the design principles and staged roadmap for the ECC
command line interface.

The CLI should be useful to both human flow developers and agent frameworks. It
must expose a short default path for common flows, while every summary line must
also provide explicit commands for deeper inspection.

## Goals

- Provide a project-oriented interface for RTL-to-GDS workflows.
- Make step-level reruns, inspection, and debugging first-class operations.
- Keep default output concise and stable.
- Make output easy to parse with simple tools such as `rg`, `awk`, and shell
  scripts.
- Provide structured output for agents through `--json` and `--jsonl`.
- Preserve the existing Python API for advanced integration.
- Build CLI behavior as a wrapper around the current Python APIs.

## Non-Goals

- Full OpenLane or LibreLane configuration import.
- A conversational assistant as the primary CLI interface.
- Tool-specific command exposure as the default user model.
- Pretty terminal UI as the canonical output format.

## Design Principles

### Progressive Disclosure

The default command output should answer only:

- What happened?
- Did it succeed?
- What command should inspect the next level of detail?

Detailed information must be available through explicit follow-up commands.
The disclosure path is:

```text
summary -> diagnosis -> evidence -> raw data
```

Examples:

```bash
ecc status
ecc diagnose cts
ecc log cts
ecc artifacts cts
ecc config cts --resolved
```

### Disclosure Commands On Summary Lines

Every summary line must include at least one disclosure command on the same
line. This is required so agents can grep the output and continue inspection
without interpreting natural language paragraphs.

Use stable `key="command"` fields. Current run and step summary records use a
`_cmd` suffix for command-valued fields, while pretty text displays the same
fields without the suffix:

```text
step=cts status=failed runtime=0:00:37 metrics_cmd="ecc metrics cts" log_cmd="ecc log cts"
```

Do not rely on prose such as:

```text
Run ecc diagnose cts for more details.
```

The command field names should be stable across releases:

| Field | Purpose |
| --- | --- |
| `inspect` | Show detailed object state |
| `diagnose` | Explain failures or quality issues |
| `log` | Show available logs or step log content |
| `artifacts` | List output artifacts |
| `config` | Show resolved configuration |
| `metrics` | Show metrics |
| `*_cmd` | Current record suffix for command-valued variants such as `inspect_cmd`, `metrics_cmd`, `log_cmd`, and `start_cmd` |
| `open` | Open a viewer or report (planned) |

### Stable Text Output

The stable shell interface should be line-oriented and grep-friendly. Avoid box
drawing, multi-line table cells, and terminal-width-dependent formatting in that
mode.

Recommended style:

```text
run=default status=failed workspace=runs/default inspect_cmd="ecc status" metrics_cmd="ecc metrics" log_cmd="ecc log"
step=synthesis tool=yosys status=success runtime=0:00:18 metrics_cmd="ecc metrics synthesis" log_cmd="ecc log synthesis"
step=floorplan tool=ecc status=success runtime=0:00:04 metrics_cmd="ecc metrics floorplan" log_cmd="ecc log floorplan"
metric=gp_hpwl step=placement value=18423 source=Placement_ecc/analysis/place_metrics.json inspect="ecc metrics placement --json"
artifact=design.def step=placement role=output path=runs/default/Placement_ecc/output/design.def inspect="ecc artifacts placement --json" config="ecc config placement --resolved"
```

Current implementation note: `--plain` provides this stable key-value output.
The default text mode renders human-oriented pretty output with disclosure
commands. JSON and JSONL modes are unchanged.

```bash
ecc status --plain
```

Pretty output is for humans only and must not be treated as the stable parsing
interface.

### Structured Output

Every inspection command should support:

```bash
--json
--jsonl
```

Use `--json` for object-level output and `--jsonl` for stream or list output.

Example:

```jsonl
{"step":"synthesis","tool":"yosys","status":"success","runtime":"0:00:18","metrics_cmd":"ecc metrics synthesis","log_cmd":"ecc log synthesis"}
{"metric":"gp_hpwl","step":"placement","value":18423,"source":"Placement_ecc/analysis/place_metrics.json","inspect":"ecc metrics placement --json"}
```

Text output and JSON output should describe the same objects. The text output is
the human and shell interface; JSON is the strict machine interface.

Current implementation status:

| Command family | Structured options |
| --- | --- |
| `ecc init` | `--plain` |
| `ecc check` | `--json`, `--plain` |
| `ecc run`, `ecc status`, `ecc log`, `ecc metrics`, `ecc artifacts`, `ecc config`, `ecc diagnose` | `--json`, `--jsonl`, `--plain` |
| `ecc param list/show/set/unset/diff` | `--json`, `--jsonl`, `--plain` |
| `ecc version` | `--json` |
| `ecc workspace ...` | `--json` |

When multiple project output options are provided, the implementation selects
`--jsonl` first, then `--json`, then `--plain`, and otherwise renders pretty
text.

### Object-Oriented CLI Model

Commands should be organized around flow objects instead of internal tools:

| Object | Description |
| --- | --- |
| Project | User design directory and `ecc.toml` |
| Run | One execution instance with a stable run id or tag |
| Step | A flow step such as synthesis, placement, CTS, routing |
| Artifact | DEF, GDS, Verilog, SPEF, reports, logs, scripts |
| Metric | QoR values such as WNS, TNS, area, HPWL, DRC count |
| Issue | Failure or QoR problem with evidence |
| Config | User config and resolved step config |

Users should not need to understand the internal Yosys, ECC-Tools, or
DreamPlace directory layout to perform common actions.

### Python API Wrapper Boundary

The CLI must be implemented as a thin orchestration layer over the existing
Python APIs. CLI commands should compose and wrap APIs such as workspace
creation, flow construction, step execution, state inspection, metrics parsing,
and artifact discovery.

The CLI must not require invasive changes to the current flow-related APIs. In
particular, CLI implementation should avoid changing the semantics of
`EngineFlow`, `Workspace`, `WorkspaceStep`, tool plugin interfaces, or RTL-to-GDS
flow builders only to satisfy command-line concerns.

If the CLI needs behavior that is not exposed today, prefer one of these
approaches:

- Add a small, general-purpose Python API that is useful outside the CLI.
- Add a CLI-local adapter that translates current API data into CLI output
  objects.
- Add read-only inspection helpers around existing state files, reports, and
  artifacts.

Avoid embedding CLI output formatting, argument parsing, terminal behavior, or
agent-specific disclosure fields inside core flow APIs.

## Command Shape

### Core Commands

The current root surface is a Typer command graph. The project-first command
surface stays small, with version reporting and legacy workspace management
available as explicit root entries:

```bash
ecc --version
ecc version
ecc init
ecc check
ecc run
ecc status
ecc log
ecc metrics
ecc artifacts
ecc config
ecc diagnose
ecc param
ecc workspace
```

Responsibilities:

| Command | Responsibility |
| --- | --- |
| `ecc --version` | Print a single `ecc <version>` line |
| `ecc version` | Show ECC runtime and component versions |
| `ecc init` | Create a project skeleton and `ecc.toml` |
| `ecc check` | Validate RTL, constraints, PDK, tools, and config |
| `ecc run` | Execute the configured default flow |
| `ecc status` | Summarize run and step state |
| `ecc diagnose` | Explain failures or QoR problems with evidence |
| `ecc metrics` | Show run-level or step-level metrics |
| `ecc log` | Show available logs or complete step log content |
| `ecc artifacts` | List generated files and disclosure commands |
| `ecc config` | Show user or resolved configuration |
| `ecc param` | List, inspect, set, unset, and diff parameter overrides |
| `ecc workspace` | Manage legacy runtime workspaces behind an explicit namespace |

### Project-Oriented Entry

The preferred user entry should be configuration driven:

```bash
ecc init gcd
ecc check
ecc run
```

The project should contain:

```text
gcd/
├── ecc.toml
├── rtl/
├── constraints/
└── runs/
```

Command-line arguments may override configuration values, but `ecc.toml` should
be the primary user-facing interface.

Current implementation supports `--project` on project and `param` commands.
When omitted, the current working directory is treated as the project directory.

### Step-Level Execution

Back-end flow work is iterative. Step-level execution must be first-class:

```bash
ecc run --from placement
ecc run --to routing
ecc run --only cts
ecc run --after floorplan
ecc run --resume
ecc run --force --step placement
```

The current implementation does not yet expose step-range execution flags.
`ecc run` executes the configured default RTL-to-GDS flow and supports:

```bash
ecc run --overwrite
ecc run --set place.target_density=0.65
```

Each run should have a stable run id and may have a user tag:

```bash
ecc run --tag baseline
ecc run --tag dense_place
ecc diff baseline dense_place
```

The implemented run writer currently creates `runs/default`. Inspection
commands support `--run-id` for selecting `runs/<id>`, a relative run path, or
an absolute run directory:

```bash
ecc status --run-id default
ecc log cts --run-id run_005
ecc metrics cts --run-id sweeps/sweep_001/run_004
```

Run tags and `ecc diff` remain planned work.

### Parameter Management

Parameters are part of the implemented CLI surface. Project-level overrides can
be stored in `ecc.toml` under `[params]`, set persistently with `ecc param set`,
or applied to a single run with repeated `ecc run --set key=value` flags.

```bash
ecc param list
ecc param show place.target_density
ecc param set place.target_density 0.65
ecc param unset place.target_density
ecc param diff
ecc run --set synth.max_fanout=16
```

### Version Information

Version reporting is part of the implemented root surface:

```bash
ecc --version
ecc version
ecc version --json
```

`ecc --version` prints one line for package-manager and script probes. `ecc
version` prints fixed-order text lines for `ecc`, `dreamplace`, `ecc_tools`, and
`runtime`. `ecc version --json` returns schema version `1` with `runtime`,
`ecc`, `dreamplace`, and `ecc_tools` fields. Missing distribution metadata is
reported as `unknown`, except the `ecc` field may fall back to the source
package `__version__`.

### Legacy Workspace Commands

`ecc workspace` is an implemented compatibility namespace for runtime workspace
operations that predate the project-oriented `ecc.toml` workflow:

```bash
ecc workspace create
ecc workspace load
ecc workspace run-flow
ecc workspace run-step
ecc workspace get-info
ecc workspace get-home
```

The namespace preserves the server-shaped response contract:

```json
{"cmd":"create_workspace","response":"success","data":{},"message":[]}
```

Workspace commands support `--json`. `workspace create` accepts either
`--input-json` or explicit field flags such as `--directory`, `--pdk`,
`--pdk-root`, `--rtl`, `--filelist`, `--origin-def`, `--origin-verilog`,
`--param-json`, `--design`, `--top`, `--clock`, and `--freq`. Old top-level
workspace flags such as `ecc --workspace ...` are no longer accepted by the root
parser.

## Output Contracts

### Summary Line Format

Stable plain text output should follow this general shape:

```text
kind=<object-kind> key=value ... disclosure_key="ecc command ..."
```

Examples:

```text
run=default status=success workspace=runs/default inspect_cmd="ecc status" metrics_cmd="ecc metrics" log_cmd="ecc log"
step=routing tool=ecc status=failed runtime=0:03:42 metrics_cmd="ecc metrics routing" log_cmd="ecc log routing"
metric=max_wns step=cts value=-0.083 source=runs/default/CTS_ecc/analysis/CTS_metrics.json inspect="ecc metrics cts --json"
artifact=design.def step=placement role=output path=runs/default/Placement_ecc/output/design.def inspect="ecc artifacts placement --json" config="ecc config placement --resolved"
```

Rules:

- Keep one object per line.
- Do not wrap summary lines.
- Use stable lowercase keys.
- Use stable lowercase tokens for step names and metric names.
- Quote command values with double quotes.
- Commands in disclosure fields must be directly executable from the project
  root.
- Include at least one disclosure command per summary line.
- Prefer relative paths rooted at the project directory.
- Avoid terminal color as the only status indicator.

Current output modes:

| Mode | Option | Notes |
| --- | --- | --- |
| Pretty text | default | Human-oriented grouped output with disclosure commands |
| Plain text | `--plain` | Stable one-record-per-line key-value output |
| JSON | `--json` | Project and `param` JSON envelope with `records`; `version` and `workspace` use their own root-level schemas |
| JSONL | `--jsonl` | One JSON object per record |

Plain output preserves record keys exactly. Pretty text may normalize labels for
display, for example rendering `inspect_cmd` as `inspect`.

### Error Output

Errors should also follow progressive disclosure. A failing command should print
a concise summary and actionable disclosure commands:

```text
kind=error error=run_exists run=default workspace=runs/default overwrite="ecc run --overwrite"
step=routing status=unknown_step inspect="ecc status"
```

For human readability, a short paragraph may follow, but agents should be able
to use the first line alone.

### Diagnosis Output

Diagnosis must include evidence, not only suggestions:

```text
issue=log_errors severity=error run=default step=cts count=12 evidence="ecc log cts" artifacts="ecc artifacts cts"
issue=missing_metrics severity=warning run=default step=cts evidence="ecc metrics cts --json" log="ecc log cts"
issue=config_unavailable severity=info run=default step=cts evidence="ecc config cts --resolved" artifacts="ecc artifacts cts"
```

Suggestions should be traceable to metrics, reports, or logs.

## Configuration Direction

The CLI should move toward a single project configuration file:

```toml
[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/gcd.v"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "/path/to/ics55"

[flow]
preset = "rtl2gds"
run = "default"

[params.place]
target_density = 0.65
```

Current validation supports the `ics55` PDK, the `rtl2gds` flow preset, and
`flow.run = "default"`. `design.rtl` must contain exactly one entry; use a
filelist (`.f`, `.fl`, or `.filelist`) for multi-source RTL designs. If
`pdk.root` is empty, the CLI falls back to `CHIPCOMPILER_ICS55_PDK_ROOT` or
`ICS55_PDK_ROOT`.

The resolved configuration used by each step should be inspectable:

```bash
ecc config --resolved
ecc config placement --resolved
ecc param list
ecc param show place.target_density
```

The current `ecc config` command requires `--resolved`.

## AI-Native Behavior

The CLI should not start with a general chat command. It should first produce
stable structured context that agents can inspect.

Preferred data files:

```text
run.json
steps.json
metrics.json
issues.json
artifacts.json
resolved_config.json
events.jsonl
```

Agent-oriented commands can then be layered on top:

```bash
ecc diagnose
ecc explain routing
ecc suggest --goal "fix hold"
ecc summarize run latest
```

These commands must still return evidence-backed results and disclosure
commands.

## Roadmap

### Phase 1: Project And Run Basics

- [x] `ecc init`
- [x] `ecc --version`
- [x] `ecc version`
- [x] `ecc check`
- [x] `ecc run`
- [x] `ecc status`
- [x] `ecc log`
- [x] `ecc metrics`
- [x] Stable grep-friendly summary output through `--plain`
- [x] `--json` and `--jsonl` for status and metrics

Success criteria:

- [x] A user can create a project, run the default RTL-to-GDS flow, inspect status,
  inspect logs, and read metrics without writing Python.
- [x] Plain summary records include disclosure commands for follow-up
  inspection.

### Phase 2: Debug And Traceability

- [x] `ecc diagnose`
- [x] `ecc artifacts`
- [x] `ecc config --resolved`
- [x] Run selection for inspection commands with `--run-id`
- [x] Parameter overrides with `ecc param` and `ecc run --set`
- [x] Legacy workspace namespace under `ecc workspace`
- [ ] Run tags and run comparison basics
- [x] Structured issue and artifact metadata

Success criteria:

- [x] A failed step can be investigated through `ecc status -> ecc diagnose -> ecc
  log/artifacts/config`.
- [x] Agent frameworks can follow disclosure commands from `--plain`, `--json`,
  or `--jsonl` output without parsing prose.

### Phase 3: Exploration And Assistance

- [ ] `ecc diff`
- [ ] `ecc sweep`
- [ ] `ecc explain`
- [ ] `ecc suggest`
- [ ] QoR dashboards or report export

Success criteria:

- [ ] A user can compare runs, sweep key flow parameters, and receive
  evidence-backed next actions for common timing, placement, routing, and DRC
  failures.

## Compatibility Notes

The stable Python integration surface is the project-level `chipcompiler`
package and the CLI launcher entrypoint `chipcompiler.cli.main`. The launcher
delegates to the root Typer graph and `chipcompiler.cli.main.run(argv)` remains
an int-returning API. Internal CLI implementation modules under
`chipcompiler.cli.*` are not compatibility surfaces; they may move with CLI
implementation refactors. Integrations should invoke the packaged `ecc` command
or call `chipcompiler.cli.main.run(argv)` rather than importing CLI helper
modules directly.

The legacy top-level parameter-only invocation with `--workspace` is no longer
part of the CLI contract. Use `ecc workspace create --directory <dir>` with
explicit field flags such as `--design`, `--top`, `--clock`, `--freq`, `--pdk`,
and `--pdk-root` for one-line old-workspace creation. The long-term default is
project-oriented and configuration-driven through `ecc.toml` and subcommands
such as `ecc run --project <dir>`.

The project-level Python APIs should remain compatible with existing Python
users. Changes needed for the CLI should be additive and should not force
current Python flow scripts to change unless the underlying API already requires
a broader cleanup.
