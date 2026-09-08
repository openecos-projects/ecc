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
ecc config cts
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
workspace_id=default status=failed workspace=gcd/default inspect_cmd="ecc status" log_cmd="ecc log"
step=synthesis tool=yosys status=success runtime=0:00:18 log_cmd="ecc log synthesis"
step=floorplan tool=ecc status=success runtime=0:00:04 log_cmd="ecc log floorplan"
config=place_default_config.json scope=step step=placement role=config path=gcd/default/config/place_default_config.json inspect="ecc config placement --json"
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
{"config":"place_default_config.json","scope":"step","step":"placement","role":"config","path":"gcd/default/config/place_default_config.json","inspect":"ecc config placement --json"}
```

Text output and JSON output should describe the same objects. The text output is
the human and shell interface; JSON is the strict machine interface.

Current implementation status:

| Command family | Structured options |
| --- | --- |
| `ecc init` | `--json`, `--jsonl`, `--plain` |
| `ecc check`, `ecc doctor` | `--json`, `--jsonl`, `--plain` |
| `ecc run`, `ecc status`, `ecc log`, `ecc config`, `ecc migrate` | `--json`, `--jsonl`, `--plain` |
| `ecc param list/show/set/unset/diff` | `--json`, `--jsonl`, `--plain` |
| `ecc pdk setup/set-root/show/unset` | `--json`, `--jsonl`, `--plain` |
| `ecc signoff inspect/export` | `--json`, `--jsonl`, `--plain` |
| `ecc report summary/qor/checklist/step` | `--json`, `--jsonl`, `--plain` |
| `ecc version` | `--json`, `--jsonl`, `--plain` |
| `ecc rpc serve` | none (machine protocol) |
| `ecc layout-image` | none (tool invocation; produces a file) |

When multiple project output options are provided, the implementation selects
`--jsonl` first, then `--json`, then `--plain`, and otherwise renders pretty
text.

### Object-Oriented CLI Model

Commands should be organized around flow objects instead of internal tools:

| Object | Description |
| --- | --- |
| Project | User design directory and `ecc.toml` |
| Workspace | One managed execution environment identified by its project-local name |
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
ecc doctor
ecc run
ecc status
ecc log
ecc config
ecc migrate
ecc param
ecc pdk
ecc project
ecc workspace
ecc signoff
ecc report
ecc rpc
ecc layout-image
```

Responsibilities:

| Command | Responsibility |
| --- | --- |
| `ecc --version` | Print a single `ecc <version>` line |
| `ecc version` | Show ECC runtime and component versions |
| `ecc init` | Create a project skeleton and `ecc.toml` |
| `ecc check` | Validate RTL, constraints, PDK, tools, and config |
| `ecc doctor` | Probe host environment (PDK, yosys+slang, bundled tools); optional failures do not exit non-zero |
| `ecc run` | Execute the configured flow (`--preset` overrides `[flow] preset` for one run) |
| `ecc status` | Summarize run and step state |
| `ecc log` | Show available logs or complete step log content |
| `ecc config` | Show the resolved project or step configuration |
| `ecc migrate` | Migrate a legacy `runs/` project to the manifest layout |
| `ecc param` | List, inspect, set, unset, and diff parameter overrides |
| `ecc pdk` | `setup` clones + `make unzip`s + wires in a PDK checkout; also `set-root`/`show`/`unset` for the `[pdk] root` path |
| `ecc project` | Edit declared design, PDK, and flow resource fields in `ecc.toml` |
| `ecc workspace` | Refresh a declared workspace from current `ecc.toml` without running it |
| `ecc signoff` | Inspect package readiness and export the tar.gz package |
| `ecc report` | Write design-summary, QoR, and checklist reports; show step evidence |
| `ecc rpc` | Serve the private JSON-RPC runtime sidecar over stdio |
| `ecc layout-image` | Render a GDS file into an image |

`ecc run` preflights the tools its preset needs (yosys for synthesis,
dreamplace for placement/legalization, ecc-tools always) and fails with
`env_not_ready` before creating a workspace. `ecc signoff inspect` is
advisory — a blocked readiness review still exits 0; `ecc signoff export`
enforces completeness (`signoff_incomplete` on missing required resources).

The former standalone metrics, artifact listing, and diagnosis commands are no
longer part of the public root command surface. Metrics files and generated
artifacts remain part of the workspace data model and flow outputs.

### Interface Conventions

The public command graph is organized by the resource it owns rather than by
implementation detail:

