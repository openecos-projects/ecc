# Development Guide

Development environment setup and workflows for ECOS Chip Compiler, including
how to extend the `ecc` CLI. All code paths are relative to the `ecc`
repository root.

## Installation

ECC is managed with `uv`. The main ECC workspace installs `ecc` from the local
source tree in editable mode.

If Nix is available, enter the development shell before running `uv sync`:

```bash
nix develop
```

If Nix is not available, run the same `uv sync` commands in your normal shell
after installing the required system packages for native builds.

### ECC Workspace

From the `ecc` repository root:

```bash
uv sync --no-build-isolation-package ecc-dreamplace --no-build-isolation-package ecc-tools-bin --verbose
source .venv/bin/activate
```

This creates the Python virtual environment and installs:

- `ecc` from the local source tree.
- `ecc-dreamplace` from `chipcompiler/thirdparty/ecc-dreamplace`.
- `ecc-tools-bin` from `chipcompiler/thirdparty/ecc-tools`.

`ecc` is editable, so Python source edits are picked up on the next import.

### Auto-load With direnv

```bash
direnv allow
```

`direnv` enters the Nix development shell automatically when you `cd` into the
repository.

## Package Builds

Build Python packages with uv:

```bash
uv build
```

Wheel and source distributions are written to `dist/`.

To build the installable PyInstaller CLI bundle yourself, see
[README - Build from source](../README.md#build-from-source).

## Debugging

For normal debugging:

1. Sync the ECC workspace with the ECC command above.
2. Activate `.venv`.
3. Run the CLI, tests, or debugger using `.venv/bin/python`.

No extra `PYTHONPATH` override is required for normal ECC development. When a
process imports `ecc` again, Python code is read from the source tree.

Optional IDE indexing configuration:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python"
}
```

This improves navigation only. Runtime behavior follows the active uv
environment.

## Code Quality

```bash
# Format and lint
uv run ruff format chipcompiler/ test/
uv run ruff check chipcompiler/ test/

# Type check
uv run ty check
uv run pyright chipcompiler/
uv run mypy chipcompiler/

# Legacy formatters
uv run black chipcompiler/ test/
uv run isort chipcompiler/ test/
```

## Git Hooks

Install the pre-commit hooks once per clone to run ruff lint/format checks
(and the commit-message check) automatically before each commit:

```bash
uv run prek install
```

This registers both the `pre-commit` stage (ruff lint + ruff format) and the
`commit-msg` stage (conventional commit message check) from
`.pre-commit-config.yaml` (via its `default_install_hook_types`). If hooks
were already installed — or an older install lacks the commit-msg hook —
reinstall explicitly with:

```bash
uv run prek install --config .pre-commit-config.yaml --hook-type pre-commit --hook-type commit-msg --overwrite
```

## Testing

```bash
uv run pytest test/
uv run pytest test/tools/yosys/test_utility.py -v
uv run pytest test/ --cov=chipcompiler --cov-report=term-missing
uv run pytest test/formal/ -v
```

### Formal Verification

z3-based formal verification. See [test/formal/README.md](../test/formal/README.md)
for details on the approach, test inventory, and known bugs found.

## Add a New EDA Tool

### 1. Create Structure

```bash
mkdir -p chipcompiler/tools/<tool_name>/{configs,scripts}
touch chipcompiler/tools/<tool_name>/{__init__.py,builder.py,runner.py,utility.py}
```

### 2. Implement Interface

`builder.py`:

```python
from pathlib import Path

from chipcompiler.data import Workspace, WorkspaceStep

def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
) -> WorkspaceStep:
    directory = Path(workspace.directory) / f"{step_name}_<tool_name>"
    return WorkspaceStep(name=step_name, tool="<tool_name>", directory=directory)

def build_step_space(workspace_step: WorkspaceStep) -> None:
    Path(workspace_step.directory).mkdir(parents=True, exist_ok=True)

def build_step_config(workspace: Workspace, workspace_step: WorkspaceStep) -> None:
    ...  # write the step's config files from the workspace parameters
```

`runner.py`:

```python
import subprocess

from chipcompiler.data import Workspace, WorkspaceStep

