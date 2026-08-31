# ECC CLI Command Extension Developer Guide

This guide is for developers who need to add or modify commands in the `ecc` CLI. It is based on the current source tree (the `chipcompiler` package, v0.1.0-alpha.11). All code paths are relative to the repository root.

Related documents: [architecture.md](architecture.md) (architecture), [development.md](development.md) (development workflow), [workspace-cli.md](workspace-cli.md) (RPC sidecar protocol), [../CLAUDE.md](../CLAUDE.md) (repository conventions).

## 1. Entry point and overall structure

```
pyproject.toml                    # scripts.ecc = "chipcompiler.cli.main:main"
chipcompiler/cli/main.py          # run(argv) / main(), a thin wrapper
chipcompiler/cli/app.py           # root typer app; invoke_typer_app() owns execution and exit codes
chipcompiler/cli/commands/        # typer command definition layer (thin)
  ├── project.py                  # registration and option declarations for init/check/run/status/log/config
  ├── doctor.py                   # doctor top-level command (environment check)
  ├── param.py                    # param sub-app (list/show/set/unset/diff)
  ├── pdk.py                      # pdk sub-app (setup/set-root/show/unset)
  ├── signoff.py                  # signoff sub-app (inspect/export/report)
  ├── report.py                   # report sub-app (qor/checklist)
  └── rpc.py                      # rpc sub-app (serve)
chipcompiler/cli/command_handlers/  # business logic layer (stateful / heavy)
  ├── project.py                  # init / check / run (preset resolution and environment preflight)
  ├── inspect.py                  # status / log / config
  ├── doctor.py                   # doctor (assembles env_probe results into records)
  ├── pdk.py                      # the three pdk subcommands (surgical TOML edit + root source resolution)
  ├── signoff.py                  # the three signoff subcommands + inspect TEXT rendering
  └── report.py                   # the two report subcommands (file writing + record summary)
chipcompiler/cli/handlers/param.py  # param subcommand handlers + param TEXT rendering
chipcompiler/cli/core/            # framework layer
  ├── inputs.py                   # frozen dataclass input models per command
  ├── invocation.py               # execute_command(): context build → handler → rendering → exit code
  ├── options.py                  # shared Annotated option aliases
  ├── output.py                   # disclosure_cmd() / step-name and state normalization
  ├── records.py                  # error_record()
  ├── types.py                    # CommandContext / CommandResult / OutputMode
  └── version_info.py             # version information for the version command
chipcompiler/cli/inspection/      # read-only probing logic
  ├── discovery.py / config_view.py / log_view.py
  └── env_probe.py                # environment probes for doctor/run preflight (the ProbeResult model)
chipcompiler/cli/project/         # ecc.toml parsing and validation (config.py), parameter registry (params.py)
chipcompiler/cli/rendering/       # output rendering (render / renderers / pretty / progress)
chipcompiler/engine/signoff/      # signoff collector + design/checklist reports (package, see §5.4)
chipcompiler/engine/qor_report.py # overall QoR scoring (port of the GUI rules, see §5.5)
```

Module placement is enforced by `test/cli/test_cli_module_layout.py`: the core framework must live under `cli/core/`, command registration under `cli/commands/`, handlers under `cli/command_handlers/` (project-style commands) and `cli/handlers/` (param-style), read-only probing under `cli/inspection/`, and rendering under `cli/rendering/`; the old flat `chipcompiler/cli/*.py` modules must not be importable. Put new files in the matching subpackage — do not create modules at the `cli/` root.

## 2. The full path of one command invocation

Using `ecc check --project gcd --json` as the example:

1. `main.py::run()` hands `sys.argv[1:]` to `app.py::invoke_typer_app(raw)` (`cli/app.py`).
2. typer parses the arguments and dispatches to `commands/project.py::check_cmd` (`cli/commands/project.py`). The command function does exactly one thing: it packs the typer parameters into the frozen dataclass `CheckInput` (defined in `cli/core/inputs.py`) and calls:
   ```python
   execute_command("check", command_input, project_handlers.check)
   ```
