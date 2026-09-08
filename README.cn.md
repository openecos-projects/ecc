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

### 安装脚本（推荐）

安装 `ecc` CLI（Linux x86_64，glibc 2.34+）：

```sh
curl -fsSL http://release.openecos.com/installers/ecc/latest/ecc-installer.sh | sh
```

同时安装 Yosys（OSS CAD Suite）和 ICS55 PDK：

```sh
curl -fsSL http://release.openecos.com/installers/ecc/latest/ecc-installer.sh | sh -s -- --with-toolchain
```

wrapper 默认安装到 `~/.local/bin`。如果该目录不在 `PATH` 中，请加入：

```sh
export PATH="$HOME/.local/bin:$PATH"
```

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
然后配置工作区（源码开发的推荐方式）：

```bash
uv sync --no-build-isolation-package ecc-dreamplace --no-build-isolation-package ecc-tools-bin --verbose
```

完整搭建见 [开发指南](docs/development.cn.md)。

如需自己编译可安装的 CLI 包（与官方 release 相同的 PyInstaller 流程）：

```bash
ECOS_PYINSTALLER_MODE=onedir uv run --no-sync --managed-python \
  pyinstaller ecc.spec --clean --noconfirm
# 重建 dist/ecc/（onedir，约 0.9G；首跑会触发 dreamplace 的 cmake 安装，属正常）

# 安装到本机（覆盖现有安装位，如 ~/.local/ecc；PATH 中指向它的软链无需改动）
rm -rf ~/.local/ecc && mkdir -p ~/.local/ecc && cp -a dist/ecc/. ~/.local/ecc/
ecc --help            # 验证应有的命令已列出
```

## 快速开始

以下命令使用已安装的 `ecc`。未安装时，在每条命令前加 `nix run . --`
（例如 `nix run . -- init gcd`）。

如果安装时加了 `--with-toolchain`，Yosys 和 ICS55 PDK 已由 `ecc` wrapper
配置好。否则请带 `--with-toolchain` 重新运行安装脚本。Nix flake 已自带
Yosys；未使用安装脚本工具链时需要设置 `pdk.root`。

创建项目并添加 RTL：

```bash
ecc init gcd
cp /path/to/gcd.v gcd/rtl/gcd.v  # 示例设计：docs/examples/gcd/gcd.v
```

`ecc init` 会生成 `gcd/ecc.toml`，按需编辑。未设置
`CHIPCOMPILER_ICS55_PDK_ROOT` 时必须填写 `pdk.root`（安装脚本
`--with-toolchain` 的 wrapper 会设置该环境变量）：

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
preset = "rtl2gds" # rtl2gds | syn_sta | synthesis_lec
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
| `ecc doctor` | 检查主机环境：PDK、yosys（含 slang）和内置工具 |
| `ecc doc <topic>` | 在终端阅读内置文档（`config` 配置参考、`ug` 用户指南、`tutorial` 教程） |
| `ecc run` | 运行配置的 RTL-to-GDS 流程 |
| `ecc status` | 快速查看 run/步骤进度概要 |
| `ecc log [step]` | 显示可用日志或步骤日志内容 |
| `ecc config [step]` | 显示解析后的项目或步骤配置 |
| `ecc migrate` | 将旧版 `runs/` 项目迁移到 manifest 布局 |
| `ecc param` | 管理参数覆盖（`list`、`show`、`set`、`unset`、`diff`） |
| `ecc pdk` | 管理 PDK 路径（`set-root`、`show`、`unset`） |
| `ecc project` | 编辑 `ecc.toml` 中的项目声明（`set`、`unset`、`add`、`remove`、`show`） |
| `ecc workspace` | 从项目配置刷新受管 workspace |
| `ecc signoff` | 检查签核就绪度并导出签核包 |
| `ecc report` | 生成设计总结、QoR、签核清单和步骤报告 |
| `ecc version` | 显示 ECC 运行时和组件版本 |
| `ecc layout-image` | 将 GDS 文件渲染为版图图像 |

项目命令均接受 `--project <dir>`（默认为当前目录）。大多数命令支持
`--plain` 输出，便于脚本化。

完整指南随 CLI 分发、可离线阅读：`ecc doc ug`（用户指南）、
`ecc doc config`（配置参考）、`ecc doc tutorial`（从零上手的教程）。


## 功能特性

- **完整 RTL-to-GDS 流程** - 综合、布局、布线、时序优化
- **开源 EDA 集成** - Yosys（综合）、ECC-DreamPlace（布局）、ECC-Tools（布线、签核）、KLayout（查看器）
- **CLI 自动化** - 可脚本化的命令行流程执行
- **便携部署** - 安装脚本或 Nix

## 🛠️ 集成工具

| 工具 | 用途 | 状态 |
|------|------|------|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL 综合 | ✅ |
| [ECC-DreamPlace](https://github.com/openecos-projects/ecc-dreamplace) | 布局 | ✅ |
| [ECC-Tools](https://github.com/openecos-projects/ecc-tools) | 物理设计（时钟树、布线、签核） | ✅ |
| [KLayout](https://www.klayout.de/) | 版图查看 | ✅ |

## 文档

- [文档索引](docs/index.md) - 完整导航
- [开发指南](docs/development.cn.md) - 配置和工作流
- [示例](docs/examples/) - 使用示例

## 参与贡献

欢迎贡献！配置说明请参阅 [开发指南](docs/development.cn.md)。

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
