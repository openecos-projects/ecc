# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ChipCompiler is an ECOS chip design automation solution that orchestrates EDA tools (Yosys, ECC-Tools, OpenROAD, Magic, KLayout) to perform RTL-to-GDS flows. The project includes:

1. **Desktop GUI (ecc-client)** - Tauri + Vue 3 application for visual design and layout editing
2. **Core Engine** - Python-based flow orchestration and EDA tool integration
3. **REST API** - FastAPI backend for programmatic access

Architecture: modular, plugin-based design with clear separation between data, engine, tools, services, and UI layers.

## Development Setup and Commands

### Installation

**Option 1: Nix (Recommended)**
```bash
nix shell github:openecos-projects/ecc#chipcompiler  # Run directly
nix profile install github:openecos-projects/ecc#chipcompiler  # Install to profile
```
Binary cache available at `serve.eminrepo.cc`. Available packages: `chipcompiler`, `ecc-tools`, `ecos-studio`.

**Option 2: Development Shell**
```bash
nix develop  # Provides Python 3.11+, uv, Yosys, ECC-Tools, dependencies
```

**Option 3: Manual Setup**
```bash
bash ./build.sh  # Creates .venv, builds ECC-Tools, downloads OSS CAD Suite
source .venv/bin/activate
ENABLE_OSS_CAD_SUITE=false ./build.sh  # Skip OSS CAD Suite if yosys installed
```

**First-time setup:**
```bash
git submodule update --init --recursive  # Required for ECC-Tools and icsprout55 PDK
```

### Running Tests

```bash
pytest test/                                    # All tests
pytest test/test_tools_yosys.py                 # Specific test file
pytest test/ -v                                 # Verbose output
pytest test/ --cov=chipcompiler --cov-report=term-missing  # Coverage
```

Key test files: `test_tools_ecc.py` (P&R flow), `test_ics55_batch.py` (batch synthesis), `test_benchmark_inputs.py`, `test_filelist.py`, `test_service.py` (API).

### Code Quality

```bash
ruff format chipcompiler/ test/    # Format (recommended)
ruff check chipcompiler/ test/     # Lint
pyright chipcompiler/              # Type check (primary)
mypy chipcompiler/                 # Type check (alternative)
```

### Building ECC-Tools

```bash
mkdir -p build && cd build
cmake ..
make
```
Builds ECC-Tools C++ bindings. After building, run `./scripts/autopatch-ecc-py.sh` to bundle runtime dependencies with correct RPATH (`$ORIGIN:$ORIGIN/lib`) for portable deployment.

### Running the API Server

```bash
chipcompiler                        # Start server (default port 8765)
chipcompiler --host 127.0.0.1 --port 8000  # Custom host/port
chipcompiler --reload               # Development mode with auto-reload
```
API docs at `http://localhost:8765/docs` (Swagger UI).

### Running the GUI Application

```bash
cd gui
pnpm install                # Install dependencies
pnpm run tauri:dev          # Development mode (hot reload)
pnpm run dev                # Frontend only in browser
pnpm run tauri:build        # Production build (.dmg, .exe, .deb)
```
Prerequisites: Node.js LTS, pnpm, Rust toolchain, Tauri dependencies (see [gui/README.md](gui/README.md)).

## Code Architecture

### Layered Architecture

