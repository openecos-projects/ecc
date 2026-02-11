# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ChipCompiler is an ECOS chip design automation solution that orchestrates EDA tools (Yosys, ECC-Tools, OpenROAD, Magic, KLayout) to perform RTL-to-GDS synthesis and place-and-route flows. The project includes:

1. **Core Engine** - Python-based flow orchestration and EDA tool integration
2. **REST API** - FastAPI backend for programmatic access
3. **Desktop GUI** - Tauri + Vue 3 application for visual design and layout editing

The architecture follows a modular, plugin-based design with clear separation between data structures, flow orchestration, tool integration, and user interfaces.

## Development Setup and Commands

### Environment Setup

The project uses Nix and `uv` for reproducible tool provisioning.

**Option 1: Nix Development Shell (Recommended)**
```bash
nix develop
```
Automatically provides Python 3.11+, uv, Yosys with Slang, ECC-Tools, and all Python dependencies.

**Option 2: Manual Setup with uv**
```bash
bash ./build.sh
source .venv/bin/activate
```
Uses `uv` to create Python 3.11 environment, syncs dependencies from pyproject.toml, and builds ECC-Tools C++ bindings. The script also downloads OSS CAD Suite by default (set `ENABLE_OSS_CAD_SUITE=false` to skip).

**Tip:** If `python` is not found in your shell, activate the project virtualenv first:
```bash
source .venv/bin/activate
```

**Submodule initialization (first-time setup):**
```bash
git submodule update --init --recursive
```
Required for ECC-Tools engine (chipcompiler/thirdparty/ecc-tools) and icsprout55 PDK (chipcompiler/thirdparty/icsprout55-pdk).

**Option 3: Release Build**
```bash
./build.sh --release
```
Creates standalone executable via PyInstaller.

### Running Tests

Tests are located in the `test/` directory. Run with:

```bash
# Run all tests
pytest test/

# Run a specific test file
pytest test/test_tools_yosys.py
pytest test/test_tools_ieda.py

# Run with verbose output
pytest test/ -v

# Run with coverage report
pytest test/ --cov=chipcompiler --cov-report=term-missing
```

Key test files:
- **test_tools_ieda.py** - Tests ECC-Tools (ecc) place-and-route with ICS55 PDK and GCD design
- **test_ics55_batch.py** - Batch synthesis tests on ICS55 PDK
- **test_benchmark_inputs.py** - Benchmark design input tests
- **test_filelist.py** - Filelist parsing tests
- **test_service.py** - REST API endpoint tests

### Code Quality

```bash
# Format code with ruff (modern formatter)
ruff format chipcompiler/ test/

# Lint with ruff
ruff check chipcompiler/ test/

# Type checking
pyright chipcompiler/  # Primary type checker
mypy chipcompiler/     # Alternative type checker

# Legacy tools (still supported)
black chipcompiler/ test/
isort chipcompiler/ test/
```

### Building with CMake

```bash
mkdir -p build && cd build
cmake ..
make
```
Builds ECC-Tools C++ bindings. Python executable path defaults to `.venv/bin/python3`.

### Running the API Server

The REST API provides programmatic access to ChipCompiler functionality:

```bash
# Start API server (default port 8765)
chipcompiler

# Custom host and port
chipcompiler --host 127.0.0.1 --port 8000

# Development mode with auto-reload
chipcompiler --reload
```

API documentation available at `http://localhost:8765/docs` (Swagger UI).

### Running the GUI Application

The desktop GUI is built with Tauri + Vue 3:

```bash
cd chipcompiler/gui

# Install frontend dependencies
pnpm install

# Run GUI in development mode (hot reload)
pnpm run tauri:dev

# Run frontend only in browser
pnpm run dev

# Build production application (generates .dmg, .exe, .deb)
pnpm run tauri:build
```

**GUI Prerequisites:** Node.js LTS, pnpm, Rust toolchain, platform-specific Tauri dependencies (see [gui/README.md](chipcompiler/gui/README.md)).

## Code Architecture

### Layered Architecture