| Group | Subcommands | Scope |
| --- | --- | --- |
| `ecc signoff` | `inspect`, `export` | Signoff package readiness and archive generation |
| `ecc report` | `summary`, `qor`, `checklist`, `step` | File reports and per-step evidence viewing |
| `ecc pdk` | `setup`, `set-root`, `show`, `unset` | Project PDK configuration |
| `ecc param` | `list`, `show`, `set`, `unset`, `diff` | Project parameter overrides |
| `ecc project` | `set`, `unset`, `add`, `remove`, `show` | Project design, PDK, and flow declarations in `ecc.toml` |
| `ecc workspace` | `refresh` | Recreate one declared workspace from `ecc.toml`, without execution |

Commands that consume a workspace use `--project DIR` (default: current
directory) and, when selection matters, `--workspace NAME`. The name resolves
only through the project's `project.json`; it is not a direct filesystem path.
Run-scoped inspection and reporting commands (`run`, `status`, `log`,
`config`, `report *`, `signoff *`) may combine the two options, and the read-only
commands (`status`, `log`, `config`, `report step`) never load or mutate the
workspace. Record-producing commands use default human text,
`--plain` for stable key-value records, `--json` for a record envelope, and
`--jsonl` for one record per line. Commands that only create, configure, or
serve a process expose only the options meaningful for that operation.

### Unified CLI Standard

The command graph follows these rules; new commands must follow them too:

- **Architecture.** Top-level commands are workflow-scale verbs (`init`,
  `check`, `run`, `status`, `log`, `config`, `doctor`, `migrate`, `version`)
  plus the frozen tool invocations (`layout-image`). Resource management and
  reporting live in noun groups (`param`, `pdk`, `project`, `workspace`,
  `signoff`, `report`, `rpc`).
- **Subcommand verbs.** Mutable resources use the CRUD set
  (`list`, `show`, `set`, `unset`, `diff`, plus `setup` for pdk). The `report`
  group names its artifacts instead (`summary`, `qor`, `checklist`, `step`)
  because `report <artifact>` reads as one action.
- **Naming.** Lowercase single words; multi-word names use kebab-case
  (`set-root`, `layout-image`). Help strings start with an imperative verb.
- **Selectors.** `--workspace NAME` selects a declared or newly-created
  project-local workspace and may be combined with `--project`. File-producing
  commands use `-o/--output`.
- **Status vs full evidence.** `ecc status` is the lightweight progress check;
  `ecc report step` is the full per-step evidence report (features, analysis,
  checklist). Both are read-only.
- **Module layout.** One handler package (`cli/command_handlers/`), command
  registration in `cli/commands/`, framework in `cli/core/`, read-only probing
  in `cli/inspection/`, all rendering in `cli/rendering/` behind a single
  registry keyed by full command path (top-level name, or `group:sub`).