3. `core/invocation.py::execute_command()` (`cli/core/invocation.py`) then:
   - `build_context()`: resolves the project directory (`--project`, defaulting to cwd) → reads `ecc.toml` into a `ProjectConfig` → resolves the run directory (`--run-id` > the configured `[flow] run` > `runs/default`; see `cli/project/config.py` and `cli/inspection/discovery.py`) → derives the `OutputMode` from `--json/--jsonl/--plain` and assembles a `CommandContext` (`cli/core/types.py`).
   - Calls the handler: `handler(command_input, ctx) -> CommandResult`.
   - Renders: `rendering/renderers.py::render_command_result()` first looks up a custom renderer in `RENDERERS[(render_key, output_mode)]`, falling back to the generic `rendering/render.py::render_result()`.
   - `raise typer.Exit(code=result.exit_code)` passes the exit code through to `invoke_typer_app`.
4. `invoke_typer_app` runs the click command with `standalone_mode=False`, catching `click.exceptions.Exit` / `ClickException` and converting them into a process exit code, so tests can read the return value of `cli_main.run([...])`.

## 3. Output conventions (the records model)

Every command's output is a "list of records":

- The handler returns `CommandResult.ok(records)` / `CommandResult.err(records, exit_code=1)` (`cli/core/types.py`); `records` is a `tuple[dict, ...]` where each dict is one structured record.
- Four output modes (priority jsonl > json > plain > text, see `cli/core/invocation.py`):
  - `--json`: a single JSON object `{"records": [...]}`;
  - `--jsonl`: one JSON record per line;
  - `--plain`: `key=value` per line (values containing whitespace are quoted), for scripting/grep;
  - TEXT by default: pretty rendering; without a custom renderer it prints `key=value` with the `_cmd` suffix stripped from key names.
- Error records use `core/records.py::error_record(...)`, producing `{"kind": "error", "error": "<machine-readable-code>", ...}`; in TEXT mode `render_error` prints them as an `[error]` block. Error codes are a stable contract (e.g. `missing_config`, `run_exists`, `unknown_parameter`, `invalid_value`) and tests assert against them.
- "Next step" hints for users are uniformly generated by `core/output.py::disclosure_cmd("ecc status", project, run_id)` as a copy-pasteable full command, stored in record fields such as `inspect` / `log_cmd` / `run`.

## 4. Adding a new top-level command (step by step)

Using a command like `ecc check` as the example, there are 5 steps (the first 3 are mandatory, the last 2 as needed):

### 4.1 Define the input model

Add a frozen dataclass in `cli/core/inputs.py`. It must satisfy the `CommandInput` protocol (`cli/core/invocation.py`) — i.e. carry the two fields `output: OutputOptions` and `project: ProjectOptions`:

```python
@dataclass(frozen=True)
class CheckInput:
    output: OutputOptions
    project: ProjectOptions
    # command-private fields go here
```

### 4.2 Write the handler

Put it in `cli/command_handlers/` (commands that mutate projects or run flows) or `cli/handlers/` (lightweight param-style commands), with a fixed signature:

```python
def check(command_input: CheckInput, ctx: CommandContext) -> CommandResult:
    if ctx.config is None:
        return CommandResult.err([error_record("missing_config", path=...)])
    ...
    return CommandResult.ok([{...}, ...])
```

Conventions: handlers do not print directly and do not parse command-line strings; heavy logic is imported lazily (existing code routinely does `from chipcompiler... import ...` inside function bodies — keep that style to shorten CLI startup); read-only probing logic goes in `cli/inspection/`, while the handler assembles records.

### 4.3 Register the typer command

Declare the command function in `cli/commands/project.py` (or a new module) and register it; shared options use the aliases from `cli/core/options.py` directly:

