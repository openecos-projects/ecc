# API Guide

This document explains how to use ECOS Chip Compiler's Python API.

## Python API

### Basic Usage

```python
from chipcompiler.engine import EngineFlow
from chipcompiler.data import Workspace, Parameters, PDK

# Create a workspace
workspace = Workspace(
    name="my_design",
    pdk=PDK.from_config("path/to/pdk/config.json"),
    parameters=Parameters.from_config("path/to/params.json"),
    origin_verilog="path/to/design.v"
)

# Initialize the flow engine
flow = EngineFlow(workspace)
flow.build_default_steps()  # Build default flow steps
flow.create_step_workspaces()  # Create step workspaces

# Run the full flow
flow.run_steps()

# Check flow status
for step in flow.workspace_steps:
    print(f"{step.name}: {step.state}")
```

### Custom Flow

```python
from chipcompiler.data import StepEnum

flow = EngineFlow(workspace)

# Manually add steps
flow.add_step(StepEnum.SYNTHESIS, "yosys")
flow.add_step(StepEnum.PLACEMENT, "ecc")
flow.add_step(StepEnum.CTS, "ecc")
flow.add_step(StepEnum.ROUTING, "ecc")

flow.create_step_workspaces()
flow.run_steps()
```

### Incremental Execution

```python
# First run
flow.run_steps()

# After fixing errors, rerun only failed steps
flow = EngineFlow.load("workspace/my_design")
flow.run_steps()  # Automatically skip successful steps
```

### Single-Step Execution

```python
# Run a specific step
flow.run_step(flow.workspace_steps[0])

# Check status
state = flow.check_state("SYNTHESIS")
print(state)  # StateEnum.Success / Incomplete
```

### State Management

```python
# Clear all states (start over)
flow.clear_states()

# Set a specific step state
flow.set_state("SYNTHESIS", StateEnum.Unstart)

# Save flow configuration
flow.save()
```

### Use a Predefined Flow

```python
from chipcompiler.rtl2gds import build_rtl2gds_flow

# Get the full RTL-to-GDS flow
steps = build_rtl2gds_flow()

flow = EngineFlow(workspace)
for step_enum, tool, state in steps:
    flow.add_step(step_enum, tool)

flow.create_step_workspaces()
flow.run_steps()
```

### Database Engine

```python
# Initialize the database engine (uses ECC-Tools engine internally)
db_engine = flow.init_db_engine()

# Use the ECC-Tools Python bindings for post-flow analysis
# db_engine provides access to circuit data for analysis and optimization
```

## Related Documentation

- [Architecture](architecture.md)
- [Development Guide](development.md)
- [GUI Development Guide](gui-guide.md)
