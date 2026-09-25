"""
GCD example using filelist for RTL synthesis.

This example demonstrates how to use a filelist file to specify RTL sources
instead of a single verilog file. Filelists support:
- Multiple source files
- Include directory directives (+incdir+)
- Comments and empty lines
- Relative and absolute paths
- Quoted paths with spaces

For more information on filelist syntax, see:
docs/specification/filelist-grammar.md
"""

from chipcompiler.data import (
    StateEnum,
    StepEnum,
    create_workspace,
    get_design_parameters,
    get_pdk,
)
from chipcompiler.engine import EngineFlow

# Setup paths
workspace_dir = "./gcd_workspace_with_filelist"
input_filelist = "./docs/examples/gcd/filelist.f"

# Load PDK and design parameters
# ICS55 PDK will be automatically downloaded after git submodule update --init --recursive
pdk = get_pdk("ics55")
parameters = get_design_parameters("ics55", "gcd")

# Create workspace with filelist
# The workspace will be created from scratch, the structure is as follows:
# gcd_workspace_with_filelist/
# ├── home/
# │   ├── flow.json       # Flow state file tracking step states and runtime
# │   ├── params.toml     # Workspace configuration (die size, clock freq, flow target)
# │   └── checklist.json  # Checklist state
# ├── config/             # Workspace-level tool configuration files
# ├── CTS_ecc             # Clock Tree Synthesis step workspace
# │   ├── analysis    # Analysis files extracted from metrics
# │   ├── data        # Data files that generated during the step
# │   ├── feature     # Metrics feature files
# │   ├── log         # Each step log files
# │   ├── output      # Output artifacts (DEF/Verilog for next step)
# │   ├── report      # Reports generated during the step
# │   └── script      # Step scripts (TCL, Python, shell)
# ├── filler_ecc      # Filler cell insertion step
# │   ...
# │   └── script
# ├── legalization_dreamplace # Legalization step
# │   ...
# │   └── script
# ├── log
# │   └── gcd.xxxx-xx-xx_xx-xx-xx # Global log file
# ├── macroPlacement_dreamplace # Macro placement step
# │   ...
# │   └── script
# ├── origin          # Original design files
# │   ├── gcd.sdc     # Timing constraints file
# │   ├── filelist.f  # Verilog filelist (all RTL sources are listed here)
# │   └── gcd.v       # GCD design source (copied from filelist)
# ├── place_dreamplace # Placement step
# │   ...
# │   └── script
# ├── postFloorplan_ecc # Floorplanning step (post)
# │   ...
# │   └── script
# ├── preFloorplan_ecc  # Floorplanning step (pre)
# │   ...
# │   └── script
# ├── route_ecc       # Routing step
# │   ...
# │   └── script
# └── Synthesis_yosys # Logic synthesis step
#     ...
#     └── script
#
# When using a filelist:
# 1. All files referenced in the filelist are copied to workspace/origin/
# 2. Directory structure is preserved
# 3. +incdir+ directories are also copied
# 4. The filelist itself is copied to workspace/origin/
workspace = create_workspace(
    directory=workspace_dir,
    origin_def="",
    origin_verilog="",  # Not needed when using filelist
    pdk=pdk,
    parameters=parameters,
    input_filelist=input_filelist,  # Provide filelist path here
)
# Use load_workspace to resume from existing workspace
# workspace = load_workspace(directory=workspace_dir)

# Verify that filelist was copied
print(f"Filelist path in workspace: {workspace.design.input_filelist}")
print(f"Origin directory: {workspace_dir}/origin")

# Setup flow engine and add steps
# The synthesis step will use the filelist instead of a single verilog file.
# The engine will:
# 1. Load the filelist from workspace/origin/filelist.f
# 2. Parse filelist and collect all RTL sources
# 3. Pass filelist to Yosys for synthesis
engine_flow = EngineFlow(workspace=workspace)
if not engine_flow.has_init():
    # Use `add_step` to add steps to the flow.
    # Each step transitions through states: Unstart → Ongoing → Success (or Incomplete on failure)

    # SYNTHESIS step: RTL to gate-level netlist using Yosys
    # Input: filelist.f with RTL sources
    # Output: Synthesized netlist (Verilog) and reports
    engine_flow.add_step(step=StepEnum.SYNTHESIS, tool="yosys", state=StateEnum.Unstart)

    # PRE_FLOORPLAN step: Define chip die size and core region
    # Input: Synthesized netlist
    # Output: Initial floorplan definition
    engine_flow.add_step(step=StepEnum.PRE_FLOORPLAN, tool="ecc", state=StateEnum.Unstart)

    # MACRO_PLACEMENT step: Place macro cells
    # Input: Initial floorplan
    # Output: Floorplan with placed macros
    engine_flow.add_step(step=StepEnum.MACRO_PLACEMENT, tool="dreamplace", state=StateEnum.Unstart)

    # POST_FLOORPLAN step: Adjust floorplan around placed macros
    # Input: Floorplan with placed macros
    # Output: Final floorplan definition
    engine_flow.add_step(step=StepEnum.POST_FLOORPLAN, tool="ecc", state=StateEnum.Unstart)

    # PLACEMENT step: Place cells on the die
    # Input: Synthesized netlist, floorplan
    # Output: DEF with cell placement
    engine_flow.add_step(step=StepEnum.PLACEMENT, tool="dreamplace", state=StateEnum.Unstart)

    # CTS step: Clock Tree Synthesis - balance clock distribution
    # Input: Placed netlist
    # Output: DEF with clock tree inserted
    engine_flow.add_step(step=StepEnum.CTS, tool="ecc", state=StateEnum.Unstart)

    # LEGALIZATION step: Legalize placement to match manufacturing constraints
    # Input: DEF after CTS
    # Output: Legalized DEF
    engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="dreamplace", state=StateEnum.Unstart)

    # ROUTING step: Route all signal and power nets
    # Input: Legalized DEF
    # Output: Fully routed DEF
    engine_flow.add_step(step=StepEnum.ROUTING, tool="ecc", state=StateEnum.Unstart)

    # FILLER step: Insert filler cells to fill gaps and improve density
    # Input: Routed DEF
    # Output: Final DEF with fillers
    engine_flow.add_step(step=StepEnum.FILLER, tool="ecc", state=StateEnum.Unstart)

# Create step workspaces and run
# create_step_workspaces() creates isolated directories for each step and chains input/output
engine_flow.create_step_workspaces()

# run_steps() executes the flow:
# - Skips already-successful steps (check state from flow.json)
# - Runs remaining steps via subprocess for isolation
# - Updates state and runtime after each step
# - Stops if any step fails (state = Incomplete)
engine_flow.run_steps()

print("\nFlow completed successfully!")
print(f"Check logs and outputs in: {workspace_dir}")
print("\nKey files to inspect:")
print(f"  - Flow state: {workspace_dir}/home/flow.json")
print(f"  - Synthesis output: {workspace_dir}/Synthesis_yosys/output/")
print(f"  - Final DEF: {workspace_dir}/filler_ecc/output/")
print(f"  - Global log: {workspace_dir}/log/")
print(f"  - Per-step logs: {workspace_dir}/<step_name>/log/")
print("\nTo resume or inspect the workspace:")
print("  from chipcompiler.data import load_workspace")
print(f"  workspace = load_workspace('{workspace_dir}')")
print("  engine_flow = EngineFlow(workspace=workspace)")
print("  engine_flow.run_steps()  # Resumes from last successful step")