```python
from chipcompiler.cli.core.options import JsonOption, PlainOption, ProjectOption

def register_project_commands(app: typer.Typer) -> None:
    app.command("check", help="Validate the current project setup")(check_cmd)

def check_cmd(
    *,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = CheckInput(
        output=output_options(json_output=json_output, jsonl=False, plain=plain),
        project=project_options(project),
    )
    execute_command("check", command_input, project_handlers.check)
```

For a top-level single command use `app.command(...)` directly (working example: `cli/commands/doctor.py`, the shortest full chain); for a command group create `xxx_app = typer.Typer(...)` and add it in `app.py` with `app.add_typer(xxx_app, name="xxx")` (working example: `cli/commands/signoff.py`, whose subcommands reuse one handler module via `execute_command(..., render_key=f"signoff:{sub}")`). Note that the root app built in `app.py` sets `add_completion=False, no_args_is_help=True`.

### 4.4 (Optional) Customize TEXT rendering

The default TEXT output is `key=value`. For friendlier output:

- Single commands: add a renderer function to the `get_pretty_renderer()` registry in `cli/rendering/pretty.py` (the existing `init/check/run/status/config` commands take this path);
- Subcommand groups: add a `(render_key, OutputMode)` entry to the `RENDERERS` dict in `cli/rendering/renderers.py`, passing `render_key` via `execute_command(..., render_key="param:show")` (the param group takes this path).

JSON/JSONL/PLAIN need no customization at all.

### 4.5 Add tests

All CLI tests live under `ecc/test/cli/`, organized by ownership (repository CLAUDE.md section 5):

- Command behavior → `test/cli/commands/test_<command>.py`; param → `test/cli/params/`; read-only probing → `test/cli/inspect/`; rendering → `test/cli/rendering/`.
- Tests call the Python entry point directly, not a subprocess:
  ```python
  from chipcompiler.cli import main as cli_main

  rc = cli_main.run(["check", "--project", project_dir, "--json"])
  assert rc == 0
  data = json.loads(capsys.readouterr().out)
  ```
- Reuse the fixtures in `test/cli/conftest.py`: `create_cli_project` (creates a temporary project with `ecc.toml`), `create_flow_json` (fabricates `runs/<id>/home/flow.json`), `create_step_dir`, `create_workspace_config`, `mock_pdk_validation`, and others. **Note the autouse `_stub_run_preflight`**: it stubs `env_probe.probe_environment` to return nothing, so CLI tests never depend on host tools (doctor/preflight tests override that stub themselves, which takes precedence).
- Tests for engine-layer reports/signoff go in the top-level `test/` (e.g. `test/test_signoff_report.py`, `test/test_qor_report.py`, `test/test_signoff_package.py`), reusing their fixtures to fabricate workspaces.
- Don't forget to register new commands in both `test/cli/test_typer_cli.py::test_root_help_returns_zero_and_lists_commands` and `test/cli/test_cli_module_layout.py` (the commands tuple).

How to run (from the repository root):

```bash
nix develop   # optional
uv sync --no-build-isolation-package ecc-dreamplace --no-build-isolation-package ecc-tools-bin
.venv/bin/python -m pytest test/cli -q
```

## 5. Common extension scenarios

### 5.1 Adding a tunable parameter (the param system)

The parameter registry lives in `cli/project/params.py::PARAM_REGISTRY` (`cli/project/params.py`). Adding one `ParamSchema` entry simultaneously enables: support in `ecc param list/show/set/unset/diff`, support for `ecc run --set key=value`, and read/write plus validation of the `[params.<group>]` table in `ecc.toml`:

```python
ParamSchema(
    param="place.target_density",        # unique key = "<group>.<name>"
    group="place",                       # corresponds to [params.place] in ecc.toml
    name="target_density",
    type="float",                        # int/float/bool/str/list[int]/list[float]/list[str]
    default=0.2,
    applies="placement",                 # the flow step it affects (display only)
    maps_to={"DreamPlace": "target_density"},  # backend parameter key: str = top-level key, dict = nested key
    description="Target placement density",
    range=(0.1, 0.95),                   # optional: numeric range
    choices=("MET2", ...),               # optional: enumeration
    unit="MHz",                          # optional: unit
    example="0.65",                      # optional: example value
)
```

