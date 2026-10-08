# 环境、RTL 与设计输入

适用：部署 ECC、创建项目、确认约束或准备非 RTL 入口。选择器见 [运行契约](run-workspaces.md)，物理参数见 [配置指南](config-floorplan.md)。

## 1. 发现实际工具

```bash
command -v ecc
ecc --version
ecc version
ecc --help
ecc doc ug --lang cn --plain
```

文档基线 `v0.1.0-alpha.12` 不是“最新版本”声明。记录实际 ECC、ecc-tools、DreamPlace、Yosys、Sizer、KLayout 版本和路径。`unknown/not installed` 需要诊断，单行 ECC 版本不证明工具齐备。

源码环境可能使用 `uv run ecc` 或 `nix run . -- ...`，只有环境已按 ECC 开发指南配置好才用；不要在芯片项目里任意 `uv sync`，不要用系统 Yosys 替代 wrapper 解析版本。

### 安装条件和安全

- 预编译部署面向 Linux x86_64、glibc 2.34+；检查实际架构、glibc、fontconfig、网络与磁盘。教程建议至少 10 GB 空闲，多候选物理实验按实际增长另留空间。
- `ecc` 和 PyInstaller `_internal/` 必须保持相邻；加 PATH 或建立 symlink，不单独复制二进制。
- 官方安装器的 `--with-toolchain` 用于 OSS CAD Suite 与 ICS55 PDK。下载/安装属于外部副作用，须在用户授权范围。原文使用 HTTP 安装器：不要不经检查就 `curl | sh`。优先可验证发布包；需要脚本时先下载，检查来源、内容与可获得的校验信息，再执行。HTTPS/签名/校验和不可用时明确说明，不伪造完整性验证。
- 不自动 sudo、改 shell rc、升级所有工具、更新 submodule 或替换旧 wrapper。代理不替代来源验证。
- 教程的下载量、4–5 分钟耗时、1.5 GB 峰值内存只属于 gcd 示例，不是任意设计保证。

### doctor 与 check

```bash
ecc doctor --project "$PROJECT" --plain
ecc check --project "$PROJECT" --plain
```

`doctor` 检查环境。当前指南必需项包括 yosys/slang、ecc-tools、DreamPlace、Sizer、PDK，KLayout 为可选渲染组件；退出 0 的 attention 可能只表示可选失败。flow 预检按所选步骤检查工具；最小综合实验不一定需要所有物理工具，但须报告 doctor 未满足项。

`check` 检查声明、文件与 PDK，不替代工具就绪或 HDL 功能验证。教程与用户指南对 RTL 存在性校验时机有不同表述：不要依赖差异，自己核对所有源文件，再 check；run 创建仍会按入口校验。

Sizer 必须同时有可执行文件和包含 `src/sizer_os.tcl` 的 runtime root，可由 `CHIPCOMPILER_ECC_SIZER_ROOT` 或二进制位置发现。`which Sizer` 成功不足以证明就绪。既有 workspace 恢复与新建预检可能不同，环境变化后恢复前也跑 doctor。

## 2. PDK 接入

文档支持对象为 `ics55`。其他工艺先核对实际工具支持；改 `pdk.name` 不等于工艺移植。

```bash
ecc pdk show --project "$PROJECT" --plain
ecc pdk set-root /absolute/path/to/icsprout55-pdk --project "$PROJECT" --plain
ecc pdk unset --project "$PROJECT" --plain
```

root 优先级：project `pdk.root` > `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT`。show 可能展示 checkout 相邻的默认目录，但当前 check/run 仍要求上述显式来源之一；show 找到目录不证明 flow 可用。

核对 tech LEF、cell/macro LEF、Liberty、映射、Harden 资源和所有请求 corner。PDK 只 clone 未展开数据可能缺 Liberty/GDS；在授权范围按该 PDK README 执行 `make -C "$PDK_ROOT" unzip`，不修改工具资源。

