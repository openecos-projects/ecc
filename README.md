# ECOS Chip Compiler (ECC)

<div align="center">

**Open-Source Chip Design Automation Solution**

[![ECC](https://img.shields.io/badge/ECC-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc)
[![ECC-Tools](https://img.shields.io/badge/ECCTools-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc-tools)
[![License](https://img.shields.io/badge/License-Apache_2.0-121011?style=for-the-badge&logo=apache&logoColor=white)](LICENSE)

[![Python](https://img.shields.io/badge/Python-121011?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Nix](https://img.shields.io/badge/Nix-121011?style=for-the-badge&logo=nixos&logoColor=white)](https://nixos.org/)
[![Tauri](https://img.shields.io/badge/Tauri-121011?style=for-the-badge&logo=tauri&logoColor=white)](https://tauri.app/)

[![documentation](https://img.shields.io/badge/documentation-121011?style=for-the-badge)](README.md)
[![文档](https://img.shields.io/badge/文档-121011?style=for-the-badge)](README.cn.md)

</div>


## Overview

ECOS Chip Compiler is an **open-source chip design automation solution** that integrates EDA tools (Yosys, [**ECC-Tools**](https://github.com/openecos-projects/ecc-tools), KLayout) to achieve complete RTL-to-GDS design flow. Developed and maintained by the [**ECOS Team**](https://github.com/openecos-projects).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/asset/overview-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/asset/overview-light.png">
  <img alt="ECOS Chip Compiler Overview" src="docs/asset/overview-light.png">
</picture>

**Two ways to use:**
- **Desktop GUI (ECOS Studio)** - Visual design tool for interactive chip design
- **Python API** - Programmatic flow control for automation


## Quick Start

### Desktop Application (Recommended)

**Option 1: AppImage (Linux x86_64)**

Download the latest AppImage from [Releases](https://github.com/openecos-projects/ecc/releases):

```bash
# Download AppImage
# Use the actual AppImage file name on the Releases page.
wget https://github.com/openecos-projects/ecc/releases/latest/download/ECOS-Studio_*.AppImage

# Make executable
chmod +x ./ECOS-Studio_*.AppImage

# Run
./ECOS-Studio_*.AppImage
```

AppImage is a portable format that runs on most Linux distributions without installation. All dependencies are bundled.

**Option 2: Install via Nix**

```bash
# Run directly from GitHub
nix shell github:openecos-projects/ecc#ecos-studio

# Launch GUI
ecc-client
```

Nix build includes all dependencies. Binary cache available for faster builds.

**Supported Platforms:** x86_64 Linux (Ubuntu 24.04+, or other distros)

### Usage

For detailed usage, see **[User Guide](docs/user-guide.md)**.

### Development Environment

For active development or Python API usage, see **[Development Guide](docs/development.md)**.

## Features

- **Complete RTL-to-GDS Flow** - Synthesis, placement, routing, timing optimization
- **Visual Design Interface** - PixiJS-based layout editor with WebGL rendering
- **Open-Source EDA Integration** - Yosys (synthesis), ECC-Tools (P&R), KLayout (viewer)
- **Python API** - Scriptable automation for batch processing
- **REST API** - FastAPI backend for external tool integration
- **Portable Deployment** - AppImage, Nix, or standalone builds

## 🛠️ Integrated Tools

| Tool | Purpose | Status |
|------|---------|--------|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL Synthesis | ✅ |
| [ECC-Tools](https://github.com/openecos-projects/ecc-tools) | Physical Design (P&R) | ✅ |
| [KLayout](https://www.klayout.de/) | Layout Viewer | 🚧 |
| [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) | Alternative Backend | 🚧 |

## Documentation

- [Architecture](docs/architecture.md) - System design and patterns
- [Development Guide](docs/development.md) - Setup and workflows
- [API Guide](docs/api-guide.md) - Python API reference
- [GUI Guide](docs/gui-develop-guide.md) - GUI development
- [Examples](docs/examples/) - Usage examples
- [Documentation Index](docs/index.md) - Complete navigation

## Contributing

Contributions welcome! See [Development Guide](docs/development.md) for setup instructions.

## Acknowledgments

Special thanks to these open-source projects:

- [Yosys](https://github.com/YosysHQ/yosys) - RTL Synthesis
- [ECC-Tools](https://github.com/openecos-projects/ecc-tools) - Physical Design Backend
- [KLayout](https://www.klayout.de/) - Layout Viewer
- [FastAPI](https://fastapi.tiangolo.com/) - Python Web Framework
- [Tauri](https://tauri.app/) - Desktop Application Framework
- [Vue.js](https://vuejs.org/) - Frontend Framework
- [PixiJS](https://pixijs.com/) - 2D Rendering Engine

<div align="center">

**Built by the ECOS Team**

[Report Issues](https://github.com/openecos-projects/ecc/issues) · [Discussions](https://github.com/openecos-projects/ecc/discussions)

</div>