The `maps_to` expansion rules are in `build_backend_overrides()` (`cli/project/params.py`): non-default values are translated into backend `parameters` overrides and merged in via `update_parameters` at run time. The surgical `ecc.toml` edit done by `ecc param set` is performed by `_apply_scoped_param_edit()` (`cli/project/params.py`) using textual regexes (comments and formatting preserved) — new parameters need no code for this. Registry tests live in `test/cli/params/test_registry.py`.

### 5.2 Extending `ecc run`

`run` has two mutually exclusive paths (`run()` / `_run_workspace()` in `cli/command_handlers/project.py`):

- **Project mode** (default): read `ecc.toml` → resolve RTL/PDK/parameters plus the `--preset` override → **environment preflight** (`_preflight_environment`: probes the tools the preset needs via `inspection/env_probe.py`; anything missing → `env_not_ready` fail-fast) → `create_workspace` under `runs/<run-id>/` → build the `EngineFlow` from the steps in `rtl2gds.get_flow_builders()` → run (progress rendering via `rendering/progress.py::run_flow_with_progress` on a TTY, plain `run_steps` otherwise). `--overwrite` runs safety checks first (only genuine ECC run directories are deleted); `--preset` is not written back to `ecc.toml` and is mutually exclusive with `--workspace`.
- **Workspace mode** (`--workspace`): after `load_workspace`, re-runs in place via `run_resume / run_from / run_only` from `chipcompiler.engine.rerun`; the `--resume/--from/--only` selectors are mutually exclusive and only legal in this mode; no environment preflight runs in this mode.

Changing the flow step sequence itself happens in `chipcompiler/engine` (`EngineFlow.build_default_steps()` / `add_step()`), not in the CLI layer; the CLI only handles argument parsing, progress-renderer selection, and result mapping.

### 5.3 Extending environment probing (doctor / preflight)

`cli/inspection/env_probe.py` is the single probing layer: `ProbeResult(component, status, required, detail, remediation)` plus one probe function per component (yosys / yosys-slang / ecc-tools / dreamplace / klayout / sizer / pdk). Adding a component = adding a probe function and registering it in `_PROBES`/`ALL_COMPONENTS`; `probe_environment()` guards against exceptions (a crashing probe counts as a fail rather than aborting the sweep). `probe_components_for_preset()` decides the preflight scope (yosys ↔ contains Synthesis, dreamplace ↔ contains place/legalization; the PDK is covered by `validate_project_config`, and the slang check is left to the synthesis step).

### 5.4 Extending signoff (`ecc signoff` and the engine reports)

- **CLI layer**: `cli/commands/signoff.py` + `cli/command_handlers/signoff.py`. `_resolve_workspace()` uniformly resolves `--workspace` versus `--project/--run-id` (conflict → `project_workspace_conflict`). inspect reuses `runtime/signoff_export.py::inspect_signoff_package` (blocked still exits 0); export reuses `export_signoff_package_archive` (`RuntimeApiError` → `signoff_incomplete`).
- **Engine layer**: the `chipcompiler/engine/signoff/` package — `__init__.py` holds the signoff collector `SignoffPackageCollector` (with the thin `text_report()` entry) plus the re-exported public API; the text design report implementation is split by responsibility (`report.py` orchestration / `report_data.py` data contract / `report_extract.py` parsers + workspace collection / `report_sections.py` section extraction / `report_timing.py` the timing chain / `report_text.py` formatting), all exposed through the package `__init__` (`from chipcompiler.engine.signoff import generate_text_report`). The public import surface stays single; adding a report section = adding an `_extract_<family>(q)` in `report_sections.py` (or the timing chain) and calling it from the orchestration in `report.py`.

