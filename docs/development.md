# Development Guide

Development environment setup and workflows for ECOS Chip Compiler.

## Installation

### Option 1: Bazel Dev Setup (Recommended)

If not using Nix, set up the full development environment with a single command:

```bash
bazel run //:prepare_dev
```

This runs two steps:
1. `uv sync --frozen --all-groups --python 3.11` — creates the Python venv
2. Builds and extracts the ECC runtime bundle → `chipcompiler/tools/ecc/bin/`
3. Builds and installs DreamPlace operators (source build, dev only) → `chipcompiler/thirdparty/ecc-dreamplace/dreamplace/ops/`

ECC-Tools and DreamPlace are built in parallel by Bazel. On memory-constrained machines, limit parallelism:
```bash
bazel run //:prepare_dev --jobs=1
```

### Option 2: Nix Development Shell

```bash
nix develop  # Provides Python 3.11+, uv, Yosys, ECC-Tools, dependencies
```

Auto-load with direnv:
```bash
echo "use flake" > .envrc
direnv allow
```

Shell hook runs `uv sync --frozen --all-groups --python 3.11` and activates venv. Binary cache at [serve.eminrepo.cc](https://serve.eminrepo.cc).

## Bazel Build System

Bazel is used for reproducible release builds and ECC-Tools C++ compilation. Requires Bazel 8+ and `uv` on PATH.

```bash
bazel build //chipcompiler/thirdparty:ecc_py_cmake       # ECC-Tools C++ build
bazel run //bazel/scripts:install_dreamplace              # Build + install DreamPlace .so (via @ecc-dreamplace)
bazel run //bazel/scripts:clean_dreamplace                # Remove installed DreamPlace artifacts
bazel run //bazel/scripts:prepare_dev                     # Full dev environment setup (ECC + DreamPlace)
```

Use `--config=ghproxy` behind restricted networks. For `git_override` deps (e.g. `ecos-bazel`), configure git mirror directly:

```bash
git config --global url."https://ghfast.top/https://github.com/".insteadOf "https://github.com/"
bazel build --config=ghproxy //...
```

Python deps are managed via `uv.lock` — Bazel consumes it automatically through `uv_export`. To update: edit `pyproject.toml`, run `uv lock`.

## Release Builds

### Python Package
```bash
uv build
```

### Bazel Wheel Build (ECC Runtime + auditwheel)

Build a portable wheel with Bazel-managed ECC runtime and hermetic uv/Python:

```bash
bazel build //:raw_wheel   # Sandboxed, cacheable — produces raw .whl
bazel run //:build_wheel   # auditwheel repair + smoke test
```

Artifacts:
- Raw wheels: `dist/wheel/raw/`
- Repaired wheels: `dist/wheel/repaired/`
- auditwheel report: `dist/wheel/reports/show.txt`
- Checksums: `dist/wheel/SHA256SUMS`

Requirements:
- Linux x86_64
- `auditwheel` (installed via dev deps)

Common failures:
- `auditwheel` missing: run `uv sync --frozen --all-groups --python 3.11`
- `ecc_py*.so` missing after bundle extraction: build/install runtime (`bazel run //:prepare_dev`)
- auditwheel policy mismatch (e.g. glibc symbols too new): rebuild on older compatible base or adjust target policy
- missing runtime libraries: inspect `dist/wheel/reports/show.txt`

### DreamPlace Wheel Build

DreamPlace has its own standalone build, CI/CD, and release pipeline.

- **Dev mode**: `bazel run //:prepare_dev` builds .so files from source and installs them into the source tree.
  `uv sync --extra dreamplace` resolves via workspace member.

- **Release mode**: A pre-built wheel is downloaded from
  [GitHub Releases](https://github.com/openecos-projects/ecc-dreamplace/releases).
  The parent `Makefile` (`make build`) fetches it automatically via the
  `_download_dreamplace_wheel` target. The CI workflow installs it directly:

  ```bash
  uv pip install --no-deps https://github.com/openecos-projects/ecc-dreamplace/releases/download/v0.1.0-alpha.1/ecc_dreamplace-0.1.0a1-py3-none-manylinux_2_34_x86_64.whl
  ```

### Standalone Executable
```bash
source .venv/bin/activate
bazel build //:server_bundle
```

Output in `bazel-bin/server_bundle/`.

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
uv run pytest test/formal/ -v                          # Formal verification tests only
```

### Formal Verification

z3-based formal verification. See [test/formal/README.md](../test/formal/README.md) for details on the approach, test inventory, and known bugs found.

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

## Integrating a Thirdparty Tool into the Build System

ECC uses a dual-build strategy: **uv workspace** for dev, **Bazel** (+ Nix) for release. Reference `ecc-dreamplace` as a working example.

**Principle**: Avoid modifying the thirdparty tool's own build system (CMakeLists, setup.py, etc.). Prefer solving build issues from the Bazel side or ECC's build configuration (cache entries, env vars, wrapper scripts).

### 1. Python deps

Add to uv workspace in root `pyproject.toml` (`[tool.uv.workspace].members`, `[tool.uv.sources]`, `[project.optional-dependencies]`), then `uv lock`.

### 2. Dev build

If the tool has compiled artifacts (`.so`, generated configs):
- Add a Bazel build target in `chipcompiler/thirdparty/BUILD.bazel`
- Create `bazel/scripts/install-<tool>.sh` with manifest-based install/clean (see `install-dreamplace.sh`)
- Register `install_<tool>` and `clean_<tool>` targets in `bazel/scripts/BUILD.bazel`
- Wire into `prepare-dev.sh` with explicit `RUNFILES_DIR="${RF}"`

### 3. Release build

Add runtime artifacts to `//chipcompiler:chipcompiler_runtime_data` (consumed by `raw_wheel` and `server_bundle`). For Nix, add to flake build inputs.

### 4. Bazel sandbox deps

Add the tool's extra to `uv_export(extras=[...])` in `MODULE.bazel`; reference as `@pypi//<pkg>` in BUILD files.

### 5. EDA tool module

Create `chipcompiler/tools/<tool>/` with `__init__.py`, `builder.py`, `runner.py`. Each tool must implement `is_eda_exist`, `build_step`, `run_step`. Integrate into flow via `EngineFlow.build_default_steps()` or `add_step()`. See [Add a New EDA Tool](#add-a-new-eda-tool) above for the full interface and code examples.

### Pitfalls

- **Runfiles**: child scripts called from `prepare-dev.sh` cannot resolve `RUNFILES_DIR` from `BASH_SOURCE[0]` — pass it explicitly
- **File ownership**: use `cp --no-preserve=ownership` and `tar --no-same-owner` when extracting Bazel outputs to avoid root-owned files in devcontainer builds

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

REST API reference: Examples: **[examples/gcd](examples/gcd/README.md)**

### Yosys Runtime Resolution

Resolution priority in `chipcompiler/tools/yosys/utility.py`:
1. Bundled runtime (`CHIPCOMPILER_OSS_CAD_DIR`)
2. System PATH (`yosys`)

Runtime handling:
- `get_yosys_command()` - Side-effect-free detection
- `get_yosys_runtime()` - Returns `(command, env)` for subprocess (no global `os.environ` mutation)
- `check_slang_plugin()` - Preflight check: `yosys -p "plugin -i slang"`

#### Troubleshooting: Yosys executable not found

If you see this error:

```
RuntimeError: Yosys executable not found in system PATH, and CHIPCOMPILER_OSS_CAD_DIR is not set.
Please install yosys or set CHIPCOMPILER_OSS_CAD_DIR to the OSS CAD Suite root directory.
```

Download the [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/releases) pre-built package for your platform, extract it, and set the environment variable:

```bash
# Download and extract (example for Linux x86_64)
wget https://github.com/YosysHQ/oss-cad-suite-build/releases/download/<version>/oss-cad-suite-linux-x64-<date>.tgz
tar -xzf oss-cad-suite-linux-x64-<date>.tgz

# Set the environment variable
export CHIPCOMPILER_OSS_CAD_DIR=/path/to/oss-cad-suite

# Or add yosys to PATH directly
source /path/to/oss-cad-suite/environment
```

### PDK Runtime Resolution

Resolution priority for `get_pdk("ics55")` in `chipcompiler/data/pdk.py`:
1. Explicit `pdk_root` argument
2. `CHIPCOMPILER_ICS55_PDK_ROOT` env var
3. Legacy `ICS55_PDK_ROOT` env var
4. In-repo default: `chipcompiler/thirdparty/icsprout55-pdk`

Backend supports `POST /api/workspace/set_pdk_root` to set runtime path. Workspace creation persists resolved root in `parameters.json` as `PDK Root`.

Example: `CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/pdk chipcompiler`

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

## Related Documentation

- [Architecture](architecture.md) - System design and patterns
