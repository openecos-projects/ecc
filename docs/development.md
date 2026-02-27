# Development Guide

Development environment setup and workflows for ECOS Chip Compiler.

## Installation

### Option 1: Nix Development Shell (Recommended)

```bash
nix develop  # Provides Python 3.11+, uv, Yosys, ECC-Tools, dependencies
```

Auto-load with direnv:
```bash
echo "use flake" > .envrc
direnv allow
```

Shell hook runs `uv sync` and activates venv. Binary cache at [serve.eminrepo.cc](https://serve.eminrepo.cc).

### Option 2: Manual Installation

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh  # Install uv
./build.sh                                        # Build project
source .venv/bin/activate                         # Activate venv
```

Skip OSS CAD Suite if yosys installed: `ENABLE_OSS_CAD_SUITE=false ./build.sh`

## CLI Usage

For command-line automation and scripting, run CLI via Nix:

```bash
# Run directly from project root
nix run .#cli -- --workspace ./ws \
                --rtl ./rtl/top.v \
                --design top \
                --top top \
                --clock clk \
                --pdk-root /path/to/ics55

# Filelist mode
nix run .#cli -- --workspace ./ws \
                --rtl ./rtl/filelist.f \
                --design top \
                --top top \
                --clock clk \
                --pdk-root /path/to/ics55 \
                --freq 200
```

If you need an interactive environment for development, use `nix develop`.

REST API reference: **[API Guide](api-guide.md)** | Examples: **[examples/gcd](examples/gcd/README.md)**

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
cmake -G Ninja -DCMAKE_BUILD_TYPE=Debug -DBUILD_ECOS=ON ..
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

## Bazel Build System

Bazel is used for reproducible release builds (API server bundle, Tauri GUI bundle, ECC-Tools C++ compilation). Day-to-day development still uses `uv`/`pytest`/`nix develop` as described above.

### Prerequisites

- Bazel 9+ (via Bazelisk recommended)
- `uv` on PATH (required by the `uv_export` repository rule)
- Python 3.11 virtualenv at `.venv/` (used by ECC-Tools cmake build for ABI matching)

### Key Build Targets

```bash
bazel build //chipcompiler/thirdparty:ecc_py_cmake   # ECC-Tools C++ build
bazel build //:api_server_bundle                      # PyInstaller API server executable
bazel build //:tauri_bundle                           # Full Tauri GUI bundle
bazel build //:release_bundle                         # Release artifact
```

Use `--config=ghproxy` behind restricted networks to route downloads through a GitHub mirror proxy.

### Python Dependency Management

`uv.lock` is the single source of truth for Python dependencies. Bazel consumes it automatically:

1. The `uv_export` repository rule runs `uv export` at module resolution time
2. This generates `requirements_lock.txt` in a Bazel repository -- developers never run this manually
3. `requirements_lock.txt` is NOT committed to the repo (listed in `.gitignore`)
4. `rules_python` `pip.parse` reads the generated lockfile to create `@pypi` hub

To add or update a Python dependency: edit `pyproject.toml`, run `uv lock`, and Bazel picks up the change on next build.

### Project Structure

```
MODULE.bazel              # Root module: deps, python toolchain, uv_export, pip, external repos
BUILD.bazel               # Root targets: api_server_bundle, tauri_bundle, release_bundle
.bazelrc                  # Build flags: disk cache, sandbox, PATH passthrough, ghproxy config
bazel/
  BUILD.bazel             # PyInstaller alias
  root_defs.bzl           # Macros: chipcompiler_api_server_bundle, chipcompiler_tauri_bundle
  scripts/
    build-tauri-bundle.sh # Shell script for Tauri build orchestration
```

### External Repositories

Defined in `MODULE.bazel`:

| Repository | Source | Purpose |
|---|---|---|
| `@icsprout55_pdk` | GitHub archive | ICS55 PDK (with `make unzip` post-setup) |
| `@patchelf` | GitHub release | ELF binary patching tool |
| `@oss_cad_suite` | GitHub release | Yosys and other OSS EDA tools |
| `@ecc_tools_src` | Local submodule | ECC-Tools C++ source (via `local_source_repo`) |
| `@appimagetool_x86_64_linux` | GitHub release | AppImage packaging tool |

### Lockfile Maintenance

To update `MODULE.bazel.lock` after changing `MODULE.bazel` or Bazel dependency versions:

```bash
bazel mod deps --lockfile_mode=update
```

## Related Documentation

- [Architecture](architecture.md) - System design and patterns
- [API Guide](api-guide.md) - REST API usage
- [GUI Development Guide](gui-develop-guide.md) - GUI development
