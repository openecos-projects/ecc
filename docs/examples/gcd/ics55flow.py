from chipcompiler.data import (
    StateEnum,
    StepEnum,
    create_workspace,
    get_design_parameters,
    get_pdk,
)
from chipcompiler.engine import EngineFlow

# Setup paths
workspace_dir = "./gcd_workspace"
input_verilog = "./docs/examples/gcd/gcd.v"

# Load PDK and design parameters
# ICS55 PDK will be automatically downloaded after git submodule update --init --recursive
pdk = get_pdk("ics55")
parameters = get_design_parameters("ics55", "gcd")

# Create workspace
# This single-source call copies the RTL basename into origin/; it does not
# create an implicit origin/rtl/ directory. The workspace will be created from
# scratch with the following structure:
# gcd_workspace/
# ├── home/
# │   ├── flow.json          # Flow state file
# │   ├── params.toml        # Workspace configuration (parameters, flow target)
# │   └── checklist.json     # Checklist state
# ├── CTS_ecc                # CTS step workspace
# │   ├── analysis    # Analysis files extract from metrics
# │   ├── data        # Data files that generated during the step
# │   ├── feature     # Metrics feature files
# │   ├── log         # Each step log files
# │   ├── output      # Output artifacts
# │   ├── report      # Reports generated during the step
# │   └── script      # Step scripts
# ├── config/                # Workspace-level tool configuration files
# ├── filler_ecc
# │   ...
# │   └── script
# ├── legalization_dreamplace
# │   ...
# │   └── script
# ├── log
# │   └── gcd.xxxx-01-22_16-05-25 # Global log file
# ├── macroPlacement_dreamplace
# │   ...
# │   └── script
# ├── origin
# │   ├── gcd.sdc            # Constraint file
# │   └── gcd.v              # RTL source file
# ├── place_dreamplace
# │   ...
# │   └── script
# ├── postFloorplan_ecc
# │   ...
# │   └── script
# ├── preFloorplan_ecc
# │   ...
# │   └── script
# ├── route_ecc
# │   ...
# │   └── script
# └── Synthesis_yosys
#     ...
#     └── script
workspace = create_workspace(
    directory=workspace_dir,
    origin_def="",
    origin_verilog=input_verilog,
    pdk=pdk,
    parameters=parameters,
)
# Use load_workspace to resume from existing workspace
# workspace = load_workspace(directory=workspace_dir)

# Setup flow engine and add steps
engine_flow = EngineFlow(workspace=workspace)
if not engine_flow.has_init():
    # Use `add_step` to add steps to the flow
    engine_flow.add_step(step=StepEnum.SYNTHESIS, tool="yosys", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.PRE_FLOORPLAN, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.MACRO_PLACEMENT, tool="dreamplace", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.POST_FLOORPLAN, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.PLACEMENT, tool="dreamplace", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.CTS, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="dreamplace", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.ROUTING, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.FILLER, tool="ecc", state=StateEnum.Unstart)

# Create step workspaces and run
engine_flow.create_step_workspaces()
engine_flow.run_steps()
