# ECOS Chip Compiler (ECC)

<div align="center">

**Open-Source Chip Design Automation Solution**

[![Python](https://img.shields.io/badge/Python-121011?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Nix](https://img.shields.io/badge/Nix-121011?style=for-the-badge&logo=nixos&logoColor=white)](https://nixos.org/)
[![ECC](https://img.shields.io/badge/ECC-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc)
[![ECC-Tools](https://img.shields.io/badge/ECCTools-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc-tools)
[![Tauri](https://img.shields.io/badge/Tauri-121011?style=for-the-badge&logo=tauri&logoColor=white)](https://tauri.app/)

<!-- [![License](https://img.shields.io/badge/License-Apache_2.0-121011?style=for-the-badge&logo=apache&logoColor=white)](LICENSE) -->
[![documentation](https://img.shields.io/badge/documentation-121011?style=for-the-badge)](README.md)
[![文档](https://img.shields.io/badge/文档-121011?style=for-the-badge)](README.cn.md)

</div>


## Overview

ECOS Chip Compiler is a Python-based **Chip design automation solution** that integrates Open Source EDA tools (Yosys, [**ECC-Tools**](https://github.com/openecos-projects/ecc-tools), Magic, KLayout) and several custom components to achieve complete RTL-to-GDS design flow. The solution is currently developed and maintained by the [**ECOS Team**](https://github.com/openecos-projects).

Please refer the **[Quick Start Guide](#-quick-start)** section to get started quickly.

**Two ways to use**:
- **Python API** - Programmatic flow control (You can refer [examples](#usage-examples) here)
- **Desktop GUI** - Visual design tool (**Still under development, coming soon**)

For detailed architecture, see **[Architecture Documentation](docs/architecture.md)**.

## Quick Start

### Install All Dependencies

Support platforms: x86_64 Linux (**Ubuntu 24.04+**, or other distros with **Nix** installed)

**Option 1: Nix (Recommended)**

Install Nix package manager if you haven't (Nix is not NixOS!): https://nixos.org/download

```bash
# Enter development environment
nix develop
```

**Option 2: Manual Installation**

```bash
# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Build project dependencies
./build.sh
source .venv/bin/activate
```

For more installation options, see **[Development Guide](docs/development.md)**.

## Usage Examples

### Python API

Here is a example flow with [icsprout55-pdk](https://github.com/openecos-projects/icsprout55-pdk) to implement GCD design:

```python
from chipcompiler.data import create_workspace, get_pdk, StepEnum, StateEnum
from chipcompiler.engine import EngineFlow
from benchmark import get_parameters

# Setup paths
workspace_dir = "./gcd_workspace"
input_verilog = "./docs/examples/gcd/gcd.v"

# Load PDK and design parameters
pdk = get_pdk("ics55")
parameters = get_parameters("ics55", "gcd")

# Create workspace
workspace = create_workspace(
    directory=workspace_dir,
    origin_def="",
    origin_verilog=input_verilog,
    pdk=pdk,
    parameters=parameters
)

# Setup flow engine and add steps
engine_flow = EngineFlow(workspace=workspace)
if not engine_flow.has_init():
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
```

Full reference: **[docs/examples/gcd](docs/examples/gcd/README.md)**

For complete API documentation, see **[API Guide](docs/api-guide.md)**.

### Desktop GUI

> [!WARNING]
> Desktop GUI is still under development. We will release the first version soon.
>

## More Documentation

See [documentation index](docs/index.md) for complete documentation navigation.

## 🛠️ Integrated Tools

| Tool | Purpose | Status |
|------|---------|--------|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL Synthesis | ✅ |
| [ECC-Tools](https://github.com/openecos-projects/ecc-tools) | Backend Flow | ✅ |
| [KLayout](https://www.klayout.de/) | Layout Viewer | 🚧 |
| [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) | Backend Flow | 🚧 |

## Contributing

See [Development Guide](docs/development.md) for details.

<!-- ## 📄 License

This project is licensed under [Apache License 2.0](LICENSE). -->

## Acknowledgments

Special thanks to these open-source projects:

- [Yosys](https://github.com/YosysHQ/yosys) - RTL Synthesis
- [ECC-Tools](https://github.com/openecos-projects/ecc-tools) - Open-Source EDA Tools (Physical Design)
- [KLayout](https://www.klayout.de/) - Layout Viewer
- [FastAPI](https://fastapi.tiangolo.com/) - Python Web Framework
- [Tauri](https://tauri.app/) - Desktop Application Framework
- [Vue.js](https://vuejs.org/) - Frontend Framework
- [PixiJS](https://pixijs.com/) - 2D Rendering Engine



<div align="center">

**Built with ❤️ by the ECOS Team**

[Report Issues](https://github.com/openecos-projects/ecc/issues) · [Discussions](https://github.com/openecos-projects/ecc/discussions)

</div>