- **Frozen surfaces.** The GUI invokes `ecc rpc serve --stdio
  [--persistent-db]`, `ecc version --json` (schema: `schema_version`, `runtime`,
  `ecc`, `dreamplace`, `ecc_tools`, `tools`), the `ecc --version` single line,
  and `ecc layout-image --gds <gds> --image <png>` as subprocess contracts.
  Additive optional flags are allowed; these names, flags, and output schemas
  must not change.

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
├── project.json       # written when the first workspace is registered
└── default/           # the default managed workspace after `ecc run`
```

Command-line arguments may override configuration values, but `ecc.toml` should
be the primary user-facing interface.

Current implementation supports `--project` on project and `param` commands;
workspace-consuming commands accept a managed `--workspace NAME` in that
project.
When omitted, the current working directory is treated as the project directory.

### Step-Level Execution

Back-end flow work is iterative. An existing managed workspace can be resumed
or re-executed in place:

```bash
ecc run --workspace default
ecc run --workspace default --resume
ecc run --workspace default --from CTS --to route
ecc run --workspace default --only place
ecc run --workspace default --only place --force
```

Step names and order come from the workspace's persisted `home/flow.json`.
Omitting a selector has resume semantics: execution starts at the first step
whose state is not `Success` and reuses the successful prefix. `--from <step>`
re-executes the named step and its persisted suffix; with `--to <step>` it
executes the inclusive range. `--only <step>` runs exactly that step; an
already successful step is a no-op unless `--force` is given. Re-executing a
step marks downstream steps `Unstart` while retaining their output files.

`--resume`, `--only`, and a range are mutually exclusive; `--force` requires
`--only`. A new bounded workspace requires both `--from` and `--to` and cannot
combine with `--preset`, `--overwrite`, `--resume`, `--only`, or `--force`.
The builder dynamically slices the canonical RTL-to-GDS flow for that range.
`--workspace` is a project-local single path segment and can be combined with
`--project`; no direct workspace paths or run ids are supported. Bare `ecc run`
creates `default` for a project with no workspace, resumes its sole active
workspace, and reports `workspace_required` when several are active.

### Parameter Management

Parameters are part of the implemented CLI surface. Legacy semantic parameters
and reviewed static tool-template fields share `ecc param`. Project-level
overrides are stored in `ecc.toml` under nested `[params.*]` tables, set
persistently with `ecc param set`, or applied to a single run with repeated
`ecc run --set key=value` flags. The concise default listing shows legacy
parameters and explicit overrides; `--step <owner>` and `--all` enumerate the
reviewed direct schemas.

```bash
ecc param list
ecc param list --step cts
ecc param list --all
ecc param show place.target_density
ecc param set place.target_density 0.65
ecc param set cts.skew_bound 0.05
ecc param set cts.routing_layer '[4, 5]'
ecc param unset place.target_density
ecc param diff
ecc param set place.target_density 0.65 --workspace baseline
ecc param diff --workspace baseline
ecc run --set cts.max_fanout=16
```

With `--workspace NAME`, `ecc param` changes only the selected existing
workspace's `home/params.toml`. It immediately refreshes the generated
configuration and invalidates the owning flow step plus its suffix, but does
not run those steps. PDK resource paths and references require a complete
reconstruction instead:

```bash
ecc project set design.def inputs/gcd.def
ecc project set design.sdc constraints/gcd.sdc
ecc project set design.rtl rtl/gcd.sv rtl/alu.sv
ecc project add design.rtl rtl/fifo.sv
ecc project set pdk.root /path/to/ics55
ecc project set flow.preset rtl2gds
ecc workspace refresh baseline
```

`ecc project` edits only `ecc.toml`: the field registry covers the `[design]`
inputs (`name`, `top`, `rtl`, `netlist`, `golden_netlist`, `def`, `sdc`,
`spef`, `clock_port`, `frequency_mhz`), `[pdk] name/root`, and `[flow] preset`.
`ecc param` continues to own all `[params.*]` and `[pdk.overrides]` fields.
`ecc workspace refresh NAME` accepts only a workspace declared in
`project.json`, recreates it with the existing overwrite safeguards, records
status `not_started`, and never executes the flow. `ecc run --workspace NAME
--overwrite` remains the refresh-and-run form.

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

The old workspace create/run compatibility commands are not exposed as a public
CLI namespace. The supported runtime session surface is the private stdio
sidecar:

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
workspace_id=default status=success workspace=gcd/default inspect_cmd="ecc status" log_cmd="ecc log"
step=routing tool=ecc status=failed runtime=0:03:42 log_cmd="ecc log routing"
config=route_ecc.json scope=step step=routing role=config path=gcd/default/config/route_ecc.json inspect="ecc config routing --json"
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
kind=error error=run_exists workspace_id=default workspace=gcd/default overwrite="ecc run --overwrite"
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
# Optional inputs for a non-RTL entry range:
# netlist = "inputs/gcd.v"
# golden_netlist = "inputs/gcd-golden.v"
# def = "inputs/gcd.def"
# sdc = "constraints/gcd.sdc"
# spef = "inputs/gcd.spef"
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "/path/to/ics55"

[flow]
preset = "rtl2gds" # rtl2gds | syn_sta | synthesis_lec

[params.place]
target_density = 0.65

[params.sta]
max_paths = 1000

[params.cts]
skew_bound = "0.05"

[params.floorplan.phy_placer.well_tap]
distance_micron = 30.0

[pdk.overrides]
tech = "prtech/techLEF/N551P6M_ecos.lef"
```

Current validation supports the `ics55` PDK. `[flow].run` is rejected with
`unsupported_flow_run`; workspace selection belongs to `--workspace NAME`.
The project-level `[design]` declarations are resolved only for fresh creation,
then copied into that workspace's `origin/`; `project.json` carries source
declarations but no per-workspace input snapshot. Valid
flow presets are discovered from the `build_*_flow` defs in
`chipcompiler/rtl2gds/builder.py` (currently `rtl2gds`, `syn_sta`, and
`synthesis_lec`). The `rtl2gds` preset includes synthesis-level LEC immediately
after synthesis, followed by every physical-design step
through RCX, STA, and Harden; `syn_sta` runs synthesis only, with a best-effort netlist-level STA report
(an STA failure does not fail the step). Switching
presets on an existing run requires `ecc run --overwrite` to rebuild the
workspace.
`design.rtl` accepts one or more source entries. A filelist (`.f`, `.fl`, or
`.filelist`) is also accepted; multiple direct source entries are assembled
into a generated filelist when the workspace is created. If `pdk.root` is
empty, the CLI falls back to `CHIPCOMPILER_ICS55_PDK_ROOT` or
`ICS55_PDK_ROOT`.

### PDK Field Overrides