```
┌─────────────────────────────────────────────┐
│  GUI Layer (gui/)               │
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

Core entities:
- **Workspace** - Top-level container with design files, PDK, parameters, flow state
- **WorkspaceStep** - Per-step workspace managing inputs, outputs, configs, logs, reports, scripts
- **Parameters** - Design specs (die size, clock frequency, buffer/filler/tie cells)
- **PDK** - Technology library paths (LEF, liberty, timing, etc.)
- **StepEnum** - Flow steps (SYNTHESIS, NETLIST_OPT, PLACEMENT, CTS, TIMING_OPT_DRV, TIMING_OPT_HOLD, LEGALIZATION, ROUTING, FILLER)
- **StateEnum** - Step states (Unstart, Ongoing, Success, Incomplete, Invalid, Ignored, Pending)

Each workspace contains `workspace.flow.json` persisting flow state for reproducibility and recovery.

### Engine Layer (chipcompiler/engine/)

**EngineFlow (flow.py):**
- Loads/saves flow config from workspace JSON
- Manages workflow via `build_default_steps()` or custom `add_step()`
- Creates per-step workspaces via `create_step_workspaces()` - chains input/output between steps
- Executes flow via `run_steps()` - each step runs in subprocess for isolation
- Tracks step state (check_state, set_state, clear_states)
- Initializes database engine via `init_db_engine()`

Key method: `flow.run_steps()` iterates workspace_steps, skips successful steps, runs remaining via subprocess, updates state and runtime.

**EngineDB (db.py):**
Wraps ECC-Tools C++ engine lifecycle for post-flow analysis. Initialized with a WorkspaceStep (typically last successful step).

### Tools Layer (chipcompiler/tools/)

**Standard EDA Tool Interface:**
Each tool module (yosys, ecc, klayout, openroad, magic) exports:
```python
def is_eda_exist() -> bool         # Check tool availability
def build_step() -> WorkspaceStep  # Create step workspace
def build_step_space() -> None     # Initialize directory tree
def build_step_config() -> None    # Generate tool config
def run_step() -> StateEnum        # Execute tool via subprocess
```

**Tool Module Structure:** `builder.py`, `runner.py`, `utility.py`, `configs/`, `scripts/`, `bin/` (ecc only).

**Yosys:** Converts RTL to gate-level netlist. Config in `chipcompiler/tools/yosys/configs/`.

**ECC-Tools Integration:**
- Backend physical design tool from [ECC-Tools](https://github.com/openecos-projects/ecc-tools)
- Tool identifier: **"ecc"** (e.g., `add_step(step=StepEnum.PLACEMENT, tool="ecc")`)
- Source: `chipcompiler/thirdparty/ecc-tools` (C++ engine)
- Wrapper: `chipcompiler/tools/ecc/` (Python integration layer)
- Performs: netlist optimization, placement, CTS, timing optimization, legalization, routing, filler insertion
- I/O: Reads DEF/Verilog, PDK LEF/liberty, SDC; generates DEF/Verilog for next step
- Python bindings available for post-flow analysis

**KLayout:** Layout visualization, GDS/OASIS handling, DRC visualization.

### Services Layer (chipcompiler/services/)

FastAPI REST API: `main.py` (app + CORS), `routers/` (endpoints), `schemas/` (Pydantic models), `services/` (business logic), `run_server.py` (Uvicorn entry). API server spawnable by Tauri GUI at startup.

### GUI Layer (gui/)

Tauri + Vue 3 desktop app:
- `src/` - Vue 3 frontend: `applications/editor/` (PixiJS layout editor), `components/` (UI), `composables/` (workspace/EDA/menu), `stores/` (Pinia state), `views/` (pages)
- `src-tauri/` - Rust backend
- `public/` - Static assets

Features: WebGL rendering, project management, AI-assisted design.

### RTL2GDS Layer (chipcompiler/rtl2gds/)

`builder.py` - `build_rtl2gds_flow()` returns complete step sequence: SYNTHESIS → FLOORPLAN → NETLIST_OPT → PLACEMENT → CTS → LEGALIZATION → ROUTING → DRC → FILLER.

### Benchmark Module (benchmark/)

Batch testing infrastructure:
- `benchmark.py` - `run_benchmark()`, `benchmark_statis()`, `benchmark_metrics()`
- `parameters.py` - `get_parameters(pdk_name, design)` returns Parameters from JSON files
- Benchmark JSONs (ics55_benchmark.json, ics55_tapeout.json) define designs for regression testing

Usage: `from benchmark import get_parameters; parameters = get_parameters("ics55", "gcd")`

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
- **File locations:** Each step has consistent directory structure: input/, output/, config/, logs/, scripts/, reports/, data/, features/, analysis/.
- **State persistence:** Flow state saved to `workspace.flow.json` after each step - enables resumption and inspection.

## Key Design Patterns

1. **Plugin Architecture** - EDA tools loaded dynamically via `load_eda_module()`, enforcing a contract of required functions.
2. **Workspace Isolation** - Each step gets isolated directory tree for inputs, outputs, configs, logs, reports, scripts.
3. **State Machine** - Steps progress through defined states (Unstart → Ongoing → Success/Incomplete).
4. **Configuration as Data** - Flow definitions and tool configs stored as JSON, enabling reproducibility.
5. **Process-based Execution** - Steps run in subprocess (via multiprocessing.Process) for isolation and timeout handling.
6. **Persistent Flow** - Flow state persists in JSON, allowing recovery and inspection via workspace.flow.json.

## Important Implementation Notes

- **Subprocess Execution:** Steps isolated via multiprocessing.Process for timeout handling
- **File Chaining:** Input/output paths must match expectations (DEF/Verilog filenames) for next step
- **PDK Paths:** PDK definitions verified at workspace creation (LEF, liberty, timing, SPEF)
- **Tool Availability:** `is_eda_exist()` checks tool binary before execution
- **Logging:** Each step generates logs in workspace_step.logs/ for debugging
- **Third-party Dependencies:** ECC-Tools in chipcompiler/thirdparty/ecc-tools, icsprout55 PDK in chipcompiler/thirdparty/icsprout55-pdk (submodules)
- **GUI-API Communication:** GUI communicates with Python backend via REST API (port 8765). CORS configured for Tauri (1420) and Vite (5173) dev servers
- **Package Management:** Uses `uv` for fast dependency resolution. Dependencies in pyproject.toml
- **Filelist Support:** Supports Verilog filelist format (`.f` files). See [docs/examples/gcd/ics55flow_with_filelist.py](docs/examples/gcd/ics55flow_with_filelist.py)
- **ECC Runtime Dependencies:** ECC-Tools Python bindings require bundled `.so` libraries. `autopatch-ecc-py.sh` collects, patches, and bundles dependencies with RPATH `$ORIGIN:$ORIGIN/lib` for portable deployment

## Testing Strategy

Functional integration testing approach:
- Create workspace with real design files (GCD design)
- Define complete flow via EngineFlow
- Run full pipeline (synthesis or P&R)
- Verify outputs and state updates

Test designs: ics55_gcd (GCD on ICS55), batch designs in benchmark/ics55_benchmark.json for regression.

Extend tests by adding designs in benchmark/parameters.py and benchmark/ics55_parameter.json.

## Common Development Workflows

**Adding a new EDA tool:**
1. Create `chipcompiler/tools/<tool_name>/` with builder.py, runner.py, utility.py
2. Implement required functions: `is_eda_exist()`, `build_step()`, `build_step_space()`, `build_step_config()`, `run_step()`
3. Add configs in `configs/` and scripts in `scripts/`
4. Update EngineFlow.build_default_steps() or use add_step()
5. Add test in test/

**Debugging a flow step:**
1. Check `workspace_step.logs/` for tool output
2. Inspect `workspace_step.config/` for generated configs
3. Verify input files in `workspace_step.input/`
4. Run individual step via EngineFlow.run_step()

**Modifying flow sequence:**
1. Edit EngineFlow.build_default_steps() or use add_step()
2. Call flow.save() to persist to workspace.flow.json
3. Run flow.run_steps() - skips successful steps
4. Use clear_states() to reset and re-run

**Working with the GUI:**
1. Start backend: `chipcompiler --reload` (port 8765)
2. Start frontend: `cd gui && pnpm run tauri:dev`
3. Frontend changes hot-reload; backend requires restart (or --reload)

**Adding API endpoints:**
1. Define schema in `chipcompiler/services/schemas/`
2. Implement logic in `chipcompiler/services/services/`
3. Create router in `chipcompiler/services/routers/`
4. Register in `chipcompiler/services/main.py`
5. Test via Swagger UI at `http://localhost:8765/docs`
