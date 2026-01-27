# ECOS Chip Compiler (ECC)

<div align="center">

**开源芯片设计自动化解决方案**

[![Python](https://img.shields.io/badge/Python-121011?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Nix](https://img.shields.io/badge/Nix-121011?style=for-the-badge&logo=nixos&logoColor=white)](https://nixos.org/)
[![ECC](https://img.shields.io/badge/ECC-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc)
[![ECC-Tools](https://img.shields.io/badge/ECCTools-EF6C00?style=for-the-badge)](https://github.com/openecos-projects/ecc-tools)
[![Tauri](https://img.shields.io/badge/Tauri-121011?style=for-the-badge&logo=tauri&logoColor=white)](https://tauri.app/)

<!-- [![License](https://img.shields.io/badge/License-Apache_2.0-121011?style=for-the-badge&logo=apache&logoColor=white)](LICENSE) -->
[![English](https://img.shields.io/badge/English-121011?style=for-the-badge)](README.md)
[![简体中文](https://img.shields.io/badge/简体中文-121011?style=for-the-badge)](README.cn.md)

</div>


## 项目简介

ECOS Chip Compiler 是一个基于 Python 的**芯片设计自动化解决方案**，集成开源 EDA 工具（Yosys、[**ECC-Tools**](https://github.com/openecos-projects/ecc-tools)、Magic、KLayout）和多个自定义组件，实现完整的 RTL-to-GDS 设计流程。项目目前由 [**ECOS 团队**](https://github.com/openecos-projects) 开发维护。

请参考 **[快速开始指南](#-快速开始)** 部分以快速入门。

**两种使用方式**:
- **Python API** - 编程式流程控制（可参考[使用示例](#使用示例)）
- **桌面 GUI** - 可视化设计工具（**仍在开发中，即将发布**）

详细架构设计请参阅 **[架构文档](docs/architecture.md)**。

## 快速开始

### 安装所有依赖

支持平台：x86_64 Linux（**Ubuntu 24.04+**，或其他安装了 **Nix** 的发行版）

**方式一：Nix（推荐）**

如果还未安装 Nix 包管理器（Nix 不是 NixOS！）：https://nixos.org/download

```bash
# 进入开发环境
nix develop
```

**方式二：手动安装**

```bash
# 安装 uv 包管理器
curl -LsSf https://astral.sh/uv/install.sh | sh

# 构建项目依赖
./build.sh
source .venv/bin/activate
```

更多安装选项请参阅 **[开发指南](docs/development.md)**。

## 使用示例

### Python API

这是一个使用 [icsprout55-pdk](https://github.com/openecos-projects/icsprout55-pdk) 实现 GCD 设计的示例流程：

```python
from chipcompiler.data import create_workspace, get_pdk, StepEnum, StateEnum
from chipcompiler.engine import EngineFlow
from benchmark import get_parameters

# 设置路径
workspace_dir = "./gcd_workspace"
input_verilog = "./docs/examples/gcd.v"

# 加载 PDK 和设计参数
pdk = get_pdk("ics55")
parameters = get_parameters("ics55", "gcd")

# 创建工作空间
workspace = create_workspace(
    directory=workspace_dir,
    origin_def="",
    origin_verilog=input_verilog,
    pdk=pdk,
    parameters=parameters
)

# 配置流程引擎并添加步骤
engine_flow = EngineFlow(workspace=workspace)
if not engine_flow.has_init():
    engine_flow.add_step(step=StepEnum.FLOORPLAN, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.NETLIST_OPT, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.PLACEMENT, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.CTS, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.ROUTING, tool="ecc", state=StateEnum.Unstart)
    engine_flow.add_step(step=StepEnum.FILLER, tool="ecc", state=StateEnum.Unstart)

# 创建步骤工作空间并运行
engine_flow.create_step_workspaces()
engine_flow.run_steps()
```

完整参考：**[docs/examples/gcd](docs/examples/gcd/README.cn.md)**

完整 API 文档请参阅 **[API 指南](docs/api-guide.md)**。

### 桌面 GUI

> [!WARNING]
> 桌面 GUI 仍在开发中，我们将很快发布第一个版本。

## 更多文档

完整文档导航请参阅 [文档索引](docs/index.md)。

## 🛠️ 集成工具

| 工具 | 用途 | 状态 |
|------|------|------|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL 综合 | ✅ |
| [ECC-Tools](https://github.com/openecos-projects/ecc-tools) | 后端流程 | ✅ |
| [KLayout](https://www.klayout.de/) | 版图查看 | 🚧 |
| [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) | 后端流程 | 🚧 |

## 参与贡献

详见 [开发指南](docs/development.md)。

<!-- ## 📄 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源协议。 -->

## 致谢

特别感谢以下开源项目：

- [Yosys](https://github.com/YosysHQ/yosys) - RTL 综合
- [ECC-Tools](https://github.com/openecos-projects/ecc-tools) - 开源 EDA 工具（物理设计）
- [KLayout](https://www.klayout.de/) - 版图查看器
- [FastAPI](https://fastapi.tiangolo.com/) - Python Web 框架
- [Tauri](https://tauri.app/) - 桌面应用框架
- [Vue.js](https://vuejs.org/) - 前端框架
- [PixiJS](https://pixijs.com/) - 2D 渲染引擎



<div align="center">

**Built with ❤️ by the ECOS Team**

[报告问题](https://github.com/openecos-projects/ecc/issues) · [讨论交流](https://github.com/openecos-projects/ecc/discussions)

</div>
