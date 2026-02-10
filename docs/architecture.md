# Architecture

This document describes ECOS Chip Compiler's software architecture in detail.

## Layered Architecture

```
┌────────────────────────────────────────────────────┐
│  GUI Layer (chipcompiler/gui/)                      │
│  ├─ Tauri (Rust backend)                            │
│  ├─ Vue 3 + TypeScript (frontend)                   │
│  ├─ PixiJS (WebGL/WebGPU rendering)                 │
│  └─ PrimeVue + Tailwind CSS (UI)                    │
├────────────────────────────────────────────────────┤
│  Service Layer (chipcompiler/services/)             │
│  ├─ FastAPI REST API                                │
│  ├─ Workspace management endpoints                  │
│  └─ CORS support                                    │
├────────────────────────────────────────────────────┤
│  RTL2GDS Layer (chipcompiler/rtl2gds/)              │
│  └─ Full flow builder                               │
├────────────────────────────────────────────────────┤
│  Engine Layer (chipcompiler/engine/)                │
│  ├─ EngineFlow - Flow orchestration                 │
│  └─ EngineDB - Database engine lifecycle            │
├────────────────────────────────────────────────────┤
│  Tool Layer (chipcompiler/tools/)                   │
│  ├─ yosys/ - RTL synthesis                           │
│  ├─ ecc/ - Placement and routing (ECC-Tools)        │
│  ├─ klayout/ - Layout viewer                         │
│  ├─ openroad/ - Open source backend                  │
│  └─ magic/ - Layout tool                             │
├────────────────────────────────────────────────────┤
│  Data Layer (chipcompiler/data/)                    │
│  ├─ Workspace - Top-level design container          │
│  ├─ WorkspaceStep - Step-level workspace            │
│  ├─ Parameters - Design parameters                  │
│  └─ PDK - PDK configuration                         │
├────────────────────────────────────────────────────┤
│  Utility Layer (chipcompiler/utility/)              │
│  └─ Logging, JSON I/O, file operations              │
└────────────────────────────────────────────────────┘
```

## Core Design Patterns

### 1. Plugin Architecture

EDA tools are loaded dynamically via `load_eda_module()`. Each tool must implement the standard interface:

```python
def is_eda_exist() -> bool      # Check whether the tool is available
def build_step() -> WorkspaceStep  # Create the step workspace
def build_step_space() -> None  # Initialize directory structure
def build_step_config() -> None # Generate tool configuration
def run_step() -> StateEnum     # Run the tool
```

### 2. Workspace Isolation

Each flow step has its own directory structure:

```
workspace_step/
├── input/      # Input files
├── output/     # Output files
├── config/     # Tool configuration
├── logs/       # Run logs
├── scripts/    # Execution scripts
├── reports/    # Analysis reports
├── data/       # Intermediate data
├── features/   # Feature data
└── analysis/   # Analysis results
```

### 3. State Machine

Step state transitions:

```
Unstart → Ongoing → Success
                  ↘ Incomplete
```

- **Unstart**: Not started
- **Ongoing**: Running
- **Success**: Completed successfully
- **Incomplete**: Failed

### 4. Configuration as Data

Flow definitions and tool configurations are stored as JSON:
- `workspace.flow.json` - Flow state
- `config/*.json` - Tool configuration

### 5. Process Isolation

Steps execute in subprocesses via `multiprocessing.Process`, providing:
- Resource isolation
- Timeout control
- Fault isolation

### 6. Flow Persistence

After saving flow state, it supports:
- Resume after interruption
- State checks
- Incremental execution

## Data Flow

### Inter-step Data Transfer

```
Step 1 (Synthesis)
   │
   ├─ output/design.v (netlist)
   │
   ▼
Step 2 (Placement)
   │
   ├─ input/design.v (from previous step output)
   ├─ output/design.def
   │
   ▼
Step 3 (Routing)
   ...
```

**Rules**:
- The first step uses `workspace.design.origin_verilog/origin_def`
- Subsequent steps use the previous step's `output/` as `input/`

### Typical Flow Execution

```
1. Create Workspace
   └─ Define PDK, parameters, RTL source files

2. Initialize EngineFlow
   ├─ Load/create workspace.flow.json
   ├─ Call create_step_workspaces()
   └─ Build workspace_steps list

3. Run flow.run_steps()
   ├─ Iterate each workspace_step
   │  ├─ State is Success -> skip
   │  └─ Otherwise run run_step()
   │     ├─ Set state = Ongoing
   │     ├─ Run tool in a subprocess
   │     ├─ Update state = Success/Incomplete
   │     └─ Record runtime

4. Initialize DB engine (optional)
   └─ Load ECC-Tools engine using the last successful step

5. Analysis (optional)
   └─ Use the ECC-Tools Python bindings for circuit analysis
```

## Module Details

### Data Layer (chipcompiler/data/)

| Class | Description |
|---|---|
| `Workspace` | Top-level container including design files, PDK, parameters, and flow state |
| `WorkspaceStep` | Step-level workspace managing inputs, outputs, and configuration |
| `Parameters` | Design parameters: die size, clock frequency, buffer cells, etc. |
| `PDK` | PDK paths: LEF, Liberty, timing constraints, etc. |
| `StepEnum` | Flow step type enum |
| `StateEnum` | Step state enum |

### Engine Layer (chipcompiler/engine/)

| Module | Description |
|---|---|
| `EngineFlow` | Flow orchestration: load/save configs, manage steps, run flow |
| `EngineDB` | Database engine: wraps ECC-Tools C++ engine lifecycle |

### Tool Layer (chipcompiler/tools/)

Each tool directory layout:

```
tool_name/
├── __init__.py   # Export interface
├── builder.py    # Workspace creation and config build
├── runner.py     # Tool execution
├── utility.py    # Helper functions
├── configs/      # Config templates
├── scripts/      # Tool scripts
└── bin/          # Tool binaries (ecc only)
```

### Yosys Runtime Flow (Current)

For synthesis (`chipcompiler/tools/yosys/`), runtime selection and execution are split between utility and runner:

1. `utility.get_yosys_command()` resolves executable priority: bundled runtime (`CHIPCOMPILER_OSS_CAD_DIR`) first, then system `PATH`.
2. `utility.get_yosys_runtime()` prepares subprocess-only environment.
3. `utility.check_slang_plugin()` performs preflight plugin check.
4. `runner.run_step()` uses resolved `(command, env)` for both preflight check and `yosys_synthesis.tcl`.

Key property: utility resolution and env preparation are side-effect free for process-global environment (no global mutation of `os.environ`).

### Service Layer (chipcompiler/services/)

| Module | Description |
|---|---|
| `main.py` | FastAPI app, CORS configuration |
| `routers/` | API endpoint definitions |
| `schemas/` | Pydantic request/response models |
| `services/` | Business logic implementations |
| `run_server.py` | Uvicorn entrypoint |

### GUI Layer (chipcompiler/gui/)

| Directory | Description |
|---|---|
| `src/applications/` | Core applications (PixiJS editor) |
| `src/components/` | Vue components |
| `src/composables/` | Composables |
| `src/stores/` | Pinia state management |
| `src/views/` | Page components |
| `src-tauri/` | Rust backend |

## Related Documentation

- [Development Guide](development.md)
- [API Guide](api-guide.md)
- [GUI Development Guide](gui-guide.md)