```
┌─────────────────────────────────────────────┐
│  GUI Layer (chipcompiler/gui/)               │
│  ├─ Tauri (Rust backend)                    │
│  ├─ Vue 3 + TypeScript (frontend)           │
│  ├─ PixiJS (WebGL/WebGPU rendering)         │
│  └─ PrimeVue + Tailwind CSS (UI)            │
├─────────────────────────────────────────────┤
│  Services Layer (chipcompiler/services/)     │
│  ├─ FastAPI REST API                        │
│  ├─ Workspace management endpoints          │
│  └─ CORS-enabled for GUI/external access    │
├─────────────────────────────────────────────┤
│  RTL2GDS Layer (chipcompiler/rtl2gds/)       │
│  └─ Flow builder for complete RTL-to-GDS    │
├─────────────────────────────────────────────┤
│  Engine Layer (chipcompiler/engine/)         │
│  ├─ EngineFlow - Flow orchestration         │
│  └─ EngineDB - Database engine lifecycle    │
├─────────────────────────────────────────────┤
│  Tools Layer (chipcompiler/tools/)           │
│  ├─ yosys/ - RTL synthesis                  │
│  ├─ ecc/ - Place & route (ECC-Tools)        │
│  ├─ iEDA/ - Legacy directory (empty)        │
│  ├─ klayout/ - Layout viewer/editor         │
│  ├─ openroad/ - Place & route (stub)        │
│  └─ magic/ - Layout tool (stub)             │
├─────────────────────────────────────────────┤
│  Data Layer (chipcompiler/data/)             │
│  ├─ Workspace - Top-level design container  │
│  ├─ WorkspaceStep - Per-step workspace      │
│  ├─ Parameters - Design parameters          │
│  └─ PDK - Process design kit config         │
├─────────────────────────────────────────────┤
│  Utility Layer (chipcompiler/utility/)       │
│  ├─ Logging, JSON I/O, file operations      │
└─────────────────────────────────────────────┘
```

### Data Layer (chipcompiler/data/)

**Core Entities:**
- **Workspace** - Top-level container with design files, PDK, parameters, and flow state
- **WorkspaceStep** - Per-flow-step workspace managing inputs, outputs, configs, logs, reports, scripts
- **Parameters** - Design specifications (die size, clock frequency, buffer/filler/tie cells)
- **PDK** - Technology library paths (LEF, liberty, timing, etc.)
- **StepEnum** - Flow step types (SYNTHESIS, NETLIST_OPT, PLACEMENT, CTS, TIMING_OPT_DRV, TIMING_OPT_HOLD, LEGALIZATION, ROUTING, FILLER)
- **StateEnum** - Step states (Unstart, Ongoing, Success, Incomplete, Invalid, Ignored, Pending)

**Key Pattern:** Each workspace contains a JSON flow definition (workspace.flow.json) that persists flow state and step information. This enables reproducibility and recovery.

### Engine Layer (chipcompiler/engine/)

**EngineFlow (flow.py):**
- Loads/saves flow configuration from workspace JSON
- Manages workflow step sequences via `build_default_steps()` or custom steps via `add_step()`
- Creates per-step workspaces via `create_step_workspaces()` - chains input/output between steps
- Executes flow via `run_steps()` - each step runs in a subprocess for isolation
- Tracks step state (check_state, set_state, clear_states)
- Initializes database engine when needed via `init_db_engine()`

**Key Method:** `flow.run_steps()` - iterates workspace_steps, skips already-successful steps, runs remaining steps via subprocess, updates state and runtime.

**EngineDB (db.py):**
- Wraps ECC-Tools C++ engine lifecycle for post-flow analysis
- Initialized with a specific WorkspaceStep (typically the last successful step)
- Enables circuit analysis and optimization via ECC-Tools Python bindings

### Tools Layer (chipcompiler/tools/)

**Standard EDA Tool Interface:**
Each tool module (yosys, ecc, klayout, openroad, magic) exports:
```python
def is_eda_exist() -> bool  # Check tool availability
def build_step() -> WorkspaceStep  # Create step workspace structure
def build_step_space() -> None  # Initialize directory tree
def build_step_config() -> None  # Generate tool-specific JSON config
def run_step() -> StateEnum  # Execute tool via subprocess
```

**Tool Module Structure:**
- `builder.py` - Workspace creation and config building
- `runner.py` - Tool execution (subprocess with environment variables, timeouts)
- `utility.py` - Tool-specific helper functions
- `configs/` - JSON configuration templates
- `scripts/` - Tool scripts (TCL, Python, shell)
- `bin/` - Tool binaries (ecc only)

**Yosys Integration:**
- Converts RTL (Verilog) to gate-level netlist
- Generates synthesis reports and logs
- Configuration in `chipcompiler/tools/yosys/configs/`