def is_eda_exist() -> bool:
    try:
        subprocess.run(["<tool_name>", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def run_step(workspace: Workspace, step: WorkspaceStep, ecc_module=None) -> bool:
    result = subprocess.run(
        ["<tool_name>", str(step.script.main)],
        cwd=step.directory,
        capture_output=True,
    )
    return result.returncode == 0
```

`__init__.py`:

```python
from .builder import build_step, build_step_space, build_step_config
from .runner import is_eda_exist, run_step

__all__ = ["build_step", "build_step_space", "build_step_config", "is_eda_exist", "run_step"]
```

### 3. Add Configs And Scripts

- JSON templates in `configs/`.
- TCL, Python, or shell scripts in `scripts/`.

### 4. Integrate Into Flow

Update `EngineFlow.build_default_steps()` or use `add_step()`.

### 5. Write Tests

```python
import pytest
from chipcompiler.tools.<tool_name> import is_eda_exist, run_step

@pytest.mark.skipif(not is_eda_exist(), reason="<tool_name> not installed")
def test_run_step():
    pass
```

## Integrating a Thirdparty Tool

ECC uses uv for Python dependency resolution. Treat thirdparty repositories as
separate projects and keep their package-specific setup instructions in those
repositories.

### 1. Python Dependencies

Add the package to root `pyproject.toml`, then run:

```bash
uv lock
```

Then sync the ECC workspace with the command in [Installation](#installation).

### 2. Runtime Integration

Create `chipcompiler/tools/<tool>/` with `__init__.py`, `builder.py`, and
`runner.py`. Each tool must implement `is_eda_exist`, `build_step`, and
`run_step`. Integrate into the flow through `EngineFlow.build_default_steps()`
or `add_step()`.

### Sizer Development Policy

Sizer is currently treated as an external native tool, not as an ECC Python
workspace package. Do not add `ecc-sizer` to `[tool.uv.workspace]`; `uv`
resolves Python packages and lockfiles, while Sizer is a separate CMake/Nix C++
project with its own OpenROAD submodule tree.

Do not vendor Sizer under `chipcompiler/thirdparty` unless ECC intentionally
takes ownership of building and distributing that native runtime. For local
development, keep Sizer in a sibling checkout and expose its executable through
PATH. Promote it to an ECC thirdparty input only when CI, release bundles, or
end-user installs must be reproducible without a separately prepared Sizer
checkout. If that happens, prefer a Nix input or release artifact first; use a
`chipcompiler/thirdparty/ecc-sizer` checkout only if the repository is meant to
be built as part of ECC itself.

## Extending The CLI

This section is for developers who add or modify commands in the `ecc` CLI.

### CLI Architecture

```
pyproject.toml                    # scripts.ecc = "chipcompiler.cli.main:main"
chipcompiler/cli/main.py          # run(argv) / main(), a thin wrapper
chipcompiler/cli/app.py           # root typer app; invoke_typer_app() owns execution and exit codes; the version / layout-image commands are registered here directly
chipcompiler/cli/commands/        # typer command definition layer (thin)
  ├── project.py                  # registration and option declarations for init/check/run/status/log/config/migrate
  ├── doctor.py                   # doctor top-level command (environment check)
  ├── param.py                    # param sub-app (list/show/set/unset/diff)
  ├── pdk.py                      # pdk sub-app (set-root/show/unset)
  ├── project_config.py           # project sub-app (set/unset/add/remove/show)
  ├── workspace.py                # workspace sub-app (refresh)
  ├── signoff.py                  # signoff sub-app (inspect/export)
  ├── report.py                   # report sub-app (summary/qor/checklist/step)
  └── rpc.py                      # rpc sub-app (serve)
chipcompiler/cli/command_handlers/  # business logic layer (stateful / heavy)
  ├── project.py                  # init / check / run / migrate / workspace refresh (preset resolution and environment preflight)
  ├── inspect.py                  # status / log / config
  ├── doctor.py                   # doctor (assembles env_probe results into records)
  ├── param.py                    # the five param subcommands (validation + TOML edits via cli/project/toml_edit.py)
  ├── pdk.py                      # the three pdk subcommands (surgical TOML edit + root source resolution)
  ├── project_config.py           # the five project subcommands (declaration schema + TOML edits via cli/project/config_fields.py)
  ├── workspace_params.py         # workspace-scoped param set/unset/list/diff (home/params.toml mutation + step invalidation)
  ├── signoff.py                  # signoff inspect/export
  └── report.py                   # the four report subcommands (file writing + record summary)
chipcompiler/cli/core/            # framework layer
  ├── inputs.py                   # frozen dataclass input models per command
  ├── invocation.py               # execute_command(): context build → handler → rendering → exit code
  ├── options.py                  # shared Annotated option aliases
  ├── output.py                   # disclosure_cmd() / step-name and state normalization
  ├── records.py                  # error_record()
  ├── types.py                    # CommandContext / CommandResult / OutputMode
  └── version_info.py             # package-metadata versions for the version command (environment tool versions live in inspection/tool_versions.py)
chipcompiler/cli/inspection/      # read-only probing logic
  ├── discovery.py / config_view.py / log_view.py
  ├── env_probe.py                # environment probes for doctor/run preflight (the ProbeResult model)
  └── tool_versions.py            # environment tool versions for ecc version (yosys/sizer/klayout)
chipcompiler/cli/project/         # config.py (ecc.toml parsing and validation) / config_fields.py (project declaration schema for `ecc project`) / params.py (parameter registry) / workspace_params.py (workspace-local override records) / manifest.py (project-state classification) / effective_config.py / config_params/ (direct-config schemas) / migrate*.py (legacy-layout migration) / run_*.py (workspace target resolution and dispatch)
chipcompiler/cli/rendering/       # output rendering (render / renderers / pretty / progress)
chipcompiler/engine/signoff/      # signoff collector + design/checklist reports (package, see below)
chipcompiler/engine/qor_report.py # overall QoR scoring (port of the GUI rules)
```

Module placement is enforced by `test/cli/test_cli_module_layout.py`: the core
framework must live under `cli/core/`, command registration under
`cli/commands/`, all handlers under the single `cli/command_handlers/` package,
read-only probing under `cli/inspection/`, and rendering under
`cli/rendering/`; the old flat `chipcompiler/cli/*.py` modules must not be
importable. Put new files in the matching subpackage — do not create modules at
the `cli/` root.

Public command ownership is strict: `ecc signoff` owns package readiness and
archive export (`inspect`, `export`); `ecc report` owns all report output
(`summary`, `qor`, `checklist`, `step`). `ecc config [STEP]` always returns
resolved data, so it has no `--resolved` switch. Do not introduce an alias in
the wrong group or an option that does not change behavior.

### The Path Of One Command Invocation

Using `ecc check --project gcd --plain` as the example:

1. `main.py::run()` hands `sys.argv[1:]` to `app.py::invoke_typer_app(raw)` (`cli/app.py`).
2. typer parses the arguments and dispatches to `commands/project.py::check_cmd` (`cli/commands/project.py`). The command function does exactly one thing: it packs the typer parameters into the frozen dataclass `CheckInput` (defined in `cli/core/inputs.py`) and calls:
   ```python
   execute_command("check", command_input, project_handlers.check)
   ```
3. `core/invocation.py::execute_command()` (`cli/core/invocation.py`) then:
   - `build_context()`: resolves the project directory (`--project`, defaulting to cwd) → reads its sole `ecc.toml` (an unreadable file is recorded in `config_error`) → classifies the project state via `cli/project/manifest.py::classify_project()` (manifest / legacy / virgin). Manifest projects resolve `--workspace NAME` only through the `project.json` workspaces table: one active workspace auto-selects, multiple ones require the selector, and a new `ecc run --workspace NAME` target is registered before files are created. `--workspace` is a single project-local name, never a direct path. A legacy project must migrate before `ecc run`; a corrupt manifest yields `manifest_invalid`. The context derives `OutputMode` from `--plain` and carries `project_state` / `manifest_error` (`cli/core/types.py`).
   - Calls the handler: `handler(command_input, ctx) -> CommandResult`.
   - After the handler, records are appended as needed (`_with_legacy_hint` / `_with_config_shadow_hint`): `run/check/status` on a legacy project carry a migration hint (pointing at `ecc migrate`); when a workspace's `home/` holds both `params.toml` and the legacy `parameters.json`, a `workspace_config_shadowed` warning is emitted (the JSON is inert).
   - Renders: `rendering/renderers.py::render_command_result()` first looks up a custom renderer in `RENDERERS[(render_key, output_mode)]`, falling back to the generic `rendering/render.py::render_result()`.
   - `raise typer.Exit(code=result.exit_code)` passes the exit code through to `invoke_typer_app`.
4. `invoke_typer_app` runs the click command with `standalone_mode=False`, catching `click.exceptions.Exit` / `ClickException` and converting them into a process exit code, so tests can read the return value of `cli_main.run([...])`.

### CLI Output Conventions

Commands dispatched through `execute_command()` use a "list of records":

- The handler returns `CommandResult.ok(records)` / `CommandResult.err(records, exit_code=1)` (`cli/core/types.py`); `records` is a `tuple[dict, ...]` where each dict is one structured record.
- Two output modes (see `cli/core/invocation.py`):
  - `--plain`: `key=value` per line (values containing whitespace are quoted), for scripting/grep;
  - TEXT by default: pretty rendering; without a custom renderer it prints `key=value` with the `_cmd` suffix stripped from key names.
- Error records use `core/records.py::error_record(...)`, producing `{"kind": "error", "error": "<machine-readable-code>", ...}`; in TEXT mode `render_error` prints them as an `[error]` block. Error codes are a stable contract (e.g. `missing_config`, `run_exists`, `unknown_parameter`, `invalid_value`) and tests assert against them.
- "Next step" hints for users are uniformly generated by `core/output.py::disclosure_cmd("ecc status", project, run_id)` as a copy-pasteable full command, stored in record fields such as `inspect` / `log_cmd` / `run`.

`ecc version` formats version metadata directly; it also has a hidden `--json`
flag (a single object with a version-specific schema) reserved for the desktop
app and kept out of `--help`. `ecc rpc serve` and `ecc layout-image`
intentionally do not use record-renderer output modes.

### Adding A New Command

Using a command like `ecc check` as the example, there are 5 steps (the first 3
are mandatory, the last 2 as needed):

1. **Define the input model.** Add a frozen dataclass in `cli/core/inputs.py`.
   It must satisfy the `CommandInput` protocol (`cli/core/invocation.py`) — i.e.
   carry the two fields `output: OutputOptions` and `project: ProjectOptions`:

   ```python
   @dataclass(frozen=True)
   class CheckInput:
       output: OutputOptions
       project: ProjectOptions
       # command-private fields go here
   ```

2. **Write the handler** in `cli/command_handlers/`, with a fixed signature:

   ```python
   def check(command_input: CheckInput, ctx: CommandContext) -> CommandResult:
       if ctx.config is None:
           return CommandResult.err([error_record("missing_config", path=...)])
       ...
       return CommandResult.ok([{...}, ...])
   ```

   Conventions: handlers do not print directly and do not parse command-line
   strings; heavy logic is imported lazily (existing code routinely does
   `from chipcompiler... import ...` inside function bodies — keep that style
   to shorten CLI startup); read-only probing logic goes in `cli/inspection/`,
   while the handler assembles records.

3. **Register the typer command.** Declare the command function in
   `cli/commands/project.py` (or a new module) and register it; shared options
   use the aliases from `cli/core/options.py` directly:

   ```python
   from chipcompiler.cli.core.options import PlainOption, ProjectOption

   def register_project_commands(app: typer.Typer) -> None:
       app.command("check", help="Validate the current project setup")(check_cmd)

   def check_cmd(
       *,
       project: ProjectOption = None,
       plain: PlainOption = False,
   ) -> None:
       command_input = CheckInput(
           output=output_options(plain=plain),
           project=project_options(project),
       )
       execute_command("check", command_input, project_handlers.check)
   ```

   For a top-level single command use `app.command(...)` directly (working
   example: `cli/commands/doctor.py`, the shortest full chain); for a command
   group create `xxx_app = typer.Typer(...)` and add it in `app.py` with
   `app.add_typer(xxx_app, name="xxx")` (working example:
   `cli/commands/signoff.py`, whose subcommands reuse one handler module via
   `execute_command(..., render_key=f"signoff:{sub}")`). Note that the root app
   built in `app.py` sets `add_completion=False, no_args_is_help=True`.

4. **(Optional) Customize TEXT rendering.** The default TEXT output is
   `key=value`. For friendlier output:

   - Single commands: add a renderer function to the `get_pretty_renderer()`
     registry in `cli/rendering/pretty.py` (the existing
     `init/check/run/status/config` commands take this path);
   - Subcommand groups: add a `(render_key, OutputMode)` entry to the
     `RENDERERS` dict in `cli/rendering/renderers.py`, passing `render_key` via
     `execute_command(..., render_key="param:show")` (the param group takes
     this path).

   PLAIN needs no customization at all.

5. **Add tests.** Test placement follows ownership boundaries (see
   [../CLAUDE.md](../CLAUDE.md) section 5); CLI specifics:

   - Command behavior → `test/cli/commands/test_<command>.py`; param →
     `test/cli/params/`; read-only probing → `test/cli/inspect/`; rendering →
     `test/cli/rendering/`.
   - Tests call the Python entry point directly, not a subprocess:
     ```python
     from chipcompiler.cli import main as cli_main

     rc = cli_main.run(["check", "--project", project_dir, "--plain"])
     assert rc == 0
     records = plain_records(capsys.readouterr().out)  # fixture from test/cli/conftest.py
     ```
   - Reuse the fixtures in `test/cli/conftest.py`: `create_cli_project`
     (creates a temporary project with `ecc.toml`), `create_flow_json`
     (fabricates `home/flow.json` beneath the given workspace directory),
     `create_step_dir`,
     `create_workspace_config`, `mock_pdk_validation`, and others. **Note the
     autouse `_stub_run_preflight`**: it stubs `env_probe.probe_environment` to
     return nothing, so CLI tests never depend on host tools (doctor/preflight
     tests override that stub themselves, which takes precedence).
   - Tests for engine-layer reports/signoff go in the top-level `test/` (e.g.
     `test/test_signoff_report.py`, `test/test_qor_report.py`,
     `test/test_signoff_package.py`), reusing their fixtures to fabricate
     workspaces.
   - Don't forget to register new commands in both
     `test/cli/test_typer_cli.py::test_root_help_returns_zero_and_lists_commands`
     and `test/cli/test_cli_module_layout.py` (the commands tuple).

### Extension Scenarios

#### Adding a tunable parameter (the param system)

Legacy semantic parameters remain in `cli/project/params.py::_LEGACY_PARAM_REGISTRY`.
Direct tool configuration belongs in one reviewed module per owner under
`data/config_params/` (`cts.py`, `floorplan.py`, `dreamplace.py`, and so on).
`ParamSchema` has one target: legacy `maps_to`, a JSON `config_target`, or a
whitelisted PDK `pdk_target`.

Use `config_param()` for a reviewed static template field (`description` is a
required keyword argument, written per parameter by a human reviewer and
enforced by `test/data/test_descriptions.py`):

```python
# chipcompiler/data/config_params/cts.py
config_param(
    "cts.skew_bound",
    "cts",
    ("skew_bound",),
    "0.08",
    applies="cts",
    description="Allowed clock skew upper bound in ns.",
)
```

This enables `ecc param list/show/set/unset/diff`, repeated `ecc run --set
key=value`, and recursive `[params.*]` TOML parsing/writing. `ecc param list`
stays concise; use `--step <owner>` or `--all` to enumerate direct schemas.
List and object values use JSON literals on the command line.

At project-run creation, non-default `config_target` values are saved as
structured `config_overrides` in `home/params.toml`;
`data.workspace.config_overrides` replays them after every workspace
configuration refresh. PDK path schemas live in `config_params/pdk.py` and
write `[pdk.overrides]`; keep `pdk.root` on `ecc pdk set-root`. Never add
workspace input, output, temporary, generated-artifact, or STA multi-corner
liberty paths as CLI parameters.

`config_params/coverage.py` compares each JSON template field with exactly one
direct schema, legacy mapping, or protected-path entry. Update that manifest
and `test/cli/params/test_config_coverage.py` whenever a template changes.
Parsing and surgical TOML editing remain in `params.py`; command tests remain
in `test/cli/params/`.

#### Extending `ecc run`

`run` has two mutually exclusive paths (`run()` / `_run_workspace()` in
`cli/command_handlers/project.py`):

- **Fresh workspace**: resolve `[design]` input declarations, PDK, parameters,
  and the requested entry step; validate only that entry step's required files;
  atomically pre-register the managed name in `project.json` as `not_started`;
  preflight tools; call `create_workspace` at `<project>/<workspace-name>`.
  `create_workspace` copies inputs to `origin/` and produces all step configs;
  the CLI never rewrites those configs afterwards. A normal fresh flow uses a
  preset. `--from A --to B` instead calls `rtl2gds.build_flow_range(A, B)` to
  construct the inclusive canonical range. New ranges cannot combine with
  `--preset`, `--overwrite`, `--resume`, `--only`, or `--force`.
- **Existing workspace**: first reconcile the persisted flow against the target
  via `chipcompiler/engine/reconcile.py` (proper prefix → append/extend;
  superset with all steps successful → `no_op`; divergent → `flow_mismatch`),
  then after `load_workspace`, re-run in place via `run_resume`, `run_from`, or
  `run_only` from `chipcompiler.engine.rerun`. `--from A --to B` is an
  inclusive persisted range and invalidates its downstream suffix while
  retaining downstream output files. Existing workspaces neither preflight
  fresh inputs nor rewrite copied inputs/configuration.

Project preset sequences are defined in `chipcompiler/rtl2gds/builder.py`
(`build_*_flow()` / `get_flow_builders()`), not in the CLI layer.
`build_flow_range()` slices the canonical `build_rtl2gds_flow()` result, so
step aliases and ordering have one source of truth. Keep a sequence change
coordinated with the engine's default flow, `StepEnum`, and manifest range
mappings; the CLI only handles argument parsing, input contracts,
progress-renderer selection, and result mapping.

#### Extending environment probing (doctor / preflight)

`cli/inspection/env_probe.py` is the single probing layer:
`ProbeResult(component, status, required, detail, remediation)` plus one probe
function per component (yosys / yosys-slang / ecc-tools / dreamplace / klayout
/ sizer / pdk). Adding a component = adding a probe function and registering it
in `_PROBES`/`ALL_COMPONENTS`; `probe_environment()` guards against exceptions
(a crashing probe counts as a fail rather than aborting the sweep).
`probe_components_for_preset()` decides the current run-preflight scope
(ecc-tools always, yosys ↔ contains Synthesis, dreamplace ↔ contains
place/legalization, sizer ↔ contains Timing optimization). The PDK is covered
by configuration validation, slang is left to synthesis, and Sizer is also
required by doctor.

#### Extending signoff (`ecc signoff inspect/export`)

- **CLI layer**: `cli/commands/signoff.py` + `cli/command_handlers/signoff.py`.
  `inspection/discovery.py::resolve_loaded_workspace()` resolves a managed
  `--workspace NAME` in the selected project (or its sole active workspace).
  inspect reuses `runtime/signoff_export.py::inspect_signoff_package` (blocked
  still exits 0); export reuses `export_signoff_package_archive`
  (`RuntimeApiError` → `signoff_incomplete`).
- **Engine layer**: the `chipcompiler/engine/signoff/` package owns the signoff
  collector `SignoffPackageCollector` and the package-export APIs used by
  readiness inspection and archive generation.

#### Extending reports (`ecc report summary/qor/checklist/step`)

- **Design summary**: `ecc report summary` calls
  `chipcompiler.engine.signoff.generate_text_report`. Its implementation is
  split by responsibility (`report.py` orchestration / `report_data.py` data
  contract / `report_extract.py` parsers + workspace collection /
  `report_sections.py` section extraction / `report_timing.py` the timing chain
  / `report_text.py` formatting), all exposed through the package `__init__`.
  Add a report section through an `_extract_<family>(q)` in
  `report_sections.py` (or the timing chain) and register it from `report.py`.
- `engine/qor_report.py`: the single-workspace port of the GUI's
  `projectQorTrend.ts` — constant tables
  (`METRIC_FAIL_VALUES`/`DIMENSION_WEIGHTS`/`QOR_SCORE_THRESHOLD`) +
  normalization + project-level record selection (role priority
  final>gate>trend; area_cost only from the last successful area step) + the
  `score_record` formulas + dimension weighting (no renormalization). Adding a
  scoreable metric = adding its threshold here and in the GUI.
- `engine/signoff/report_checklist.py`: read-only rendering of
  `home/checklist.json` (reports unavailable on an invalid file; never writes
  back).
- CLI: `cli/commands/report.py` + `cli/command_handlers/report.py`; workspace
  resolution reuses `inspection/discovery.py` (`resolve_workspace_path` =
  side-effect-free core, `resolve_command_workspace` = core + `load_workspace`;
  shared by signoff, report, and the read-only status/log/config commands).

#### Extending the RPC (`ecc rpc serve`)

`rpc serve --stdio` starts the JSON-RPC 2.0 sidecar
(`chipcompiler/runtime/stdio_server.py`). Methods are declared in
`chipcompiler/runtime/methods.py::RUNTIME_METHODS` (`method_name` + a pydantic
`request_model` + `handler_name`), handler implementations live in
`chipcompiler/runtime/workspace_api.py`, and `runtime/server.py` mounts them
uniformly; protocol details in [rpc-guide.md](rpc-guide.md). Adding a
method = one `RuntimeMethodSpec` + the matching API method + a request model;
no CLI-layer changes needed.

#### Extending project declarations (`ecc project *` / `ecc workspace refresh`)

- The editable keys of `ecc project set/unset/add/remove/show` are declared in
  `cli/project/config_fields.py::PROJECT_FIELDS` (`key` / TOML table / name /
  type / `list_value`). Add a field there and the subcommands pick it up;
  `add`/`remove` are hard-restricted to `design.rtl`
  (`unsupported_project_collection` otherwise).
- `ecc workspace refresh` is implemented as the run path with `overwrite=True,
  execute_flow=False` (`cli/command_handlers/project.py::refresh_workspace`),
  which is why it runs the same environment preflight as a fresh run (`preset:
  rtl2gds` from `ecc.toml` means the full tool set must be ready, even though
  no step executes). On a non-manifest project it reports
  `workspace_refresh_requires_managed_workspace`.
- Workspace-scoped `param set/unset/list/diff --workspace NAME` mutate
  `home/params.toml` through `cli/command_handlers/workspace_params.py`
  (records in `workspace_param_overrides`, suffix invalidation via
  `chipcompiler.engine.rerun`), and project-scoped `param` goes through
  `cli/command_handlers/param.py`.

## CLI Usage

For command-line automation and scripting, run CLI via Nix:

```bash
nix run . -- init gcd
nix run . -- check --project gcd
nix run . -- run --project gcd
nix run . -- status --project gcd
nix run . -- log --project gcd
```

Or run through the active uv environment:

```bash
uv run ecc init gcd
uv run ecc check --project gcd
uv run ecc run --project gcd
```

### Environment Doctor

`ecc doctor` probes the host environment (PDK, yosys incl. the slang frontend,
bundled ecc-tools/dreamplace, required sizer, optional klayout) and reports
pass/fail/skip per component with remediation hints. Only required failures
exit non-zero. `ecc run` performs the same probes for the tools the chosen
preset needs and fails fast with `env_not_ready` before creating a workspace:

```bash
uv run ecc doctor                  # inside a project for the PDK probe
uv run ecc doctor --project gcd --plain
```

### PDK Path

`ecc pdk set-root <path>` wires an already-ready ics55 PDK into the
project (writes `[pdk] root` in `ecc.toml` as an absolute path; incomplete
contents are advisory). `ecc pdk show` reports the effective root, which
resolver won (ecc.toml / `CHIPCOMPILER_ICS55_PDK_ROOT` / `ICS55_PDK_ROOT` /
repo default), and a contents check; `ecc pdk unset` clears the override:

```bash
uv run ecc pdk set-root ~/pdk/icsprout55-pdk
uv run ecc pdk show
```

### Flow Preset Override

`ecc run --preset <name>` overrides `[flow] preset` for a single run without
editing `ecc.toml`. Valid names are auto-discovered from
`chipcompiler/rtl2gds/builder.py` (`rtl2gds | syn_sta | synthesis_lec`); the
`rtl2gds` preset is the full synthesis-to-harden chain (15 steps, with a
synthesis-level LEC immediately after Synthesis; Harden
emits GDS + abstract LEF + timing LIB):

```bash
uv run ecc run --project gcd --preset rtl2gds
```

### Reports

`ecc report qor` scores the workspace the same way the GUI project dashboard
does (per-metric scores against fixed fail thresholds, dimension averages,
weighted overall — weights are not renormalized over missing dimensions);
`ecc report checklist` renders the signoff checklist status, and `ecc report
summary` writes the GUI-parity text design summary. All three write to
`<workspace>/signoff/` by default and accept `-o` plus the usual
`--project` plus an optional managed `--workspace NAME` selector:

```bash
uv run ecc report qor --project gcd
uv run ecc report checklist --project gcd --workspace default
uv run ecc report summary --project gcd
```

### Signoff

After a completed flow, inspect and export the signoff package:

```bash
uv run ecc signoff inspect --project gcd       # readiness review (blocked still exits 0)
uv run ecc signoff export -o gcd.tar.gz --project gcd [--include-debug]
```

`inspect`/`export` refresh step analysis first (same as the GUI). They use the
selected project and its managed `--workspace NAME`; a single active workspace
is selected automatically.

The project config is the CLI input surface:

```toml
[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/gcd.v"]
# Optional input declarations for non-RTL entry ranges:
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
```

For filelist mode, set `design.rtl` to a single filelist path, for example
`rtl = ["rtl/filelist.f"]`. Multiple RTL sources should be listed in the
filelist rather than as multiple `design.rtl` entries.

## Runtime Resolution

### Yosys

Resolution priority in `chipcompiler/tools/yosys/utility.py`:

1. Bundled runtime through `CHIPCOMPILER_OSS_CAD_DIR`.
2. System PATH through `yosys`.

Runtime handling:

- `get_yosys_command()` performs side-effect-free detection.
- `get_yosys_runtime()` returns `(command, env)` for subprocess use.
- `check_slang_plugin()` runs the preflight check `yosys -p "plugin -i slang"`.

If Yosys is not found, install the managed toolchain with the ECC installer
`--with-toolchain` flag (see the [README](../README.md#installation)). The
installer wrapper exports `CHIPCOMPILER_OSS_CAD_DIR` and
`CHIPCOMPILER_ICS55_PDK_ROOT`. To point at an existing OSS CAD Suite instead:

```bash
export CHIPCOMPILER_OSS_CAD_DIR=/path/to/oss-cad-suite
```

### Kepler Formal (LEC engine)

The `lec` and `postRouteLec` steps run the kepler-formal equivalence checker
(GPL-3.0, invoked as a separate process). Resolution priority in
`chipcompiler/tools/kepler_formal/utility.py`:

1. Release root through `CHIPCOMPILER_KEPLER_FORMAL_ROOT` (root-level
   `kepler-formal` launcher, then `bin/kepler-formal`).
2. System PATH through `kepler-formal`.

Manual install builds from source: kepler-formal is GPL-3.0-only, so ECOS
does not redistribute built binaries — each user builds their own copy (see
the upstream [build instructions](https://github.com/keplertech/kepler-formal#build-instructions)):

```bash
git clone --recurse-submodules https://github.com/keplertech/kepler-formal.git
cd kepler-formal
sudo apt-get install g++ cmake ninja-build bison flex pkg-config \
  libcapnp-dev libtbb-dev libboost-iostreams-dev zlib1g-dev
cmake -B build -GNinja -DCMAKE_BUILD_TYPE=Release -DPYTHON_INTERFACE=OFF
cmake --build build -j "$(nproc)"
export CHIPCOMPILER_KEPLER_FORMAL_ROOT="$PWD/build/src"   # provides bin/kepler-formal
ecc doctor   # kepler-formal should report pass
```

ECOS Studio detects a Resource Manager installation of kepler-formal and
exports `CHIPCOMPILER_KEPLER_FORMAL_ROOT` for the ECC sidecar automatically;
the env var above is the CLI-only equivalent. Verdict parsing relies on the
tool's stdout evidence (`No difference was found.`); upgrading kepler-formal
requires rerunning the LEC integration tests, because the tool exits 0 even
for an unequal design pair.


### Sizer

Sizer integration expects the external
[`ecc-sizer`](https://github.com/openecos-projects/ecc-sizer) repository to be
built separately. Clone it outside the ECC repository:

```bash
git clone --recursive https://github.com/openecos-projects/ecc-sizer /path/to/ecc-sizer
cd /path/to/ecc-sizer
git submodule update --init --recursive
```

Build Sizer with its own development environment:

```bash
nix develop
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target Sizer -j "$(nproc)"
```

The executable is expected at:

```text
/path/to/ecc-sizer/build/src/Sizer
```

For ECC development, add the executable directory to PATH before running flows
or tests:

```bash
export PATH=/path/to/ecc-sizer/build/src:$PATH
which Sizer
```

The command name is case-sensitive on Linux. Current ECC detection looks for
`Sizer`, then discovers the Sizer runtime root by walking upward from that
binary and checking for `src/sizer_os.tcl`. If the executable is provided
through a wrapper that does not live under the Sizer checkout, also set:

```bash
export CHIPCOMPILER_ECC_SIZER_ROOT=/path/to/ecc-sizer
```

For the ICS55 GCD tool integration test:

```bash
nix develop
export PATH=/path/to/ecc-sizer/build/src:$PATH
export CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/ics55-pdk
.venv/bin/python -m pytest test/integration/test_rtl2gds_flow.py::test_ics55_gcd -q -s
```

### PDK

Resolution priority for `get_pdk("ics55")` in `chipcompiler/data/pdk.py`:

1. Explicit `pdk_root` argument.
2. `CHIPCOMPILER_ICS55_PDK_ROOT` environment variable.
3. Legacy `ICS55_PDK_ROOT` environment variable.
4. Default: `../pdk/icsprout55-pdk` next to the ecc checkout (the ecos-studio
   workspace location).

Backend supports `POST /api/workspace/set_pdk_root` to set runtime path.
Workspace creation persists the resolved root in `home/params.toml` as `pdk_root`.

Example:

```bash
CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/pdk uv run ecc
```

## Common Workflows

### Debug Flow Step

1. Check `workspace_step.logs/` for tool output.
2. Inspect `workspace_step.config/` for configs.
3. Verify `workspace_step.input/` files.
4. Reproduce or continue the failure in place with the project and managed
   workspace name:

```bash
project=/path/to/project
workspace=default

# Resume from the first non-successful step (default when no selector is given).
.venv/bin/ecc run --project "$project" --workspace "$workspace"
.venv/bin/ecc run --project "$project" --workspace "$workspace" --resume

# Re-execute the inclusive CTS-to-route range in the persisted flow.
.venv/bin/ecc run --project "$project" --workspace "$workspace" --from CTS --to route

# Run exactly one step; add --force if it already succeeded.
.venv/bin/ecc run --project "$project" --workspace "$workspace" --only place
.venv/bin/ecc run --project "$project" --workspace "$workspace" --only place --force
```

`--resume`, `--only`, and a range are mutually exclusive, and `--force` is
only valid with `--only`. `--workspace` can be combined with `--project`;
new ranges cannot be combined with `--overwrite`. Step names use the canonical
flow aliases.

Workspace mode mutates the workspace in place: each executed step's `output/`
is replaced, and steps downstream of a re-executed step are marked `Unstart`
so a later resume re-runs them. Rerunning a step regenerates
`workspace/config/*.json` from `home/params.toml`, so adjust parameters
instead of hand-editing generated configs; keep a copy of a reported workspace
if it must stay immutable.

For Python-level debugging, invoke the same CLI module directly:

```bash
.venv/bin/python -m chipcompiler.cli.main run \
  --workspace "$workspace" \
  --only place \
  --force
```

### Modify Flow Sequence

1. Edit `EngineFlow.build_default_steps()` or use `add_step()`.
2. Persist with `flow.save()` to `workspace.flow.json`.
3. Run with `flow.run_steps()`; successful steps are skipped.
4. Use `clear_states()` to re-run.

## Conventions

Contributor conventions are not repeated here; they live in
[../CLAUDE.md](../CLAUDE.md) (behavioral guidelines, test placement, module
size, gotchas) and [review-guidelines.md](review-guidelines.md) (review
standards).

## Related Documentation

- [RPC Guide](rpc-guide.md) - RPC sidecar protocol
- [Examples](examples/) - Example projects and CLI usage
- [中文开发指南](development.cn.md)
