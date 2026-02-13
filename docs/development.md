# Development Guide

Development environment setup and workflows for ECOS Chip Compiler.

## Installation

### Option 1: Nix (Recommended)

```bash
# Run directly
nix shell github:openecos-projects/ecc#chipcompiler

# Install to profile
nix profile install github:openecos-projects/ecc#chipcompiler
```

Binary cache at `serve.eminrepo.cc`. Available packages: `chipcompiler`, `ecc-tools`, `ecos-studio`.

### Option 2: Nix Development Shell

```bash
nix develop  # Provides Python 3.11+, uv, Yosys, ECC-Tools, dependencies
```

Auto-load with direnv:
```bash
echo "use flake" > .envrc
direnv allow
```

Shell hook runs `uv sync` and activates venv.

### Option 3: Manual Installation

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh  # Install uv
./build.sh                                        # Build project
source .venv/bin/activate                         # Activate venv
```

Skip OSS CAD Suite if yosys installed: `ENABLE_OSS_CAD_SUITE=false ./build.sh`

## Python API Usage

For programmatic automation and scripting:

```bash
# Install via Nix
nix shell github:openecos-projects/ecc#chipcompiler

# Or manual installation
curl -LsSf https://astral.sh/uv/install.sh | sh
./build.sh
source .venv/bin/activate
```

**Example usage:**
```python
from chipcompiler.data import create_workspace, get_pdk, get_design_parameters
from chipcompiler.engine import EngineFlow

# Create workspace with PDK and parameters
pdk = get_pdk("ics55")
parameters = get_design_parameters("ics55", "gcd")
workspace = create_workspace(
    directory="./gcd_workspace",
    origin_verilog="./design.v",
    pdk=pdk,
    parameters=parameters
)

# Run RTL-to-GDS flow
flow = EngineFlow(workspace=workspace)
flow.build_default_steps()
flow.create_step_workspaces()
flow.run_steps()
```

Full API reference: **[API Guide](api-guide.md)** | Examples: **[examples/gcd](examples/gcd/README.md)**

### Yosys Runtime Resolution

Resolution priority in `chipcompiler/tools/yosys/utility.py`:
1. Bundled runtime (`CHIPCOMPILER_OSS_CAD_DIR`)
2. System PATH (`yosys`)

Runtime handling:
- `get_yosys_command()` - Side-effect-free detection
- `get_yosys_runtime()` - Returns `(command, env)` for subprocess (no global `os.environ` mutation)
- `check_slang_plugin()` - Preflight check: `yosys -p "plugin -i slang"`

### PDK Runtime Resolution

Resolution priority for `get_pdk("ics55")` in `chipcompiler/data/pdk.py`:
1. Explicit `pdk_root` argument
2. `CHIPCOMPILER_ICS55_PDK_ROOT` env var
3. Legacy `ICS55_PDK_ROOT` env var
4. In-repo default: `chipcompiler/thirdparty/icsprout55-pdk`

Backend supports `POST /api/workspace/set_pdk_root` to set runtime path. Workspace creation persists resolved root in `parameters.json` as `PDK Root`.

Example: `CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/pdk chipcompiler`

### Build ECC-Tools C++ Bindings

```bash
mkdir -p build && cd build
cmake -G Ninja -DCMAKE_BUILD_TYPE=Debug -DBUILD_AIEDA=ON ..
ninja ieda_py
```

### Bundle ECC Runtime Dependencies

After building ECC-Tools bindings:
```bash
./scripts/autopatch-ecc-py.sh  # Auto-detect
./scripts/autopatch-ecc-py.sh --ecc-py /path/to/ecc_py.so  # Custom path
```

Process: collects `.so` deps → copies to `bin/lib/` → patches RPATH (`$ORIGIN:$ORIGIN/lib`) → verifies with `ldd`.

Requirements: `patchelf` (`apt install patchelf`), `pyelftools` (auto-installed).

Verification: `ldd chipcompiler/tools/ecc/bin/ecc_py*.so` (all deps should resolve to `$ORIGIN/lib/` or system).

Auto-called by `build.sh`, `Dockerfile`, `.devcontainer/setup.sh`.

## Code Quality

```bash
# Format & lint (recommended)
uv run ruff format chipcompiler/ test/
uv run ruff check chipcompiler/ test/

# Type check
uv run ty check              # Recommended (configured in pyproject.toml)
uv run pyright chipcompiler/
uv run mypy chipcompiler/

# Legacy
uv run black chipcompiler/ test/
uv run isort chipcompiler/ test/
```

## Testing

```bash
uv run pytest test/                                    # All tests
uv run pytest test/test_tools_yosys_utility.py -v     # Specific file
uv run pytest test/ --cov=chipcompiler --cov-report=term-missing  # Coverage
```

## Add a New EDA Tool

### 1. Create Structure
```bash
mkdir -p chipcompiler/tools/<tool_name>/{configs,scripts}
touch chipcompiler/tools/<tool_name>/{__init__.py,builder.py,runner.py,utility.py}
```

### 2. Implement Interface

**builder.py:**
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

**runner.py:**
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
            cwd=workspace_step.path, capture_output=True, timeout=workspace_step.timeout
        )
        return StateEnum.Success if result.returncode == 0 else StateEnum.Incomplete
    except Exception as e:
        workspace_step.log_error(str(e))
        return StateEnum.Incomplete
```

**__init__.py:**
```python
from .builder import build_step, build_step_space, build_step_config
from .runner import is_eda_exist, run_step

__all__ = ["build_step", "build_step_space", "build_step_config", "is_eda_exist", "run_step"]
```

### 3. Add Configs & Scripts
- JSON templates in `configs/`
- TCL/Python/Shell scripts in `scripts/`

### 4. Integrate into Flow
Update `EngineFlow.build_default_steps()` or use `add_step()`.

### 5. Write Tests
```python
# test/test_tools_<tool_name>.py
import pytest
from chipcompiler.tools.<tool_name> import is_eda_exist, run_step

@pytest.mark.skipif(not is_eda_exist(), reason="<tool_name> not installed")
def test_run_step():
    # Test implementation
    pass
```

## Common Workflows

### Debug Flow Step
1. Check `workspace_step.logs/` for tool output
2. Inspect `workspace_step.config/` for configs
3. Verify `workspace_step.input/` files
4. Run individual step: `EngineFlow.run_step()`

### Modify Flow Sequence
1. Edit `EngineFlow.build_default_steps()` or use `add_step()`
2. Persist: `flow.save()` → `workspace.flow.json`
3. Run: `flow.run_steps()` (skips successful steps)
4. Reset: `clear_states()` to re-run

### GUI Development
1. Start backend: `chipcompiler --reload` (port 8765)
2. Start frontend: `cd gui && pnpm run tauri:dev`
3. Frontend hot-reloads; backend needs restart (or --reload)

### Add API Endpoint
1. Define schema: `chipcompiler/services/schemas/`
2. Implement logic: `chipcompiler/services/services/`
3. Create router: `chipcompiler/services/routers/`
4. Register: `chipcompiler/services/main.py`
5. Test: Swagger UI at `http://localhost:8765/docs`

## Release Builds

### Python Package
```bash
uv build
```

### Standalone Executable
```bash
./build.sh --release
```

Output in `dist/`.

## Related Documentation

- [Architecture](architecture.md) - System design and patterns
- [API Guide](api-guide.md) - Python API usage
- [GUI Development Guide](gui-guide.md) - GUI development
