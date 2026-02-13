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

**Option 1: Nix Development Shell (Recommended)**
```bash
nix develop  # Provides Python 3.11+, uv, Yosys, ECC-Tools, dependencies
```

**Option 2: Manual Setup**
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

For detailed architecture, see [docs/architecture.md](docs/architecture.md).

### Layered Architecture

```
┌─────────────────────────────────────────────┐
│  GUI Layer (gui/)                           │
│  Tauri + Vue 3 + PixiJS                     │
├─────────────────────────────────────────────┤
│  Services Layer (chipcompiler/services/)    │
│  FastAPI REST API                           │
├─────────────────────────────────────────────┤
│  RTL2GDS Layer (chipcompiler/rtl2gds/)      │
│  Flow builder                               │
├─────────────────────────────────────────────┤
│  Engine Layer (chipcompiler/engine/)        │
│  EngineFlow + EngineDB                      │
├─────────────────────────────────────────────┤
│  Tools Layer (chipcompiler/tools/)          │
│  yosys, ecc, klayout, openroad, magic       │
├─────────────────────────────────────────────┤
│  Data Layer (chipcompiler/data/)            │
│  Workspace, WorkspaceStep, Parameters, PDK  │
├─────────────────────────────────────────────┤
│  Utility Layer (chipcompiler/utility/)      │
│  Logging, JSON I/O, file operations         │
└─────────────────────────────────────────────┘
```

### Key Layers

**Data Layer:** Workspace (top-level container), WorkspaceStep (per-step workspace), Parameters (design specs), PDK (tech library paths). Each workspace has `workspace.flow.json` for state persistence.

**Engine Layer:** EngineFlow orchestrates workflow (build_default_steps, add_step, create_step_workspaces, run_steps). EngineDB wraps ECC-Tools for post-flow analysis.

**Tools Layer:** Standard interface (is_eda_exist, build_step, run_step). Yosys (synthesis), ECC-Tools (P&R - tool name "ecc"), KLayout (layout viewer).

**ECC-Tools Note:** Tool identifier is "ecc" in code. Source in chipcompiler/thirdparty/ecc-tools, wrapper in chipcompiler/tools/ecc/.

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

For detailed workflows, see [docs/development.md](docs/development.md).

**Quick reference:**
- **Add EDA tool:** Create tool module with standard interface (is_eda_exist, build_step, run_step), add configs/scripts, integrate into flow
- **Debug step:** Check workspace_step.logs/, config/, input/; run individual step via EngineFlow.run_step()
- **Modify flow:** Edit build_default_steps() or use add_step(), call flow.save(), run flow.run_steps()
- **GUI dev:** Start backend (`chipcompiler --reload`), start frontend (`cd gui && pnpm run tauri:dev`)
- **Add API endpoint:** Define schema, implement logic, create router, register in main.py, test via Swagger UI
