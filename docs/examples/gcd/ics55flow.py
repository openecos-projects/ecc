from benchmark import get_parameters
from chipcompiler.data import StateEnum, StepEnum, create_workspace, get_pdk
from chipcompiler.engine import EngineFlow

# Setup paths
workspace_dir = "./gcd_workspace"
input_verilog = "./docs/examples/gcd/gcd.v"

# Load PDK and design parameters
# ICS55 PDK will be automatically downloaded after git submodule update --init --recursive
pdk = get_pdk("ics55")
parameters = get_parameters("ics55", "gcd")

# Create workspace
# The workspace will be created from scratch, the structure is as follows:
# gcd_workspace/
# ├── flow.json       # Flow state file
# ├── parameters.json # Design parameters file
# ├── CTS_ecc         # CTS step workspace
# │   ├── analysis    # Analysis files extract from metrics
# │   ├── config      # Configuration files
# │   ├── data        # Data files that generated during the step
# │   ├── feature     # Metrics feature files
# │   ├── log         # Each step log files
# │   ├── output      # Output artifacts
# │   ├── report      # Reports generated during the step
# │   └── script      # Step scripts
# ├── drc_ecc
# │   ...             # Similar structure as above
# │   └── script
# ├── filler_ecc
# │   ...
# │   └── script
# ├── fixFanout_ecc
# │   ...
# │   └── script
# ├── Floorplan_ecc
# │   ...
# │   └── script
# ├── legalization_ecc
# │   ...
# │   └── script
# ├── log
# │   └── gcd.xxxx-01-22_16-05-25 # Global log file
# ├── origin
# │   ├── gcd.sdc
# │   ├── filelist.f
# │   └── rtl
# ├── place_ecc
# │   ...
# │   └── script
# ├── route_ecc
# │   ...
# │   └── script
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
    engine_flow.add_step(step=StepEnum.SYNTHESIS, tool="Yosys", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.FLOORPLAN, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.NETLIST_OPT, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.PLACEMENT, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.CTS, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.ROUTING, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.FILLER, tool="ecc", state=StateEnum.Unstart)

# Create step workspaces and run
engine_flow.create_step_workspaces()
engine_flow.run_steps()
