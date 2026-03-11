# ECOS Chip Compiler (ECC)

<div align="center">

**Open-Source Chip Design Automation Solution**

[![ECC](https://img.shields.io/badge/ECC-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc)
[![ECC-Tools](https://img.shields.io/badge/ECCTools-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc-tools)
[![License](https://img.shields.io/badge/License-Apache_2.0-121011?style=for-the-badge&logo=apache&logoColor=white)](LICENSE)

[![Python](https://img.shields.io/badge/Python-121011?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Nix](https://img.shields.io/badge/Nix-121011?style=for-the-badge&logo=nixos&logoColor=white)](https://nixos.org/)

[![documentation](https://img.shields.io/badge/documentation-121011?style=for-the-badge)](README.md)
[![文档](https://img.shields.io/badge/文档-121011?style=for-the-badge)](README.cn.md)

</div>


## Overview

ECOS Chip Compiler is an **open-source chip design automation solution** that integrates EDA tools (Yosys, [**ECC-Tools**](https://github.com/openecos-projects/ecc-tools), KLayout) to achieve complete RTL-to-GDS design flow. Developed and maintained by the [**ECOS Team**](https://github.com/openecos-projects).

The GUI (ECOS Studio) has been moved to the [ecos-studio](https://github.com/0xharry/ecos-studio) repo.

**How to use:**
- **CLI (`cli`)** - Command-line flow execution
- **Python API** - Use `chipcompiler` as a library


## Quick Start

### CLI Flow Runner

Use `nix run .#cli -- ...` to create a workspace and run the full RTL2GDS flow directly.

```bash
nix run .#cli -- --workspace ./ws \
                --rtl ./rtl/top.v \
                --design top \
                --top top \
                --clock clk \
                --pdk-root /path/to/ics55
nix run .#cli -- --workspace ./ws \
                --rtl ./rtl/filelist.f \
                --design top \
                --top top \
                --clock clk \
                --pdk-root /path/to/ics55 \
                --freq 200
```

## Features

- **Complete RTL-to-GDS Flow** - Synthesis, placement, routing, timing optimization
- **Open-Source EDA Integration** - Yosys (synthesis), ECC-Tools (P&R), KLayout (viewer)
- **CLI Automation** - Scriptable flow execution from command line
- **Portable Deployment** - Nix or standalone builds

## 🛠️ Integrated Tools

| Tool | Purpose | Status |
|------|---------|--------|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL Synthesis | ✅ |
| [ECC-Tools](https://github.com/openecos-projects/ecc-tools) | Physical Design (P&R) | ✅ |
| [KLayout](https://www.klayout.de/) | Layout Viewer | 🚧 |

## Documentation

- [Documentation Index](docs/index.md) - Complete navigation
- [Architecture](docs/architecture.md) - System design and patterns
- [Development Guide](docs/development.md) - Setup and workflows
- [Examples](docs/examples/) - Usage examples

## Contributing

Contributions welcome! See [Development Guide](docs/development.md) for setup instructions.

## Acknowledgments

Special thanks to these open-source projects:

- [Yosys](https://github.com/YosysHQ/yosys) - RTL Synthesis
- [ECC-Tools](https://github.com/openecos-projects/ecc-tools) - Physical Design Backend
- [KLayout](https://www.klayout.de/) - Layout Viewer
- [nixpkgs](https://github.com/NixOS/nixpkgs) - A collection of Nix packages

<div align="center">

**Built by the ECOS Team**

[Report Issues](https://github.com/openecos-projects/ecc/issues) · [Discussions](https://github.com/openecos-projects/ecc/discussions)

</div>