**ECC-Tools Integration:**
- Backend physical design tool provided via [ECC-Tools](https://github.com/openecos-projects/ecc-tools)
- Tool name is **"ecc"** in flow configurations (e.g., `add_step(step=StepEnum.PLACEMENT, tool="ecc")`)
- Wraps ECC-Tools engine internally (located in chipcompiler/thirdparty/ecc-tools)
- Performs netlist optimization, placement, CTS, timing optimization, legalization, routing, filler insertion
- Reads DEF/Verilog inputs, PDK LEF/liberty files, timing constraints (SDC)
- Generates DEF/Verilog outputs for next step
- Python bindings available for post-flow analysis

**Naming Clarification:**
- **ECC-Tools** = The physical design backend tool suite (formerly known as iEDA project, now renamed to ECC-Tools)
- **ecc** = Tool identifier in Python code (e.g., `tool="ecc"`)
- **chipcompiler/thirdparty/ecc-tools** = ECC-Tools project source code (C++ engine)
- **chipcompiler/tools/ecc/** = Python wrapper and integration layer for ECC-Tools
- **chipcompiler/tools/iEDA/** = Legacy directory (empty, kept for backward compatibility)

**KLayout Integration:**
- Layout visualization and editing
- GDS/OASIS file handling
- DRC visualization

### Services Layer (chipcompiler/services/)

FastAPI-based REST API for programmatic access:

- **main.py** - FastAPI app with CORS middleware for GUI access
- **routers/** - API endpoint definitions (workspace management)
- **schemas/** - Pydantic models for request/response validation
- **services/** - Business logic implementations
- **run_server.py** - Uvicorn server entry point

The API server can be spawned by the Tauri GUI at application startup.

### GUI Layer (chipcompiler/gui/)

Desktop application built with Tauri + Vue 3:

- **src/** - Vue 3 frontend with TypeScript
  - `applications/editor/` - PixiJS-based layout editor with ruler plugin
  - `components/` - UI components (panels, toolbars, chat)
  - `composables/` - Vue composition functions (workspace, EDA, menu events)
  - `stores/` - Pinia state management
  - `views/` - Page components (Welcome, Editor, Configure)
- **src-tauri/** - Rust backend for native functionality
- **public/** - Static assets (icons, thumbnails)

Key features: high-performance WebGL rendering, project management, AI-assisted design interface.

### RTL2GDS Layer (chipcompiler/rtl2gds/)

Provides pre-configured flow templates:

- **builder.py** - `build_rtl2gds_flow()` - Returns complete step sequence (SYNTHESIS → FLOORPLAN → NETLIST_OPT → PLACEMENT → CTS → LEGALIZATION → ROUTING → DRC → FILLER)

This simplifies creating full RTL-to-GDS flows without manually defining each step.

### Benchmark Module (benchmark/)

Provides batch testing infrastructure and design parameter management:

- **benchmark.py** - Batch execution functions:
  - `run_benchmark()` - Runs synthesis/P&R on multiple designs from JSON config
  - `benchmark_statis()` - Collects statistics from batch runs
  - `benchmark_metrics()` - Generates metrics reports

- **parameters.py** - Factory for design parameters:
  - `get_parameters(pdk_name, design)` - Returns Parameters instance for specific PDK/design
  - Loads from JSON files (ics55_parameter.json)
  - Merges design-specific info from benchmark JSON files

- **Benchmark JSON files** (ics55_benchmark.json, ics55_tapeout.json):
  - Define multiple designs with filelist paths, top modules, clock names, frequencies
  - Used for regression testing and batch synthesis flows

**Usage Pattern:**
```python
from benchmark import get_parameters
parameters = get_parameters("ics55", "gcd")  # Returns pre-configured Parameters
```

### Typical Flow Execution Path

```
1. Create Workspace
   └─ Define PDK, parameters, origin RTL/DEF

2. Initialize EngineFlow
   ├─ Load workspace.flow.json (or build_default_steps)
   ├─ create_step_workspaces() - chains input/output between steps
   └─ workspace_steps = [synthesis_step, netlist_opt_step, place_step, ...]

3. Run Flow via flow.run_steps()
   ├─ For each workspace_step:
   │  ├─ If state == Success, skip
   │  └─ Else run_step(workspace_step)
   │     ├─ Set state = Ongoing
   │     ├─ Execute tool in subprocess via run_step()
   │     │  ├─ Load tool module dynamically
   │     │  ├─ Run build_step_config (generates tool JSON config)
   │     │  └─ Run tool executable with env vars
   │     ├─ Update state = Success (or Incomplete on failure)
   │     └─ Record runtime

4. Initialize DB Engine (Optional)
   └─ Load ECC-Tools engine with last/first-unsuccessful step workspace

5. Analysis (Optional)
   └─ Use ECC-Tools Python bindings for circuit analysis and optimization
```

### Data Flow Between Steps

- **Input chaining:** First step uses `workspace.design.origin_verilog/origin_def`. Subsequent steps use previous step's output.
- **File locations:** Each step's input/output defined in `WorkspaceStep` with consistent directory structure (input/, output/, config/, logs/, scripts/, reports/, data/, features/, analysis/).
- **State persistence:** Flow state saved to `workspace.flow.json` after each step - enables resumption and inspection.

## Key Design Patterns

1. **Plugin Architecture** - EDA tools loaded dynamically via `load_eda_module()`, enforcing a contract of required functions.
2. **Workspace Isolation** - Each step gets isolated directory tree for inputs, outputs, configs, logs, reports, scripts.
3. **State Machine** - Steps progress through defined states (Unstart → Ongoing → Success/Incomplete).
4. **Configuration as Data** - Flow definitions and tool configs stored as JSON, enabling reproducibility.
5. **Process-based Execution** - Steps run in subprocess (via multiprocessing.Process) for isolation and timeout handling.
6. **Persistent Flow** - Flow state persists in JSON, allowing recovery and inspection via workspace.flow.json.

## Important Implementation Notes

- **Subprocess Execution:** Steps are isolated via Python multiprocessing.Process. Return state is currently simplified but should capture tool exit codes properly.
- **File Chaining:** Input/output file paths must match expectations (DEF/Verilog filenames) for next step to find them.
- **PDK Paths:** PDK definitions must provide valid paths to LEF, liberty, timing (SDC), and SPEF files - verified at workspace creation.
- **Tool Availability:** `is_eda_exist()` checks tool binary presence before execution - ensures tool is installed via Nix or system PATH.
- **Logging:** Each step generates logs in workspace_step.logs/ - useful for debugging tool failures.
- **Third-party Dependencies:** ECC-Tools engine in chipcompiler/thirdparty/ecc-tools, icsprout55 PDK in chipcompiler/thirdparty/icsprout55-pdk (submodules).
- **GUI-API Communication:** GUI frontend communicates with Python backend via REST API (port 8765). CORS is configured for Tauri dev server (1420) and Vite dev server (5173).
- **Package Management:** Uses `uv` for fast dependency resolution and environment management. Dependencies defined in pyproject.toml.
- **Filelist Support:** The project supports Verilog filelist format (`.f` files) for specifying multiple RTL sources. See [docs/examples/gcd/ics55flow_with_filelist.py](docs/examples/gcd/ics55flow_with_filelist.py) for usage.

## Testing Strategy

Tests use **functional integration testing**:
- Create workspace with real design files (GCD design)
- Define complete flow via EngineFlow
- Run full pipeline (synthesis or place-and-route)
- Verify outputs and state updates

Key test files:
- **test_tools_ieda.py** - ECC-Tools place-and-route flow tests
- **test_ics55_batch.py** - Batch synthesis tests on ICS55 PDK
- **test_benchmark_inputs.py** - Benchmark design input tests
- **test_filelist.py** - Filelist parsing tests
- **test_service.py** - REST API endpoint tests

Test designs:
- **ics55_gcd** - GCD on ICS55 technology
- **Batch designs** - Multiple designs defined in benchmark/ics55_benchmark.json for regression testing

Extend tests by adding new designs in benchmark/parameters.py and benchmark/ics55_parameter.json.

## Common Development Workflows

**Adding a new EDA tool:**
1. Create `chipcompiler/tools/<tool_name>/` directory
2. Implement builder.py, runner.py with required functions
3. Add tool configs in `configs/` and scripts in `scripts/`
4. Update flow step definitions in EngineFlow.build_default_steps() or add_step()
5. Add test in test/ with new PDK if needed

**Debugging a flow step:**
1. Check `workspace_step.logs/` for tool output
2. Inspect `workspace_step.config/` for generated configs
3. Verify input files in `workspace_step.input/`
4. Run individual step via EngineFlow.run_step() after examining state

**Modifying flow sequence:**
1. Edit EngineFlow.build_default_steps() or use add_step()
2. Call flow.save() to persist changes to workspace.flow.json
3. Run flow.run_steps() - will skip already-successful steps
4. Use clear_states() to reset and re-run

**Working with the GUI:**
1. Start backend API: `chipcompiler --reload` (port 8765)
2. Start frontend in dev mode: `cd chipcompiler/gui && pnpm run tauri:dev`
3. GUI frontend communicates with API via HTTP requests
4. Frontend changes hot-reload automatically in dev mode
5. Backend changes require restart (or use --reload flag)

**Adding API endpoints:**
1. Define schema in `chipcompiler/services/schemas/`
2. Implement business logic in `chipcompiler/services/services/`
3. Create router in `chipcompiler/services/routers/`
4. Register router in `chipcompiler/services/main.py`
5. Test via Swagger UI at `http://localhost:8765/docs`
