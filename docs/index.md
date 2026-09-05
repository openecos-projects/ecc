# ChipCompiler Documentation

Welcome to the ChipCompiler documentation center.

## CLI Guides

The `ecc` command-line tool ships bilingual guides (`.en.md` / `.cn.md`):

- **[CLI Tutorial](ecc-cli-tutorial.en.md)** / **[中文教程](ecc-cli-tutorial.cn.md)** - From zero to RTL → Harden with a signoff package
  - Installing the ecc CLI, PDK, and Yosys
  - First project, the 15-step `rtl2gds` flow, signoff package, and reports
  - Tuning parameters, workspaces, and rerun scenarios
- **[CLI User Guide](ecc-cli-ug.en.md)** / **[中文用户指南](ecc-cli-ug.cn.md)** - All currently supported commands
  - Every command and option: `init`/`check`/`run`/`status`/`log`/`config`/`doctor`/`param`/`pdk`/`project`/`workspace`/`signoff`/`report`/`rpc`/`layout-image`
  - Run selectors (`--resume`/`--from`/`--to`/`--only`), error-code reference, end-to-end workflows
- **[CLI Config Reference](ecc-cli-config.en.md)** / **[中文配置参考](ecc-cli-config.cn.md)** - `ecc.toml`, workspace files, and the parameter system
- **[CLI Dev Guide](ecc-cli-dev.en.md)** / **[中文开发指南](ecc-cli-dev.cn.md)** - Adding or modifying CLI commands
- **[Workspace CLI Guide](workspace-cli.md)** - Private JSON-RPC runtime sidecar protocol (`ecc rpc serve`)

## Core Documentation

- **[Architecture](architecture.md)** - Detailed system architecture and design patterns
  - Layered architecture explanation
  - Core design patterns
  - Data flow and execution paths
  - Module details

- **[Development Guide](development.md)** - Development environment setup and workflows
  - Environment configuration
  - Code quality tools
  - Adding new EDA tools
  - Debugging and testing

- **[Release Guide](release.md)** - Release branch and hotfix release workflow
  - Preparing `release/v*` branches
  - Version bump and CI validation
  - Publishing releases from `v*` tags

## Technical Specifications

### File Format Specifications

ChipCompiler supports various EDA file formats. Technical specifications for parser implementations:

- **[Filelist Grammar](specification/filelist-grammar.md)** - EBNF grammar for EDA tool filelists
  - Supports file paths, +incdir directives, comments, quoted paths
  - Parser implementation: `chipcompiler/utility/filelist.py`

### CLI Specifications

- **[CLI Design](specification/cli-design.md)** - Progressive-disclosure CLI design and roadmap
  - Grep-friendly summary lines with disclosure commands
  - Project, run, step, metric, artifact, issue, and config object model
  - Phased roadmap for project setup, debug, traceability, and exploration

## Quick Navigation

### I want to...

- **Get started with ChipCompiler** → See main [README](../README.md)
- **Run my first RTL-to-GDS flow** → [CLI Tutorial](ecc-cli-tutorial.en.md) / [中文教程](ecc-cli-tutorial.cn.md)
- **Look up an `ecc` command or option** → [CLI User Guide](ecc-cli-ug.en.md) / [中文用户指南](ecc-cli-ug.cn.md)
- **Understand `ecc.toml` / workspace files / parameters** → [CLI Config Reference](ecc-cli-config.en.md) / [中文配置参考](ecc-cli-config.cn.md)
- **Extend the CLI with new commands** → [CLI Dev Guide](ecc-cli-dev.en.md)
- **Use legacy workspace commands** → [Workspace CLI Guide](workspace-cli.md)
- **Understand the architecture** → [Architecture](architecture.md)
- **Set up development environment** → [Development Guide](development.md)
- **Create a release** → [Release Guide](release.md)
- **Add new tools** → [Development Guide - Adding EDA Tools](development.md#add-a-new-eda-tool)
- **Debug workflows** → [Development Guide - Debugging](development.md#debugging)

## Additional Resources

- [Main README](../README.md)
