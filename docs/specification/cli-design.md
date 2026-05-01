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
ecc diagnose step cts
ecc log step cts --errors
ecc artifacts step cts
ecc config step cts --resolved
```

### Disclosure Commands On Summary Lines

Every summary line must include at least one disclosure command on the same
line. This is required so agents can grep the output and continue inspection
without interpreting natural language paragraphs.

Use stable `key="command"` fields:

```text
step=cts status=failed elapsed=37s wns=-0.083 hold_vios=12 diagnose="ecc diagnose step cts" log="ecc log step cts --errors" config="ecc config step cts --resolved"
```

Do not rely on prose such as:

```text
Run ecc diagnose step cts for more details.
```

The command field names should be stable across releases:

| Field | Purpose |
| --- | --- |
| `inspect` | Show detailed object state |
| `diagnose` | Explain failures or quality issues |
| `log` | Show filtered or raw logs |
| `artifacts` | List output artifacts |
| `config` | Show resolved configuration |
| `metrics` | Show metrics |
| `open` | Open a viewer or report |

### Stable Text Output

The default output should be line-oriented and grep-friendly. Avoid box drawing,
multi-line table cells, and terminal-width-dependent formatting in the default
mode.

Recommended style:

```text
run=baseline status=failed failed_step=routing elapsed=554s diagnose="ecc diagnose run baseline" metrics="ecc metrics run baseline" artifacts="ecc artifacts run baseline"
step=synthesis status=success elapsed=18s cells=312 area=1840.2 inspect="ecc show step synthesis" log="ecc log step synthesis --errors"
step=floorplan status=success elapsed=4s util=45.0 die=100x100 inspect="ecc show step floorplan" config="ecc config step floorplan --resolved"
step=placement status=success elapsed=72s hpwl=18423 overflow=0.02 inspect="ecc show step placement" metrics="ecc metrics step placement"
step=cts status=failed elapsed=37s wns=-0.083 hold_vios=12 diagnose="ecc diagnose step cts" log="ecc log step cts --errors"
```

Pretty output may be provided through a separate option:

```bash
ecc status --pretty
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
{"kind":"step","step":"synthesis","status":"success","elapsed_s":18,"inspect_cmd":"ecc show step synthesis","log_cmd":"ecc log step synthesis --errors"}
{"kind":"step","step":"cts","status":"failed","elapsed_s":37,"wns":-0.083,"hold_vios":12,"diagnose_cmd":"ecc diagnose step cts","log_cmd":"ecc log step cts --errors"}
```

Text output and JSON output should describe the same objects. The text output is
the human and shell interface; JSON is the strict machine interface.

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

The first stable CLI surface should stay small:

```bash
ecc init
ecc check
ecc run
ecc status
ecc diagnose
ecc metrics
ecc log
ecc artifacts
ecc config
ecc open
```

Responsibilities:

| Command | Responsibility |
| --- | --- |
| `ecc init` | Create a project skeleton and `ecc.toml` |
| `ecc check` | Validate RTL, constraints, PDK, tools, and config |
| `ecc run` | Execute a full flow or selected step range |
| `ecc status` | Summarize run and step state |
| `ecc diagnose` | Explain failures or QoR problems with evidence |
| `ecc metrics` | Show run-level or step-level metrics |
| `ecc log` | Show filtered or raw logs |
| `ecc artifacts` | List generated files and viewer commands |
| `ecc config` | Show user or resolved configuration |
| `ecc open` | Open KLayout, reports, or other viewers |

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
├── runs/
└── reports/
```

Command-line arguments may override configuration values, but `ecc.toml` should
be the primary user-facing interface.

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

Each run should have a stable run id and may have a user tag:

```bash
ecc run --tag baseline
ecc run --tag dense_place
ecc diff baseline dense_place
```

## Output Contracts

### Summary Line Format

Default text output should follow this general shape:

```text
kind=<object-kind> key=value ... disclosure_key="ecc command ..."
```

Examples:

```text
run=baseline status=success elapsed=914s metrics="ecc metrics run baseline" artifacts="ecc artifacts run baseline"
step=routing status=failed elapsed=222s shorts=84 opens=3 drc=87 diagnose="ecc diagnose step routing" log="ecc log step routing --errors" open="ecc open step routing --markers drc"
metric=wns value=-0.083 unit=ns status=fail source=cts/reports/timing_hold.rpt inspect="ecc show metric wns --step cts"
artifact=def step=placement path=runs/baseline/placement/output/design.def open="ecc open step placement --artifact def"
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

### Error Output

Errors should also follow progressive disclosure. A failing command should print
a concise summary and actionable disclosure commands:

```text
error=E2103 status=failed step=routing reason=drc_violations shorts=84 opens=3 diagnose="ecc diagnose step routing" log="ecc log step routing --errors" open="ecc open step routing --markers drc"
```

For human readability, a short paragraph may follow, but agents should be able
to use the first line alone.

### Diagnosis Output

Diagnosis must include evidence, not only suggestions:

```text
issue=cts_hold status=fail severity=error wns=-0.083 hold_vios=12 evidence="ecc show issue cts_hold --evidence" log="ecc log step cts --errors"
evidence=timing_hold_report path=runs/baseline/cts/reports/timing_hold.rpt value=-0.083 inspect="ecc show artifact timing_hold_report"
action=enable_hold_repair confidence=medium config="ecc config step cts --resolved"
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
clock_period = "10ns"

[pdk]
name = "ics55"
root = "$PDK_ROOT"

[floorplan]
die_area = [0, 0, 100, 100]
core_util = 45
aspect_ratio = 1.0

[flow]
preset = "rtl2gds"
from = "synthesis"
to = "gds"
```

The resolved configuration used by each step should be inspectable:

```bash
ecc config --resolved
ecc config step placement --resolved
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
ecc diagnose
ecc explain step routing
ecc suggest --goal "fix hold"
ecc summarize run latest
```

These commands must still return evidence-backed results and disclosure
commands.

## Roadmap

### Phase 1: Project And Run Basics

- [ ] `ecc init`
- [ ] `ecc check`
- [ ] `ecc run`
- [ ] `ecc status`
- [ ] `ecc log`
- [ ] `ecc metrics`
- [ ] Default grep-friendly summary output
- [ ] `--json` and `--jsonl` for status and metrics

Success criteria:

- [ ] A user can create a project, run the default RTL-to-GDS flow, inspect status,
  inspect logs, and read metrics without writing Python.
- [ ] Every summary line includes at least one disclosure command.

### Phase 2: Debug And Traceability

- [ ] `ecc diagnose`
- [ ] `ecc artifacts`
- [ ] `ecc config --resolved`
- [ ] Run tags and run comparison basics
- [ ] Structured issue and artifact metadata

Success criteria:

- [ ] A failed step can be investigated through `ecc status -> ecc diagnose -> ecc
  log/artifacts/config`.
- [ ] Agent frameworks can follow disclosure commands without parsing prose.

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

The current CLI accepts explicit arguments such as `--workspace`, `--rtl`,
`--design`, `--top`, `--clock`, `--pdk-root`, and `--freq`. The new CLI should
preserve a migration path for scripted users, but the long-term default should
be project-oriented and configuration-driven.

The CLI should remain API-compatible with existing Python users. Changes needed
for the CLI should be additive and should not force current Python flow scripts
to change unless the underlying API already requires a broader cleanup.
