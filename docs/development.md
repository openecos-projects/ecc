# Development Guide

Development environment setup and workflows for ECOS Chip Compiler.

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
uv sync --no-build-isolation-package ecc-dreamplace --no-binary-package ecc-tools-bin --verbose
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
from chipcompiler.data import Workspace, WorkspaceStep, StepEnum

def build_step(workspace: Workspace, step: StepEnum) -> WorkspaceStep:
    return WorkspaceStep(workspace=workspace, step=step, tool="<tool_name>")

def build_step_space(workspace_step: WorkspaceStep) -> None:
    workspace_step.create_directories()

def build_step_config(workspace_step: WorkspaceStep) -> None:
    config = {"input": workspace_step.input_path, "output": workspace_step.output_path}
    workspace_step.write_config(config)
```

`runner.py`:

```python
import subprocess
from chipcompiler.data import WorkspaceStep, StateEnum

def is_eda_exist() -> bool:
    try:
        subprocess.run(["<tool_name>", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def run_step(workspace_step: WorkspaceStep) -> StateEnum:
    try:
        result = subprocess.run(
            ["<tool_name>", "-c", workspace_step.config_file],
            cwd=workspace_step.path,
            capture_output=True,
            timeout=workspace_step.timeout,
        )
        return StateEnum.Success if result.returncode == 0 else StateEnum.Incomplete
    except Exception as e:
        workspace_step.log_error(str(e))
        return StateEnum.Incomplete
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

## CLI Usage

For command-line automation and scripting, run CLI via Nix:

```bash
nix run . -- init gcd
nix run . -- check --project gcd
nix run . -- run --project gcd
nix run . -- status --project gcd
nix run . -- metrics --project gcd
nix run . -- log --project gcd
```

Or run through the active uv environment:

```bash
uv run ecc init gcd
uv run ecc check --project gcd
uv run ecc run --project gcd
```

The project config is the CLI input surface:

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

If Yosys is not found, download the
[OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/releases)
pre-built package for your platform, extract it, and set:

```bash
export CHIPCOMPILER_OSS_CAD_DIR=/path/to/oss-cad-suite
```

Or add Yosys to PATH directly:

```bash
source /path/to/oss-cad-suite/environment
```

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
4. In-repo default: `chipcompiler/thirdparty/icsprout55-pdk`.

Backend supports `POST /api/workspace/set_pdk_root` to set runtime path.
Workspace creation persists resolved root in `parameters.json` as `PDK Root`.

Example:

```bash
CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/pdk uv run ecc
```

## Common Workflows

### Debug Flow Step

1. Check `workspace_step.logs/` for tool output.
2. Inspect `workspace_step.config/` for configs.
3. Verify `workspace_step.input/` files.
4. Run individual step with `EngineFlow.run_step()`.

### Modify Flow Sequence

1. Edit `EngineFlow.build_default_steps()` or use `add_step()`.
2. Persist with `flow.save()` to `workspace.flow.json`.
3. Run with `flow.run_steps()`; successful steps are skipped.
4. Use `clear_states()` to re-run.

## Related Documentation

- [Architecture](architecture.md) - System design and patterns
- [Examples](examples/) - Example projects and CLI usage
