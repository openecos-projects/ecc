# ECOS Chip Compiler (ECC)

<div align="center">

**开源芯片设计自动化解决方案**

[![ECC](https://img.shields.io/badge/ECC-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc)
[![ECC-Tools](https://img.shields.io/badge/ECCTools-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc-tools)
[![License](https://img.shields.io/badge/License-Apache_2.0-121011?style=for-the-badge&logo=apache&logoColor=white)](LICENSE)

[![Python](https://img.shields.io/badge/Python-121011?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Nix](https://img.shields.io/badge/Nix-121011?style=for-the-badge&logo=nixos&logoColor=white)](https://nixos.org/)

[![documentation](https://img.shields.io/badge/documentation-121011?style=for-the-badge)](README.md)
[![文档](https://img.shields.io/badge/文档-121011?style=for-the-badge)](README.cn.md)

</div>


## 项目简介

ECOS Chip Compiler 是一个**开源芯片设计自动化解决方案**，集成 EDA 工具（Yosys、[**ECC-DreamPlace**](https://github.com/openecos-projects/ecc-dreamplace)、[**ECC-Tools**](https://github.com/openecos-projects/ecc-tools)、KLayout）实现完整的 RTL-to-GDS 设计流程。由 [**ECOS 团队**](https://github.com/openecos-projects) 开发维护。

GUI（ECOS Studio）已迁移至 [ecos-studio](https://github.com/0xharry/ecos-studio) 仓库。

**使用方式：**
- **CLI (`ecc`)** - 面向项目的命令行流程执行
- **Python API** - 将 `chipcompiler` 作为库使用


## 安装

### 预构建 CLI 包（推荐）

从 [GitHub Releases](https://github.com/openecos-projects/ecc/releases) 下载
`ecc-cli-linux-x86_64.tar.gz`（PyInstaller 打包，Linux x86_64）并解压：

```bash
mkdir -p ~/.local/ecc
tar -xzf ecc-cli-linux-x86_64.tar.gz -C ~/.local/ecc
~/.local/ecc/ecc --help
```

将 `~/.local/ecc` 加入 `PATH` 后即可在任意位置运行 `ecc`。

### Nix

已安装 [Nix](https://nixos.org/) 时，**带子模块**克隆仓库（必须——
`chipcompiler/thirdparty/` 会拉取 `ecc-tools` 和 `ecc-dreamplace`），
然后通过 flake 运行 ECC：

```bash
git clone --recursive https://github.com/openecos-projects/ecc.git
cd ecc
nix run . -- --help
```

如果克隆时没带 `--recursive`：

```bash
git submodule update --init --recursive
```

### 源码构建

使用 `uv` 进行 Python 开发时，按上述方式（带 `--recursive`）克隆仓库，
然后参照 [开发指南](docs/development.md) 配置工作区。

## 快速开始

以下命令使用已安装的 `ecc`。未安装时，在每条命令前加 `nix run . --`
（例如 `nix run . -- init gcd`）。

### 前置准备

运行流程需要 Yosys 和 PDK：

**Yosys** —— 从 [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/releases)
下载适用于你平台的最新 release，解压后将 ECC 指向解压目录：

```bash
export CHIPCOMPILER_OSS_CAD_DIR=/path/to/oss-cad-suite
```

（通过 Nix flake 运行时不需要——flake 已自带 Yosys。）

**PDK** —— 克隆 [icsprout55-pdk](https://github.com/openecos-projects/icsprout55-pdk)
并运行 `make unzip` 下载 liberty 文件：

```bash
git clone --depth 1 https://github.com/openecos-projects/icsprout55-pdk.git
cd icsprout55-pdk && make unzip && cd ..
```

然后在 `ecc.toml` 中将 `pdk.root` 设为 PDK 路径（或导出
`CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/icsprout55-pdk`）。

创建项目并添加 RTL：

```bash
ecc init gcd
cp /path/to/gcd.v gcd/rtl/gcd.v  # 示例设计：docs/examples/gcd/gcd.v
```

`ecc init` 会生成 `gcd/ecc.toml`——编辑它并设置你的 PDK 路径：

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

然后校验并运行：

```bash
ecc check --project gcd
ecc run --project gcd
ecc status --project gcd
ecc log --project gcd
```

## CLI 命令

运行 `ecc --help`（或 `ecc <command> --help`）查看完整用法。常用命令：

| 命令 | 说明 |
| --- | --- |
| `ecc init <name>` | 创建项目骨架和 `ecc.toml` |
| `ecc check` | 校验 RTL、约束、PDK、工具和配置 |
| `ecc run` | 运行配置的 RTL-to-GDS 流程 |
| `ecc status` | 显示运行和步骤状态 |
| `ecc log [step]` | 显示可用日志或步骤日志内容 |
| `ecc config [step] --resolved` | 显示解析后的项目或步骤配置 |
| `ecc param` | 管理参数覆盖（`list`、`show`、`set`、`unset`、`diff`） |
| `ecc version` | 显示 ECC 运行时和组件版本 |
| `ecc layout-image` | 将 GDS 文件渲染为版图图像 |

项目命令均接受 `--project <dir>`（默认为当前目录）。大多数命令支持
`--plain`、`--json` 和 `--jsonl` 输出，便于脚本化。

完整的命令模型——`ecc.toml` 参考、流程预设、步骤级重跑
（`--resume`、`--from`、`--only`）和参数覆盖——请参阅
[CLI 设计规范](docs/specification/cli-design.md)。

## 功能特性

- **完整 RTL-to-GDS 流程** - 综合、布局、布线、时序优化
- **开源 EDA 集成** - Yosys（综合）、ECC-DreamPlace（布局）、ECC-Tools（布线、签核）、KLayout（查看器）
- **CLI 自动化** - 可脚本化的命令行流程执行
- **便携部署** - 预构建 CLI 包或 Nix

## 🛠️ 集成工具

| 工具 | 用途 | 状态 |
|------|------|------|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL 综合 | ✅ |
| [ECC-DreamPlace](https://github.com/openecos-projects/ecc-dreamplace) | 布局 | ✅ |
| [ECC-Tools](https://github.com/openecos-projects/ecc-tools) | 物理设计（时钟树、布线、签核） | ✅ |
| [KLayout](https://www.klayout.de/) | 版图查看 | ✅ |

## 文档

- [文档索引](docs/index.md) - 完整导航
- [CLI 设计规范](docs/specification/cli-design.md) - 命令接口和 `ecc.toml` 参考
- [架构](docs/architecture.md) - 系统设计和模式
- [开发指南](docs/development.md) - 配置和工作流
- [示例](docs/examples/) - 使用示例

## 参与贡献

欢迎贡献！配置说明请参阅 [开发指南](docs/development.md)。

## 致谢

特别感谢以下开源项目：

- [Yosys](https://github.com/YosysHQ/yosys) - RTL 综合
- [ECC-DreamPlace](https://github.com/openecos-projects/ecc-dreamplace) - 布局
- [ECC-Tools](https://github.com/openecos-projects/ecc-tools) - 物理设计后端
- [KLayout](https://www.klayout.de/) - 版图查看器
- [nixpkgs](https://github.com/NixOS/nixpkgs) - Nix 包合集

<div align="center">

**Built by the ECOS Team**

[报告问题](https://github.com/openecos-projects/ecc/issues) · [讨论交流](https://github.com/openecos-projects/ecc/discussions)

</div>