### 5.5 Extending QoR scoring / checklist reports (`ecc report`)

- `engine/qor_report.py`: the single-workspace port of the GUI's `projectQorTrend.ts` — constant tables (`METRIC_FAIL_VALUES`/`DIMENSION_WEIGHTS`/`QOR_SCORE_THRESHOLD`) + normalization + project-level record selection (role priority final>gate>trend; area_cost only from the last successful area step) + the `score_record` formulas + dimension weighting (no renormalization). Adding a scoreable metric = adding its threshold here and in the GUI.
- `engine/signoff/report_checklist.py`: read-only rendering of `home/checklist.json` (reports unavailable on an invalid file; never writes back).
- CLI: `cli/commands/report.py` + `cli/command_handlers/report.py`; workspace resolution reuses `inspection/discovery.py::resolve_command_workspace` (shared by signoff and report).

### 5.6 Extending the RPC (`ecc rpc serve`)

`rpc serve --stdio` starts the JSON-RPC 2.0 sidecar (`chipcompiler/runtime/stdio_server.py`). Methods are declared in `chipcompiler/runtime/methods.py::RUNTIME_METHODS` (`method_name` + a pydantic `request_model` + `handler_name`), handler implementations live in `chipcompiler/runtime/workspace_api.py`, and `runtime/server.py` mounts them uniformly; protocol details in [workspace-cli.md](workspace-cli.md). Adding a method = one `RuntimeMethodSpec` + the matching API method + a request model; no CLI-layer changes needed.

## 6. Building the CLI bundle (testing installed behavior after code changes)

The command itself can be verified directly with `.venv/bin/ecc` or `uv run ecc`; to test installed-bundle behavior (the real experience with unchanged PATH/symlinks/env), rebuild the PyInstaller bundle — exactly the official release pipeline (`ecc.spec` + `.github/actions/build-pyinstaller-bundle`):

```bash
cd ecc
.venv/bin/python -m PyInstaller ecc.spec --clean --noconfirm   # output: dist/ecc/ (onedir, ~1.8G; the first run triggers dreamplace's cmake install, which is normal)

# Install locally (the default install location of ecc-cli-setup.sh; the ~/.local/bin/ecc symlink and ~/.ecc-env.sh need no changes)
rm -rf ~/.local/ecc && mkdir -p ~/.local/ecc && cp -a dist/ecc/. ~/.local/ecc/
ecc --help            # verify doctor / signoff / report are listed

# To distribute, package the tar.gz in the official format
tar -cf /tmp/ecc.tar -C dist/ecc . && gzip -n -9 -c /tmp/ecc.tar > dist/release/ecc-cli-linux-x86_64.tar.gz
```

To roll back to the official release: `bash docs/ecc-cli-setup.sh --force` (see [ecc-cli-setup.sh](ecc-cli-setup.sh)).

## 7. Constraints and caveats (from the repository conventions)

- **Module size**: once a file exceeds roughly 800 LoC, put new functionality in a new module instead of growing it (repository CLAUDE.md section 6).
- **Python 3+**: do not use `__future__`; check `requires-python` in `pyproject.toml` for the minimum version.
- **Test placement** follows ownership boundaries; prefer whole-object comparisons; do not write tests for statically defined values; do not keep negative tests for removed logic.
- **Code review** must enforce the additional standards in [review-guidelines.md](review-guidelines.md).
- `uv.lock` is the source of truth for dependencies; `requirements_lock.txt` is auto-generated and gitignored.
- ECC-Tools' tool identifier in code is `"ecc"` (not `"ecc-tools"`); every tool module must implement `is_eda_exist / build_step / run_step`; steps execute in `multiprocessing.Process` and state persists in `workspace.flow.json`.
- After installing dependencies, `ecc` is editable — source changes take effect on the next import, no reinstall needed.
