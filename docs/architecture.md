# Architecture

ECOS Chip Compiler orchestrates EDA tools through a layered, plugin-based architecture.

## Layered Architecture

```
┌────────────────────────────────────────────────────┐
│  Service Layer (chipcompiler/services/)            │
│  FastAPI REST API + CORS                           │
├────────────────────────────────────────────────────┤
│  RTL2GDS Layer (chipcompiler/rtl2gds/)             │
│  Pre-configured flow templates                     │
├────────────────────────────────────────────────────┤
│  Engine Layer (chipcompiler/engine/)               │
│  EngineFlow (orchestration) + EngineDB (analysis)  │
├────────────────────────────────────────────────────┤
│  Tool Layer (chipcompiler/tools/)                  │
│  yosys, ecc, klayout, openroad, magic              │
├────────────────────────────────────────────────────┤
│  Data Layer (chipcompiler/data/)                   │
│  Workspace, WorkspaceStep, Parameters, PDK         │
├────────────────────────────────────────────────────┤
│  Utility Layer (chipcompiler/utility/)             │
│  Logging, JSON I/O, file operations                │
└────────────────────────────────────────────────────┘
```

## Core Design Patterns

### 1. Plugin Architecture
Tools loaded dynamically via `load_eda_module()`. Standard interface:
```python
def is_eda_exist() -> bool         # Check availability
def build_step() -> WorkspaceStep  # Create workspace
def build_step_space() -> None     # Initialize directories
def build_step_config() -> None    # Generate config
def run_step() -> StateEnum        # Execute tool
```

### 2. Workspace Isolation
Each step has isolated directory structure:
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
```
Unstart → Ongoing → Success
                  ↘ Incomplete
```
States: Unstart (not started), Ongoing (running), Success (completed), Incomplete (failed), Invalid, Ignored, Pending.

### 4. Configuration as Data
- `workspace.flow.json` - Flow state persistence
- `config/*.json` - Tool configurations

### 5. Process Isolation
Steps execute in subprocesses (`multiprocessing.Process`) for resource isolation, timeout control, and fault isolation.

### 6. Flow Persistence
Saved flow state enables resume after interruption, state checks, and incremental execution.

## Data Flow

### Inter-step Transfer
```
Synthesis → output/design.v
              ↓
Placement → input/design.v → output/design.def
              ↓
Routing → input/design.def → ...
```

**Rules:**
- First step uses `workspace.design.origin_verilog/origin_def`
- Subsequent steps chain: previous `output/` → next `input/`

### Typical Execution Flow
```
1. Create Workspace (PDK, parameters, RTL)
2. Initialize EngineFlow (load/create workspace.flow.json)
3. Run flow.run_steps()
   - Iterate workspace_steps
   - Skip Success states
   - Run remaining: Ongoing → subprocess → Success/Incomplete
4. Optional: Initialize EngineDB for post-flow analysis
```

## Layer Details

### Data Layer (chipcompiler/data/)

| Entity | Purpose |
|--------|---------|
| `Workspace` | Top-level container: design files, PDK, parameters, flow state |
| `WorkspaceStep` | Per-step workspace: inputs, outputs, configs, logs, reports |
| `Parameters` | Design specs: die size, clock frequency, buffer/filler/tie cells |
| `PDK` | Tech library paths: LEF, liberty, timing, SPEF |
| `StepEnum` | Flow steps: SYNTHESIS, NETLIST_OPT, PLACEMENT, CTS, TIMING_OPT_*, LEGALIZATION, ROUTING, FILLER |
| `StateEnum` | Step states: Unstart, Ongoing, Success, Incomplete, Invalid, Ignored, Pending |

### Engine Layer (chipcompiler/engine/)

**EngineFlow (flow.py):**
- Load/save flow config from `workspace.flow.json`
- Build workflow: `build_default_steps()` or `add_step()`
- Chain workspaces: `create_step_workspaces()` links input/output
- Execute: `run_steps()` runs steps in subprocess, tracks state/runtime
- State management: `check_state()`, `set_state()`, `clear_states()`

**EngineDB (db.py):**
Wraps ECC-Tools C++ engine for post-flow circuit analysis. Initialized with a WorkspaceStep (typically last successful).

### Tool Layer (chipcompiler/tools/)

**Directory Structure:**
```
tool_name/
├── __init__.py   # Interface exports
├── builder.py    # Workspace + config creation
├── runner.py     # Tool execution
├── utility.py    # Helpers
├── configs/      # Config templates
├── scripts/      # Tool scripts (TCL/Python/Shell)
└── bin/          # Binaries (ecc only)
    └── lib/      # Runtime dependencies (ecc only)
```

**Integrated Tools:**

**Yosys** - RTL synthesis (Verilog → gate-level netlist)

**ECC-Tools** - Physical design backend
- Tool name: `"ecc"` (e.g., `add_step(StepEnum.PLACEMENT, tool="ecc")`)
- Source: `chipcompiler/thirdparty/ecc-tools` (C++ engine)
- Wrapper: `chipcompiler/tools/ecc/` (Python integration)
- Operations: netlist optimization, placement, CTS, timing optimization, legalization, routing, filler
- I/O: DEF/Verilog, PDK LEF/liberty, SDC
- Runtime deps bundled in `bin/lib/` with RPATH `$ORIGIN:$ORIGIN/lib` for portability

**KLayout** - Layout visualization, GDS/OASIS handling, DRC

**Runtime Dependency Bundling (ECC-Tools):**
Script `scripts/autopatch-ecc-py.sh` collects `.so` dependencies, copies to `bin/lib/`, patches RPATH with `auto-patchelf`, verifies with `ldd`. Enables deployment without build directory.

**Yosys Runtime Resolution:**
1. `utility.get_yosys_command()` - Resolve executable (bundled `CHIPCOMPILER_OSS_CAD_DIR` → system PATH)
2. `utility.get_yosys_runtime()` - Prepare subprocess env (no global `os.environ` mutation)
3. `utility.check_slang_plugin()` - Preflight check
4. `runner.run_step()` - Execute with resolved `(command, env)`

### Service Layer (chipcompiler/services/)

FastAPI REST API structure:
- `main.py` - App + CORS config
- `routers/` - Endpoint definitions
- `schemas/` - Pydantic models
- `services/` - Business logic
- `run_server.py` - Uvicorn entry

API docs at `/docs` (Swagger UI). The GUI and Tauri backend have been moved to `ecos/gui/` in the [ecos-studio](https://github.com/0xharry/ecos-studio) repo.

### RTL2GDS Layer (chipcompiler/rtl2gds/)

`build_rtl2gds_flow()` returns complete flow: SYNTHESIS → FLOORPLAN → NETLIST_OPT → PLACEMENT → CTS → LEGALIZATION → ROUTING → DRC → FILLER.

### Benchmark Module (benchmark/)

Batch testing infrastructure:
- `benchmark.py` - `run_benchmark()`, `benchmark_statis()`, `benchmark_metrics()`
- `parameters.py` - `get_parameters(pdk_name, design)` factory
- JSON configs: `ics55_benchmark.json`, `ics55_tapeout.json`

Usage: `parameters = get_parameters("ics55", "gcd")`

## Related Documentation

- [Development Guide](development.md) - Setup, workflows, adding tools
