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
summary -> evidence -> raw data
```

Examples:

```bash
ecc status
ecc log cts
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
step=cts status=failed runtime=0:00:37 log_cmd="ecc log cts"
```

Do not rely on prose such as:

```text
Run the log command for more details.
```

The command field names should be stable across releases:

| Field | Purpose |
| --- | --- |
| `inspect` | Show detailed object state |
| `log` | Show available logs or step log content |
| `config` | Show resolved configuration |
| `*_cmd` | Current record suffix for command-valued variants such as `inspect_cmd`, `log_cmd`, and `start_cmd` |
| `open` | Open a viewer or report (planned) |

### Stable Text Output

The stable shell interface should be line-oriented and grep-friendly. Avoid box
drawing, multi-line table cells, and terminal-width-dependent formatting in that
mode.

Recommended style:

```text
run=default status=failed workspace=runs/default inspect_cmd="ecc status" log_cmd="ecc log"
step=synthesis tool=yosys status=success runtime=0:00:18 log_cmd="ecc log synthesis"
step=floorplan tool=ecc status=success runtime=0:00:04 log_cmd="ecc log floorplan"
config=place_default_config.json scope=step step=placement role=config path=runs/default/config/place_default_config.json inspect="ecc config placement --resolved --json"
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
{"step":"synthesis","tool":"yosys","status":"success","runtime":"0:00:18","log_cmd":"ecc log synthesis"}
{"config":"place_default_config.json","scope":"step","step":"placement","role":"config","path":"runs/default/config/place_default_config.json","inspect":"ecc config placement --resolved --json"}
```

Text output and JSON output should describe the same objects. The text output is
the human and shell interface; JSON is the strict machine interface.

Current implementation status:

| Command family | Structured options |
| --- | --- |
| `ecc init` | `--plain` |
| `ecc check` | `--json`, `--plain` |
| `ecc run`, `ecc status`, `ecc log`, `ecc config` | `--json`, `--jsonl`, `--plain` |
| `ecc param list/show/set/unset/diff` | `--json`, `--jsonl`, `--plain` |
| `ecc version` | `--json` |

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
surface stays small, with version reporting and the private runtime sidecar
available as explicit root entries:

```bash
ecc --version
ecc version
ecc init
ecc check
ecc run
ecc status
ecc log
ecc config
ecc param
ecc rpc
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
| `ecc log` | Show available logs or complete step log content |
| `ecc config` | Show user or resolved configuration |
| `ecc param` | List, inspect, set, unset, and diff parameter overrides |
| `ecc rpc` | Serve the private JSON-RPC runtime sidecar over stdio |

The former standalone metrics, artifact listing, and diagnosis commands are no
longer part of the public root command surface. Metrics files and generated
artifacts remain part of the workspace data model and flow outputs.

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
ecc config cts --resolved --run-id sweeps/sweep_001/run_004
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

### Runtime Sidecar RPC

Workspace operations are no longer exposed as a compatibility command namespace.
The supported runtime surface is the private stdio sidecar:

```bash
ecc rpc serve --stdio
ecc rpc serve --stdio --persistent-db
```

The sidecar uses JSON-RPC 2.0 payloads framed with `Content-Length` headers.
After `workspace.create` or `workspace.open`, follow-up calls use the returned
`workspaceId` rather than repeatedly passing the workspace directory. The
default sidecar does not advertise or persist native DB handles.

First-slice runtime methods include:

```text
rpc.hello
rpc.ping
rpc.shutdown
workspace.create
workspace.open
workspace.close
workspace.home
workspace.info
workspace.refresh_config
workspace.sync_config
workspace.reset_flow
flow.run
flow.run_step
```

`--persistent-db` is an opt-in process capability. When enabled, `rpc.hello`
also advertises:

```text
db.ensure
db.release
```

These DB methods are not part of the default first-slice method list. They start
and stop session-scoped DB reuse explicitly; `workspace.open`,
`workspace.create`, `flow.run`, and `flow.run_step` must not start persistent DB
reuse for a session that has not called `db.ensure`.

The former custom workspace JSON object is not part of the supported output
contract. See `docs/workspace-cli.md` for framing examples and method payloads.

## Output Contracts

### Summary Line Format

Stable plain text output should follow this general shape:

```text
kind=<object-kind> key=value ... disclosure_key="ecc command ..."
```

Examples:

```text
run=default status=success workspace=runs/default inspect_cmd="ecc status" log_cmd="ecc log"
step=routing tool=ecc status=failed runtime=0:03:42 log_cmd="ecc log routing"
config=rt_default_config.json scope=step step=routing role=config path=runs/default/config/rt_default_config.json inspect="ecc config routing --resolved --json"
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
preset = "rtl2gds" # rtl2gds | rcx | harden | syn_sta
run = "default"

[params.place]
target_density = 0.65
```

Current validation supports the `ics55` PDK and `flow.run = "default"`. Valid
flow presets are discovered from the `build_*_flow` defs in
`chipcompiler/rtl2gds/builder.py` (currently `rtl2gds`, `rcx`, `harden`, and
`syn_sta`). The preset selects the flow builder: `rcx` appends the RCX and STA
steps to the rtl2gds flow, `harden` additionally appends the Harden step, and
`syn_sta` runs synthesis only, with a best-effort netlist-level STA report
(an STA failure does not fail the step). Switching
presets on an existing run requires `ecc run --overwrite` to rebuild the
workspace.
`design.rtl` must contain exactly one entry; use a
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
- [x] Stable grep-friendly summary output through `--plain`
- [x] `--json` and `--jsonl` for status, log, run, config, and param commands

Success criteria:

- [x] A user can create a project, run the default RTL-to-GDS flow, inspect status,
  and inspect logs without writing Python.
- [x] Plain summary records include disclosure commands for follow-up
  inspection.

### Phase 2: Debug And Traceability

- [x] `ecc config --resolved`
- [x] Run selection for inspection commands with `--run-id`
- [x] Parameter overrides with `ecc param` and `ecc run --set`
- [x] Private runtime sidecar under `ecc rpc serve --stdio`
- [ ] Run tags and run comparison basics

Success criteria:

- [x] A failed step can be investigated through status, log, and resolved config
  output.
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
part of the CLI contract. Old-workspace automation should use the private
JSON-RPC runtime sidecar, open or create a workspace session, and pass the
returned `workspaceId` to follow-up runtime calls. The long-term default is
project-oriented and configuration-driven through `ecc.toml` and subcommands
such as `ecc run --project <dir>`.

The project-level Python APIs should remain compatible with existing Python
users. Changes needed for the CLI should be additive and should not force
current Python flow scripts to change unless the underlying API already requires
a broader cleanup.
