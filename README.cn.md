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

ECOS Chip Compiler 是一个**开源芯片设计自动化解决方案**，集成 EDA 工具（Yosys、[**ECC-Tools**](https://github.com/openecos-projects/ecc-tools)、KLayout）实现完整的 RTL-to-GDS 设计流程。由 [**ECOS 团队**](https://github.com/openecos-projects) 开发维护。

**两种使用方式：**
- **桌面 GUI (ECOS Studio)** - 可视化设计工具，用于交互式芯片设计
- **Python API** - 编程式流程控制，用于自动化

详细架构设计请参阅 **[架构文档](docs/architecture.md)**。

## 快速开始

### 桌面应用（推荐）

**方式一：AppImage（Linux x86_64）**

从 [Releases](https://github.com/openecos-projects/ecc/releases) 下载最新 AppImage：

```bash
# 下载 AppImage
wget https://github.com/openecos-projects/ecc/releases/latest/download/ecos-studio-x86_64.AppImage

# 添加执行权限
chmod +x ecos-studio-x86_64.AppImage

# 运行
./ecos-studio-x86_64.AppImage
```

AppImage 是便携格式，无需安装即可在大多数 Linux 发行版上运行。所有依赖已打包。

**方式二：通过 Nix 安装**

```bash
# 直接从 GitHub 运行
nix shell github:openecos-projects/ecc#ecos-studio

# 启动 GUI
ecc-client
```

Nix 构建包含所有依赖。提供二进制缓存以加速构建。

**支持平台：** x86_64 Linux（Ubuntu 24.04+ 或其他发行版）

### 开发环境

开发或使用 Python API，请参阅 **[开发指南](docs/development.md)**。

## 功能特性

- **完整 RTL-to-GDS 流程** - 综合、布局、布线、时序优化
- **可视化设计界面** - 基于 PixiJS 的版图编辑器，WebGL 渲染
- **开源 EDA 集成** - Yosys（综合）、ECC-Tools（布局布线）、KLayout（查看器）
- **Python API** - 可脚本化自动化，支持批处理
- **REST API** - FastAPI 后端，支持外部工具集成
- **便携部署** - AppImage、Nix 或独立构建

## 🛠️ 集成工具

| 工具 | 用途 | 状态 |
|------|------|------|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL 综合 | ✅ |
| [ECC-Tools](https://github.com/openecos-projects/ecc-tools) | 物理设计（布局布线） | ✅ |
| [KLayout](https://www.klayout.de/) | 版图查看 | 🚧 |
| [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) | 备选后端 | 🚧 |

## 文档

- [架构](docs/architecture.md) - 系统设计和模式
- [开发指南](docs/development.md) - 配置和工作流
- [API 指南](docs/api-guide.md) - Python API 参考
- [GUI 指南](docs/gui-guide.md) - GUI 开发
- [示例](docs/examples/) - 使用示例
- [文档索引](docs/index.md) - 完整导航

## 参与贡献

欢迎贡献！配置说明请参阅 [开发指南](docs/development.md)。

## 致谢

特别感谢以下开源项目：

- [Yosys](https://github.com/YosysHQ/yosys) - RTL 综合
- [ECC-Tools](https://github.com/openecos-projects/ecc-tools) - 物理设计后端
- [KLayout](https://www.klayout.de/) - 版图查看器
- [FastAPI](https://fastapi.tiangolo.com/) - Python Web 框架
- [Tauri](https://tauri.app/) - 桌面应用框架
- [Vue.js](https://vuejs.org/) - 前端框架
- [PixiJS](https://pixijs.com/) - 2D 渲染引擎

<div align="center">

**Built by the ECOS Team**

[报告问题](https://github.com/openecos-projects/ecc/issues) · [讨论交流](https://github.com/openecos-projects/ecc/discussions)

</div>