| 覆盖 key | 相对路径基准 | 用途 |
|---|---|---|
| `pdk.tech` | PDK root | tech LEF |
| `pdk.lefs` | PDK root | 单元/宏 LEF 列表 |
| `pdk.libs` | PDK root | Liberty 列表 |
| `pdk.mapping_file` | PDK root | 综合映射 |
| `pdk.sdc`、`pdk.spef` | project | 设计约束/寄生数据 |

先 `param show` 再 project 级设置；这些路径不支持 workspace 局部修改。更改后 fresh 或授权 refresh。不同 PDK/库版本的结果不可作为同组 PPA 候选混比。

## 3. 从 RTL 建项

核对规格、top、源文件/filelist、clock/reset、频率、接口时序、参数化配置、宏/IP、PDK 与约束。信息充分就执行；缺失且会改变设计的关键规格再询问。

```bash
ecc init "$PROJECT" --plain
ecc project set design.top chip_top --project "$PROJECT" --plain
ecc project set design.rtl rtl/top.sv rtl/datapath.sv --project "$PROJECT" --plain
ecc project add design.rtl rtl/control.sv --project "$PROJECT" --plain
ecc project remove design.rtl rtl/unused.sv --project "$PROJECT" --plain
ecc project set design.clock_port clk_i --project "$PROJECT" --plain
ecc project set design.frequency_mhz 100 --project "$PROJECT" --plain
ecc project set pdk.name ics55 --project "$PROJECT" --plain
ecc project set flow.preset rtl2gds --project "$PROJECT" --plain
ecc project show --project "$PROJECT" --plain
```

`PROJECT` 为新目录，先核对 `init --help` 和父目录。已有项目不重新 init。例子的端口、频率不是通用配方。

`set design.rtl` 整表替换，`add/remove` 改列表。可注册 `rtl/filelist.f`；查实际 bundled guide 和 ECC filelist grammar，核对源文件、include 搜索路径、defines 与相对路径基准。不要猜嵌套/include 语法，不用 shell eval 展开 filelist。

### RTL 功能验证

在授权源目录工作，不改 workspace 快照。按项目习惯 lint/elaborate/simulate/test，检查组合环、latch、未驱动信号、reset、位宽/符号和可综合性。记录测试/覆盖边界；无测试不称功能已验证。

RTL 改动与纯物理实验分开。LEC 是逻辑保持证据，但跳过 LEC、缺参考网表或物理 flow 成功不证明新 RTL 满足规格。硬宏/SRAM 必须有匹配的逻辑模型、LEF、Liberty，必要时 GDS；不能把 blackbox 当成已实现存储器。

## 4. 时钟和 SDC

`T_clk(ns)=1000/frequency_mhz`。不能仅改报告频率声称约束改变。

未声明 `design.sdc` 时，当前生成器创建 `origin/<design>.sdc`：由 clock_port 建真实时钟，无端口可能建虚拟时钟；IO delay 为 0；setup/hold uncertainty 分别为周期的 1.5%/0.5%；clock/input transition 上限分别为 0.15/0.20 ns；含 cts.max_fanout 和 PDK 负载。这是入门起点，不是系统级完整约束。

有真实 IO 预算、多时钟/generated clock、异步域、false/multicycle path、负载时，在独立输入目录编写审查 SDC，再注册：

```bash
ecc project set design.sdc constraints/chip.sdc --project "$PROJECT" --plain
```

自定义 SDC 原样复制；参数变化只自动刷新带 ECC 生成标记的 SDC。因此改 frequency 或 fanout 不一定改变用户 SDC。核对实际 SDC 与 STA 周期、端点/路径覆盖；单个 frequency_mhz 不能代表全部多时钟意图。不随意设 false path 消除真实违例。

## 5. 非 RTL 输入和验收

可声明 `design.netlist/golden_netlist/def/sdc/spef`，以 fresh range 起跑。匹配 DEF/网表的实例、库、设计名、阶段与命名；压缩文件也需有效。需求见 [范围入口](run-workspaces.md)。捕获 origin 后原文件修改不自动更新实验。

交付：实际环境/PDK、输入来源、top/clock/frequency、SDC 类型/预算、宏资源、功能验证、doctor/check。project 声明若不同于旧 workspace 快照，明确指出，不能将 project 配置当成旧实验实际值。
