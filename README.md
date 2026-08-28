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

ECOS Chip Compiler is an **open-source chip design automation solution** that integrates EDA tools (Yosys, [**ECC-DreamPlace**](https://github.com/openecos-projects/ecc-dreamplace), [**ECC-Tools**](https://github.com/openecos-projects/ecc-tools), KLayout) to achieve complete RTL-to-GDS design flow. Developed and maintained by the [**ECOS Team**](https://github.com/openecos-projects).

The GUI (ECOS Studio) has been moved to the [ecos-studio](https://github.com/0xharry/ecos-studio) repo.

**How to use:**
- **CLI (`ecc`)** - Project-oriented command-line flow execution
- **Python API** - Use `chipcompiler` as a library


## Installation

### Installer (recommended)

Install the `ecc` CLI (Linux x86_64, glibc 2.34+):

```sh
curl -fsSL http://release.openecos.com/installers/ecc/latest/ecc-installer.sh | sh
```

To also install Yosys (OSS CAD Suite) and the ICS55 PDK:

```sh
curl -fsSL http://release.openecos.com/installers/ecc/latest/ecc-installer.sh | sh -s -- --with-toolchain
```

The wrapper is installed to `~/.local/bin` by default. If that directory is not
on `PATH`, add it:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

### Nix

With [Nix](https://nixos.org/) installed, clone the repository **with
submodules** (required — `chipcompiler/thirdparty/` pulls in `ecc-tools` and
`ecc-dreamplace`), then run ECC via the flake:

```bash
git clone --recursive https://github.com/openecos-projects/ecc.git
cd ecc
nix run . -- --help
```

If you already cloned without `--recursive`:

```bash
git submodule update --init --recursive
```

### Build from source

For Python development with `uv`, clone the repository as above (with
`--recursive`), then follow the [Development Guide](docs/development.md) to
set up the workspace.

## Quick Start

The commands below use the installed `ecc`. Without installing, prefix each
command with `nix run . --` (e.g. `nix run . -- init gcd`).

If you installed with `--with-toolchain`, Yosys and the ICS55 PDK are already
configured by the `ecc` wrapper. Otherwise re-run the installer with
`--with-toolchain`. The Nix flake provides Yosys itself; set `pdk.root` if you
are not using the installer toolchain.

Create a project and add your RTL:

```bash
ecc init gcd
cp /path/to/gcd.v gcd/rtl/gcd.v  # example design: docs/examples/gcd/gcd.v
```

`ecc init` generates `gcd/ecc.toml`. Edit it as needed. `pdk.root` is required
unless `CHIPCOMPILER_ICS55_PDK_ROOT` is already set (the installer
`--with-toolchain` wrapper does this):

```toml
[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/gcd.v"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "/path/to/icsprout55-pdk"

[flow]
preset = "rtl2gds" # rtl2gds | rcx | harden | syn_sta
run = "default"
```

Then validate and run:

```bash
ecc check --project gcd
ecc run --project gcd
ecc status --project gcd
ecc log --project gcd
```

## CLI Commands

Run `ecc --help` (or `ecc <command> --help`) for full usage. Common commands:

| Command | Description |
| --- | --- |
| `ecc init <name>` | Create a project skeleton and `ecc.toml` |
| `ecc check` | Validate RTL, constraints, PDK, tools, and config |
| `ecc run` | Run the configured RTL-to-GDS flow |
| `ecc status` | Show run and step status |
| `ecc log [step]` | Show available logs or step log content |
| `ecc config [step] --resolved` | Show resolved project or step configuration |
| `ecc param` | Manage parameter overrides (`list`, `show`, `set`, `unset`, `diff`) |
| `ecc version` | Show ECC runtime and component versions |
| `ecc layout-image` | Render a GDS file into a layout image |

Project commands accept `--project <dir>` (defaults to the current directory).
Most commands support `--plain`, `--json`, and `--jsonl` output for scripting.

For the full command model — `ecc.toml` reference, flow presets, step-level
rerun (`--resume`, `--from`, `--only`), and parameter overrides — see the
[CLI Design Specification](docs/specification/cli-design.md).

## Features

- **Complete RTL-to-GDS Flow** - Synthesis, placement, routing, timing optimization
- **Open-Source EDA Integration** - Yosys (synthesis), ECC-DreamPlace (placement), ECC-Tools (CTS, routing, signoff), KLayout (viewer)
- **CLI Automation** - Scriptable flow execution from command line
- **Portable Deployment** - Installer or Nix

## 🛠️ Integrated Tools

| Tool | Purpose | Status |
|------|---------|--------|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL Synthesis | ✅ |
| [ECC-DreamPlace](https://github.com/openecos-projects/ecc-dreamplace) | Placement | ✅ |
| [ECC-Tools](https://github.com/openecos-projects/ecc-tools) | Physical Design (CTS, Routing, Signoff) | ✅ |
| [KLayout](https://www.klayout.de/) | Layout Viewer | ✅ |

## Documentation

- [Documentation Index](docs/index.md) - Complete navigation
- [CLI Design Specification](docs/specification/cli-design.md) - Command surface and `ecc.toml` reference
- [Architecture](docs/architecture.md) - System design and patterns
- [Development Guide](docs/development.md) - Setup and workflows
- [Examples](docs/examples/) - Usage examples

## Contributing

Contributions welcome! See [Development Guide](docs/development.md) for setup instructions.

## Acknowledgments

Special thanks to these open-source projects:

- [Yosys](https://github.com/YosysHQ/yosys) - RTL Synthesis
- [ECC-DreamPlace](https://github.com/openecos-projects/ecc-dreamplace) - Placement
- [ECC-Tools](https://github.com/openecos-projects/ecc-tools) - Physical Design Backend
- [KLayout](https://www.klayout.de/) - Layout Viewer
- [nixpkgs](https://github.com/NixOS/nixpkgs) - A collection of Nix packages

<div align="center">

**Built by the ECOS Team**

[Report Issues](https://github.com/openecos-projects/ecc/issues) · [Discussions](https://github.com/openecos-projects/ecc/discussions)

</div>
