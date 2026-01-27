# 使用 Python API 的 GCD 示例

## 安装

请确保已按 **[README](../../../README.cn.md#安装所有依赖)** 中的说明安装所有依赖。

## 使用示例

完整示例代码见：**[ics55flow.py](ics55flow.py)**。

我们可以直接运行示例：

```bash
python3 docs/examples/gcd/ics55flow.py
```

## 详细解释

开始之前，我们需要先设置工作空间。下面的代码片段展示了如何使用 [ICS55 PDK](https://github.com/openecos-projects/icsprout55-pdk) 为 GCD 示例生成参数：

```python
from chipcompiler.data import get_pdk
from benchmark import get_parameters

# 设置路径
workspace_dir = "./gcd_workspace"
input_verilog = "./docs/examples/gcd/gcd.v"

# 加载 PDK 和设计参数
# 在执行 git submodule update --init --recursive 后会自动下载 ICS55 PDK
pdk = get_pdk("ics55")
parameters = get_parameters("ics55", "gcd")
```

使用下面的 Python 代码生成工作空间：

```python
from chipcompiler.data import create_workspace, get_pdk, StepEnum, StateEnum
workspace = create_workspace(
    directory=workspace_dir,
    origin_def="",
    origin_verilog=input_verilog,
    pdk=pdk,
    parameters=parameters
)
# 使用 `load_workspace` 从已有工作空间恢复
# workspace = load_workspace(directory=workspace_dir)
```

工作空间将从零开始创建，结构如下：

```
gcd_workspace/
├── flow.json       # 流程状态文件
├── parameters.json # 设计参数文件
├── CTS_ecc         # CTS 步骤工作空间
│   ├── analysis    # 从指标数据中提取的分析数据文件
│   ├── config      # 配置文件
│   ├── data        # 步骤生成的数据文件
│   ├── feature     # 指标数据特征文件
│   ├── log         # 各步骤日志文件
│   ├── output      # 输出产物
│   ├── report      # 步骤生成的报告
│   └── script      # 步骤脚本
├── drc_ecc
│   ...             # 与上方结构类似，下方亦然
│   └── script
├── filler_ecc
│   ...
│   └── script
├── fixFanout_ecc
│   ...
│   └── script
├── Floorplan_ecc
│   ...
│   └── script
├── legalization_ecc
│   ...
│   └── script
├── log
│   └── gcd.xxxx-01-22_16-05-25 # 全局日志文件
├── origin
│   ├── gcd.sdc
│   ├── filelist.f
│   └── rtl
├── place_ecc
│   ...
│   └── script
├── route_ecc
│   ...
│   └── script
└── Synthesis_yosys
    ...
    └── script
```

然后可以按如下方式设置流程引擎、添加步骤、创建步骤工作空间并运行：

```python
from chipcompiler.data import StepEnum, StateEnum
from chipcompiler.engine import EngineFlow

engine_flow = EngineFlow(workspace=workspace)
if not engine_flow.has_init():
    # 使用 `add_step` 将步骤加入流程
    engine_flow.add_step(step=StepEnum.SYNTHESIS, tool="Yosys", state=StateEnum.Unstart)
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

定义的流程如下：

```mermaid
graph LR
    A[Synthesis<br/>Yosys] --> B[Floorplan<br/>ECC-Tools]
    B --> C[Netlist Opt<br/>ECC-Tools]
    C --> D[Placement<br/>ECC-Tools]
    D --> E[CTS<br/>ECC-Tools]
    E --> F[Legalization<br/>ECC-Tools]
    F --> G[Routing<br/>ECC-Tools]
    G --> H[Filler<br/>ECC-Tools]
```

随后流程引擎会按顺序执行各步骤，你可以在每个步骤工作空间中查看日志和输出结果。

## 使用 Filelist

除了指定单个 RTL 文件，你还可以使用 **filelist** 来指定多个源文件和包含目录。这对于包含多个 RTL 模块的复杂项目非常有用。

### Filelist 格式

Filelist 是一个文本文件（通常使用 `.f` 扩展名），用于指定综合时所需的多个 RTL 源文件和包含目录。

示例 `filelist.f`：
```
# RTL 源文件
rtl/gcd.v
rtl/gcd_pkg.v
rtl/utils.v

# Verilog `include 指令使用的包含目录（.vh 头文件）
+incdir+rtl/include
+incdir+rtl/common

# 包含空格的路径需要用引号
"rtl/special modules/module.v"
```

**支持的解析语法：**
- **多个源文件**：每个 `.v` 文件单独占一行
- **注释**：使用 `#` 或 `//` 表示整行或行内注释
- **包含目录**：`+incdir+<路径>` - 将这些目录中的所有文件复制到工作空间
- **引号路径**：支持包含空格的路径：`"path with spaces/file.v"`
- **相对/绝对路径**：都支持
- **嵌套结构**：将文件复制到工作空间时保留目录层次结构

### 使用 Filelist 创建工作空间

创建工作空间时使用 `input_filelist` 参数：

```python
from chipcompiler.data import create_workspace, get_pdk
from benchmark import get_parameters

# 设置路径
workspace_dir = "./gcd_workspace_with_filelist"
input_filelist = "./docs/examples/gcd/filelist.f"

# 加载 PDK 和设计参数
pdk = get_pdk("ics55")
parameters = get_parameters("ics55", "gcd")

# 使用 filelist 创建工作空间
workspace = create_workspace(
    directory=workspace_dir,
    origin_def="",
    origin_verilog="",  # 使用 filelist 时不需要
    pdk=pdk,
    parameters=parameters,
    input_filelist=input_filelist  # 提供 filelist 而不是单个文件
)
```

当你提供 filelist 时，filelist 中引用的文件会被处理如下：
1. **文件复制**：filelist 中引用的所有文件会自动复制到工作空间
2. **包含目录**：`+incdir+` 目录中的文件也会被复制
3. **目录结构**：相对目录结构会被保留
4. **去重**：同时出现在 filelist 和 `+incdir+` 中的文件只会被复制一次

复制的文件会在 `workspace/origin/` 中组织，保留目录结构：
```
gcd_workspace_with_filelist/
├── origin/
│   ├── filelist.f        # 复制的 filelist
│   ├── rtl/
│   │   ├── gcd.v
│   │   ├── gcd_pkg.v
│   │   ├── utils.v
│   │   ├── include/      # 来自 +incdir+rtl/include 的文件
│   │   └── common/       # 来自 +incdir+rtl/common 的文件
│   ├── gcd.sdc           # 约束文件
│   └── ...
└── ...
```

`+incdir+` 目录中的所有文件（通常是 `.vh` 头文件）都会被复制到工作空间，使 Verilog 综合工具能够解析 `include 语句而无需修改路径。
