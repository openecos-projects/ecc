# ChipCompiler Documentation

Welcome to the ChipCompiler documentation center.

## CLI Guides

The `ecc` command-line tool ships bilingual guides (`.en.md` / `.cn.md`):

- **[CLI Tutorial](../chipcompiler/docs/ecc-tutorial.en.md)** / **[中文教程](../chipcompiler/docs/ecc-tutorial.cn.md)** - From zero to RTL → Harden with a signoff package
  - Installing the ecc CLI, PDK, and Yosys
  - First project, the 15-step `rtl2gds` flow, signoff package, and reports
  - Tuning parameters, workspaces, and rerun scenarios
- **[CLI User Guide](../chipcompiler/docs/ecc-user-guide.en.md)** / **[中文用户指南](../chipcompiler/docs/ecc-user-guide.cn.md)** - All currently supported commands
  - Every command and option: `init`/`check`/`run`/`status`/`log`/`config`/`doctor`/`param`/`pdk`/`project`/`workspace`/`signoff`/`report`/`rpc`/`layout-image`
  - Run selectors (`--resume`/`--from`/`--to`/`--only`), error-code reference, end-to-end workflows
- **[CLI Config Reference](../chipcompiler/docs/ecc-config-ref.en.md)** / **[中文配置参考](../chipcompiler/docs/ecc-config-ref.cn.md)** - `ecc.toml`, workspace files, and the parameter system
- **[Staged Floorplan Flow](../chipcompiler/docs/floorplan-flow.en.md)** / **[分阶段 Floorplan 流程](../chipcompiler/docs/floorplan-flow.cn.md)** - Pre-floorplan, macro placement, post-floorplan, and the macro-location Tcl handoff
- **[RPC Guide](rpc-guide.md)** - Private JSON-RPC runtime sidecar protocol (`ecc rpc serve`)

## Core Documentation

- **[Development Guide](development.md)** / **[中文开发指南](development.cn.md)** - Development environment setup and workflows
  - Environment configuration
  - Code quality tools
  - Adding new EDA tools
  - Debugging and testing
  - Extending the `ecc` CLI

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
- **Run my first RTL-to-GDS flow** → [CLI Tutorial](../chipcompiler/docs/ecc-tutorial.en.md) / [中文教程](../chipcompiler/docs/ecc-tutorial.cn.md)
- **Look up an `ecc` command or option** → [CLI User Guide](../chipcompiler/docs/ecc-user-guide.en.md) / [中文用户指南](../chipcompiler/docs/ecc-user-guide.cn.md)
- **Understand `ecc.toml` / workspace files / parameters** → [CLI Config Reference](../chipcompiler/docs/ecc-config-ref.en.md) / [中文配置参考](../chipcompiler/docs/ecc-config-ref.cn.md)
- **Extend the CLI with new commands** → [CLI Dev Guide](development.md#extending-the-cli)
- **Use legacy workspace commands** → [RPC Guide](rpc-guide.md)
- **Set up development environment** → [Development Guide](development.md)
- **Create a release** → [Release Guide](release.md)
- **Add new tools** → [Development Guide - Adding EDA Tools](development.md#add-a-new-eda-tool)
- **Debug workflows** → [Development Guide - Debugging](development.md#debugging)

## Additional Resources

- [Main README](../README.md)