Users can override individual fields of a built-in PDK (such as `ics55`) directly
from `ecc.toml` without authoring a complete external PDK JSON. The CLI exposes
the allowed content paths as `pdk.tech`, `pdk.lefs`, `pdk.libs`,
`pdk.mapping_file`, `pdk.sdc`, and `pdk.spef`; these commands write the same
`[pdk.overrides]` fields. `pdk.root` remains `ecc pdk set-root`.

```toml
[pdk]
name = "ics55"
root = "/path/to/ics55"

[pdk.overrides]
dont_use = ["DFFSRQX*", "ICG*"]
abc_load = 0.020
```

Overrides are applied in memory via whole-field replacement at workspace creation.
The override delta reaches the Yosys builder and other tool steps within a single
`ecc run`. Persistence behavior varies by field category:

- **Scalar/list fields** (`corners`, `site_core`, `site_io`, `site_corner`,
  `tap_cell`, `end_cap`, `buffers`, `fillers`, `tie_high_cell`, `tie_high_port`,
  `tie_low_cell`, `tie_low_port`, `dont_use`, `abc_driver_cell`, `abc_load`):
  Applied in memory and consumed within the run (e.g., baked into generated Yosys
  scripts). Not written to `home/params.toml`. On `load_workspace` (e.g., a subsequent
  `ecc run` without `[pdk.overrides]` in `ecc.toml`), these fields are
  recomputed from the base built-in PDK. Effect: single-run only, dropped on reload
  unless the override is present in `ecc.toml` for the next run. `corners` is the
  exception in this list: no tool step currently consumes it (PDK-to-RCX propagation
  is not wired in `refresh_workspace_config`), so a `corners` override only changes
  the in-memory PDK — exactly like the base PDK's own `corners`.

- **`root`**: Written to `home/params.toml` as `pdk_root` and re-read by `load_workspace`.
  `root` cannot be overridden; set `pdk.root` in `[pdk]` instead.

- **Path fields** (`tech`, `lefs`, `libs`): Written to `db.json` at build time and
  restored by `load_workspace`. Path overrides survive through `db.json`, not through
  PDK recomputation. Out of intended scope.

- **`sdc`/`spef`**: Copied into `origin/` when present; rediscovered by `load_workspace`.
  Out of intended scope.

- **`mapping_file`**: Applied only to the in-memory PDK for the current run. The
  workspace path does not serialize it and `load_workspace` never restores it, so a
  `mapping_file` override is dropped on reload. Out of intended scope.

The primary use case is tuning cell lists (`dont_use`) and synthesis parameters
(`abc_load`), which are scalar/list fields consumed within a run.

Direct tool configuration is deliberately schema-bound: every JSON template
field is either represented by one reviewed per-step schema, covered by an
existing legacy mapping, or listed as a protected workspace path. Workspace
input, output, temporary, generated-artifact, and STA multi-corner liberty
paths are not valid `ecc param` keys. Direct overrides are persisted as a
structured `config_overrides` patch in `home/params.toml` and replayed
after each workspace configuration refresh.

Overrides are validated at `ecc check` time — unknown keys, type mismatches, and
path-existence failures are caught before any run begins. Relative path values in
overrides resolve by field semantics: PDK-content paths (`tech`, `lefs`, `libs`,
`mapping_file`) resolve against the PDK root, while design-data paths (`sdc`,
`spef`) resolve against the project directory (like `pdk.root` and `design.rtl`).
The resolved paths are what `ecc run` forwards to
workspace creation. Path-existence is checked for every path field an override
sets: the required `tech`, `lefs`, and `libs` (checked for every PDK by
`PDK.validate()`) and the optional `mapping_file`, `sdc`, and `spef` (checked only
when an override supplies them). A non-empty value pointing at a missing file
fails `ecc check` regardless of whether that field is later persisted or
regenerated.
`ecc config` surfaces the raw `[pdk.overrides]` input as a project
configuration entry.

The resolved configuration used by each step should be inspectable:

```bash
ecc config
ecc config placement
ecc param list
ecc param show place.target_density
```

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

- [x] `ecc config`
- [x] Managed workspace selection for inspection commands with `--workspace NAME`
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

The supported workspace parameter form is `ecc param <verb> KEY --workspace
NAME` for a workspace declared in the project manifest. It persists a
workspace-local override and refreshes the affected configuration without
running the flow. PDK resources and input references are project-level values:
edit `ecc.toml` through `ecc project` (or the matching `ecc pdk`/`ecc param`
commands), then use `ecc workspace refresh NAME`. Old workspace create/run
automation should use the private JSON-RPC runtime sidecar. The long-term
default is project-oriented and configuration-driven through `ecc.toml` and
subcommands such as `ecc run --project <dir>`.

The project-level Python APIs should remain compatible with existing Python
users. Changes needed for the CLI should be additive and should not force
current Python flow scripts to change unless the underlying API already requires
a broader cleanup.
