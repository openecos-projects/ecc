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

ECOS Chip Compiler 是一个**开源芯片设计自动化解决方案**，集成 EDA 工具（Yosys、[**ECC-Tools**](https://github.com/openecos-projects/ecc-tools)、KLayout）实现完整的 RTL-to-GDS 设计流程。由 [**ECOS 团队**](https://github.com/openecos-projects) 开发维护。

GUI（ECOS Studio）已迁移至 [ecos-studio](https://github.com/0xharry/ecos-studio) 仓库。

**使用方式：**
- **CLI (`cli`)** - 命令行流程执行
- **Python API** - 将 `chipcompiler` 作为库使用


## 快速开始

### CLI 流程运行

可以使用 `nix run .#cli -- ...` 直接创建 workspace 并执行完整 RTL2GDS 流程。

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

## 功能特性

- **完整 RTL-to-GDS 流程** - 综合、布局、布线、时序优化
- **开源 EDA 集成** - Yosys（综合）、ECC-Tools（布局布线）、KLayout（查看器）
- **CLI 自动化** - 可脚本化的命令行流程执行
- **便携部署** - Nix 或独立构建

## 🛠️ 集成工具

| 工具 | 用途 | 状态 |
|------|------|------|
| [Yosys](https://github.com/YosysHQ/yosys) | RTL 综合 | ✅ |
| [ECC-Tools](https://github.com/openecos-projects/ecc-tools) | 物理设计（布局布线） | ✅ |
| [KLayout](https://www.klayout.de/) | 版图查看 | 🚧 |

## 文档

- [文档索引](docs/index.md) - 完整导航
- [架构](docs/architecture.md) - 系统设计和模式
- [开发指南](docs/development.md) - 配置和工作流
- [示例](docs/examples/) - 使用示例

## 参与贡献

欢迎贡献！配置说明请参阅 [开发指南](docs/development.md)。

## 致谢

特别感谢以下开源项目：

- [Yosys](https://github.com/YosysHQ/yosys) - RTL 综合
- [ECC-Tools](https://github.com/openecos-projects/ecc-tools) - 物理设计后端
- [KLayout](https://www.klayout.de/) - 版图查看器
- [nixpkgs](https://github.com/NixOS/nixpkgs) - Nix 包合集

<div align="center">

**Built by the ECOS Team**

[报告问题](https://github.com/openecos-projects/ecc/issues) · [讨论交流](https://github.com/openecos-projects/ecc/discussions)

</div>
