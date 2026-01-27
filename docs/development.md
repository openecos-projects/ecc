# Development Guide

This document covers the development environment setup and common workflows for ECOS Chip Compiler.

## Environment Setup

### Option 1: Nix Development Environment (recommended)

```bash
# Enter the development environment
nix develop
```

Use direnv for automatic loading:

```bash
echo "use flake" > .envrc
direnv allow
```

### Option 2: Manual Installation

```bash
# Install the uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Build the project
./build.sh

# Activate the virtual environment
source .venv/bin/activate
```

If yosys is already installed on your system, you can skip the OSS CAD Suite download:

```bash
ENABLE_OSS_CAD_SUITE=false ./build.sh
```

### Build ECC-Tools C++ bindings

```bash
mkdir -p build && cd build
cmake -G Ninja -DCMAKE_BUILD_TYPE=Debug -DBUILD_AIEDA=ON ..
ninja ieda_py
```

## Code Quality

### Formatting

```bash
# Use ruff (recommended)
uv run ruff format chipcompiler/ test/
uv run ruff check chipcompiler/ test/

# Traditional tools
uv run black chipcompiler/ test/
uv run isort chipcompiler/ test/
```

### Type Checking

```bash
# Use ty (recommended; configured in pyproject.toml)
uv run ty check

# Or use other tools
uv run pyright chipcompiler/
uv run mypy chipcompiler/
```

### Run Tests

```bash
# All tests
uv run pytest test/

# Specific file
uv run pytest test/test_tools_yosys.py -v

# Coverage report
uv run pytest test/ --cov=chipcompiler --cov-report=term-missing
```

## Add a New EDA Tool

### 1. Create the tool directory

```bash
mkdir -p chipcompiler/tools/<tool_name>/{configs,scripts}
touch chipcompiler/tools/<tool_name>/{__init__.py,builder.py,runner.py,utility.py}
```

### 2. Implement standard interfaces

**builder.py**:

```python
from chipcompiler.data import Workspace, WorkspaceStep, StepEnum

def build_step(workspace: Workspace, step: StepEnum) -> WorkspaceStep:
    """Create the step workspace"""
    workspace_step = WorkspaceStep(
        workspace=workspace,
        step=step,
        tool="<tool_name>"
    )
    return workspace_step

def build_step_space(workspace_step: WorkspaceStep) -> None:
    """Initialize directory structure"""
    workspace_step.create_directories()

def build_step_config(workspace_step: WorkspaceStep) -> None:
    """Generate tool config file"""
    config = {
        "input": workspace_step.input_path,
        "output": workspace_step.output_path,
        # ... other configuration
    }
    workspace_step.write_config(config)
```

**runner.py**:

```python
import subprocess
from chipcompiler.data import WorkspaceStep, StateEnum

def is_eda_exist() -> bool:
    """Check whether the tool is available"""
    try:
        subprocess.run(["<tool_name>", "--version"],
                      capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def run_step(workspace_step: WorkspaceStep) -> StateEnum:
    """Run the tool"""
    try:
        result = subprocess.run(
            ["<tool_name>", "-c", workspace_step.config_file],
            cwd=workspace_step.path,
            capture_output=True,
            timeout=workspace_step.timeout
        )
        if result.returncode == 0:
            return StateEnum.Success
        return StateEnum.Incomplete
    except Exception as e:
        workspace_step.log_error(str(e))
        return StateEnum.Incomplete
```

**__init__.py**:

```python
from .builder import build_step, build_step_space, build_step_config
from .runner import is_eda_exist, run_step

__all__ = [
    "build_step",
    "build_step_space",
    "build_step_config",
    "is_eda_exist",
    "run_step"
]
```

### 3. Add config templates

Add JSON config templates in the `configs/` directory.

### 4. Add tool scripts

Add TCL/Python/Shell scripts in the `scripts/` directory.

### 5. Integrate into the flow

Update `EngineFlow.build_default_steps()` or use `add_step()`.

### 6. Write tests

```python
# test/test_tools_<tool_name>.py
import pytest
from chipcompiler.tools.<tool_name> import is_eda_exist, run_step

@pytest.mark.skipif(not is_eda_exist(), reason="<tool_name> not installed")
def test_run_step():
    # ... test implementation
    pass
```


## Release Builds

### Python package

```bash
uv build
```

### Standalone executable (Run-Server mode)

```bash
./build.sh --release
```

Generated files are in the `dist/` directory.

## Related Documentation

- [Architecture](architecture.md)
- [API Guide](api-guide.md)
- [GUI Development Guide](gui-guide.md)
