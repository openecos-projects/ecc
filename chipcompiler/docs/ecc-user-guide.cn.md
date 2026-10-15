# ECC CLI 用户指南（当前支持的全部命令）

`ecc` 是 ECOS Chip Compiler 的项目制命令行入口，覆盖 RTL-to-GDS 流水的建项、校验、运行、状态/日志/配置查询、参数管理、签核与报告。本文已按 `ecc/` 子模块当前源码（v0.1.0-alpha.12）对齐；命令输出或采集自实际执行，或会明确标为示例（其中 run 状态可能是手工构造的演示数据）。

- 源码位置：[chipcompiler/cli/](https://github.com/openecos-projects/ecc/tree/main/chipcompiler/cli/)
- 命令扩展开发方式见 [development.cn.md](https://github.com/openecos-projects/ecc/blob/main/docs/development.cn.md#扩展-cli)

## 0. 调用方式

### 一键安装（推荐）

安装 `ecc` CLI（Linux x86_64，glibc 2.34+）：

```bash
curl -fsSL http://release.openecos.com/installers/ecc/latest/ecc-installer.sh | sh
```

同时安装 Yosys（OSS CAD Suite，含 slang 前端）与 ICS55 PDK：

```bash
curl -fsSL http://release.openecos.com/installers/ecc/latest/ecc-installer.sh | sh -s -- --with-toolchain
```

wrapper 默认安装到 `~/.local/bin`。该目录不在 `PATH` 中时加入：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`--with-toolchain` 安装的 wrapper 会导出 `CHIPCOMPILER_OSS_CAD_DIR` 与 `CHIPCOMPILER_ICS55_PDK_ROOT`，Yosys 与 PDK 由 wrapper 自动配置；缺工具链时重新运行安装脚本加 `--with-toolchain` 即可补齐。环境体检用 `ecc doctor`。

### 预编译 CLI 包（手动安装）

从 [GitHub Releases](https://github.com/openecos-projects/ecc/releases) 下载 `ecc-cli-linux-x86_64.tar.gz` 后解压到固定目录：

```bash
mkdir -p ~/.local/ecc
tar -xzf ecc-cli-linux-x86_64.tar.gz -C ~/.local/ecc
~/.local/ecc/ecc --version    # 自检
```

解压产物是 `ecc` 可执行文件 + `_internal/` 目录（PyInstaller 布局），**两者必须保持在一起**（不要把 `ecc` 单独拷到别处）。要在任意文件夹直接敲 `ecc`，把解压目录加入 `PATH`，任选其一：

```bash
# 方式 A：写入 shell 配置（bash 用 ~/.bashrc，zsh 用 ~/.zshrc）
echo 'export PATH="$HOME/.local/ecc:$PATH"' >> ~/.bashrc
source ~/.bashrc

# 方式 B：软链接到已在 PATH 的 ~/.local/bin（Ubuntu 默认含此目录）
mkdir -p ~/.local/bin
ln -snf ~/.local/ecc/ecc ~/.local/bin/ecc   # -n 已存在时覆盖

# 方式 C：系统级安装（多用户共享）
sudo tar -xzf ecc-cli-linux-x86_64.tar.gz -C /opt/ecc
sudo ln -s /opt/ecc/ecc /usr/local/bin/ecc
```

验证与升级：

```bash
which ecc && ecc --version          # 任意目录下应输出 ecc <版本号>
# 升级 = 用新包覆盖解压目录内容；方式 B/C 的软链接无需改动
```

> 本文面向 v0.1.0-alpha.12。更早版本不具备这里记载的完整命令面，包括内置 `ecc doc` 文档、`doctor`/`signoff`/`report` 命令组和全部 workspace/范围选择器。先用 `ecc --version` 确认版本；从当前源码树开发时，按 [development.cn.md](https://github.com/openecos-projects/ecc/blob/main/docs/development.cn.md#扩展-cli) 使用 `uv run ecc`。

> 注：`ecc` 的项目定位默认取当前目录（`ecc.toml` 所在处），所以「任意文件夹启动」是常态用法；在其他目录操作项目时加 `--project <dir>` 即可。

**目录默认值：** 在项目根目录可省略 `--project`；在受管 workspace 根目录，可省略
`--project` 和 `--workspace`，CLI 通过父级项目清单选中当前工作区的登记 ID，
不以目录 basename 替代登记名称。显式参数优先，项目根目录的多工作区选择仍需
`--workspace`。外部工作区请用 `--project` 指定归属；没有归属项目信息的独立
工作区可直接运行 `status` 等工作区命令，但项目级报告需要真实项目清单。
只自动识别根目录，不把任意项目子目录当工作区，也不全局搜索项目。

注意：`param`、`macro` 等同时支持项目和工作区作用域的命令，在工作区根目录默认
操作当前工作区；要操作项目级设置，请在项目根目录执行。`process` 的
`--workspace` 也可在工作区内省略，`cancel` 仍要求 `--run-id`。
创建、导入、删除、派生等生命周期操作的显式位置参数保持不变。

### 源码运行

```bash
# Nix（ecc 仓库内）
nix run . -- --help

# uv 开发环境（ecc 仓库内）
uv run ecc --help
```

## 1. 通用约定

- 全局：`ecc --version`（单行版本号）、`ecc --help`。
- 项目定位：项目级命令接受 `--project <dir>`（缺少参数指定即为当前目录）。`--workspace <路径指定>` 可以是受工具管理的非空简单文件夹路径，也可以是完整绝对路径。名称继续使用项目内的 `<project>/<workspace-id>` 布局；绝对路径创建或选择项目外 workspace，新路径默认以目录 basename 作为 workspace ID，已登记路径沿用清单中的 ID。新项目裸执行 `ecc run` 创建 `default`；只有一个活跃 workspace 时自动选择，多个活跃 workspace 时必须指定 `--workspace`。命名 workspace 会在创建文件前登记到 `project.json`。遗留的 `runs/` 项目必须先执行 `ecc migrate`。每个项目只有一个 `ecc.toml`；创建时会把声明的输入复制到各 workspace 的 `origin/`。
- 结构化输出：`init`、`check`、`run`、`status`、`log`、`config`、`migrate`、`doctor`、`rtl`、`param`、`macro`、`pdk`、`project`、`workspace`、`process`、`flow`、`signoff`、`report`、`compare`、`chipview`、`gdsview` 在相应命令中支持 `--plain`，缺省为人类可读 TEXT。`reproducible`、`sweep`、`explore`、`diagnose` 也支持 `--plain`；面向机器的实验命令默认仍输出 JSON。
- 退出码：成功 0；业务失败 1（错误记录形如 `[error] error=<机器可读错误码>`）。完整注册表：

| 退出码 | 含义 | 触发者 |
|---|---|---|
| 0 | 成功（含建议性检查返回 blocked/attention、`no_op` 的 run、空结果的只读查询） | 全部命令 |
| 1 | 业务失败：校验、状态或执行错误，stdout/stderr 带机器可读 error 记录 | 全部命令 |
| 2 | 用法错误：参数缺失/非法取值、`--plain` 与 `--json` 同时使用、未知 topic/profile/flow 名 | 全部命令 |
| 6 | 只读质量门禁的必需项失败 | `signoff check`、`sweep verify`、`diagnose run`、`reproducible verify` |
| 7 | 必需门禁因证据缺失/过期/不明确而无法评级 | `signoff check` |
| 20 | `workspace_busy`：目标 workspace 被占用且未传 `--no-wait` | 变更类命令 |
| 21 | `revision_conflict`：`--expected-revision` 与 manifest revision 不一致 | 带 `--expected-revision` 的命令 |
| 22 | `process_not_found`：登记的运行进程已失效且无存活进程持有 workspace 锁 | `ecc process` 组 |
| 23 | 契约不兼容（保留值：CLI 自身不发射，由 GUI 侧契约门禁在 runtime/CLI 契约不受支持时使用） | — |
| 124 | 超时：记录在 sweep 候选的 `exit_code` 中；有界经验优化或 campaign 超时时也作为命令退出码 | `sweep run` 结果、`experience optimize`、`experience campaign run` |
| 130 | 有界经验优化或 campaign 被取消 | `experience optimize`、`experience campaign run` |
- 步骤名（step token）有三套写法，按场景区分：
  - **展示名**（`ecc status` / `ecc log` / `ecc report step` 的输出与入参，统一小写/下划线）：`synthesis / lec / pre_floorplan / macro_placement / post_floorplan / placement / cts / legalization / timing_optimization / routing / filler / lvs / drc / postroutelec / rcx / sta / poweranalysis / harden`；
  - **持久化名**（`home/flow.json` 中的原始名；已有 workspace 上的 `--from`/`--only`/`--to` 必须用它，如 `place`、`CTS`、`Timing optimization`）：`Synthesis / lec / preFloorplan / macroPlacement / postFloorplan / place / CTS / legalization / Timing optimization / route / filler / lvs / drc / postRouteLec / RCX / sta / powerAnalysis / Harden`；
  - **新建范围时的别名**（首次 `--from A --to B` 建 workspace 会做别名归一化，两种拼法都接受）：如 `cts`↔`CTS`、`route`↔`routing`、`timingopt`↔`Timing optimization`、`postlec`↔`postRouteLec`。
  拼错时返回 `unknown_step` 并列出全部可用步骤名，照抄即可。

### 1.1 当前目录默认选择

#### 基本用法

```bash
cd /path/to/project
ecc report project
ecc status --workspace trial_a

cd /path/to/project/trial_a
ecc status
ecc log
ecc report step drc --section analysis
ecc report project --json
ecc report snapshot -o /path/to/comparisons/before.json
```

项目根目录执行时，所有已有 `--project` 选项仍默认当前目录。工作区根目录执行时，
具有 `--workspace` 选择器的命令默认选择当前工作区，同时识别其所属父级项目。
登记 ID 可与实际目录名不同，以 project.json 的路径匹配为准。

#### 优先级与边界

1. 显式 `--project` 与 `--workspace` 保留优先级，绝不替换显式工作区名称或路径。
2. 项目根目录中，不依据目录名猜工作区；保留一个活动工作区自动选择、多工作区
   需显式选择的既有行为。process 原来要求显式选择，只有在当前工作区中才默认。
3. 工作区根目录中，通过最近父级 project.json/ecc.toml 识别项目；受管工作区
   通过清单的完整路径匹配，未运行、缺少 flow 的已声明工作区同样可定位。
4. 工作区外部存放时，用 `--project /owner/project` 匹配当前目录与登记工作区。
   不遍历其他项目或维护全局项目搜索数据库。
5. 独立工作区存在 home/flow.json、home/params.toml、snapshot 或 legacy 参数标记
   时，可将当前完整路径用于 workspace-consuming 命令；无归属项目就不声称能
   生成项目级报告。只读命令不会自动登记工作区或创建项目。
6. 任意项目子目录不自动当工作区；本版不支持从工作区的 home/output 子目录向上
   猜测选择。需要显式参数或回到项目/工作区根目录。
7. 项目 metadata 损坏时明确失败，不通过推导选择绕过 manifest 校验。
8. 相对显式路径仍以进程当前目录为基准；推导项目不会改变 --output 等路径基准。

#### 作用域与安全

`param set/unset/apply/list/show/diff` 和 macro 等支持项目/工作区作用域的命令，
在工作区中省略 --workspace 等价于选中该工作区，不再意外操作项目级设置。
要操作项目级参数或 macro 设置，请在项目根目录执行相应命令。

`process inspect/cancel/reconcile` 的 --workspace 可在工作区中省略；cancel 的
--run-id 仍是必需的安全参数。显式绝对工作区路径解析为其登记 ID 后交给 process API。

workspace create/import/delete/derive/archive/reset-flow 等的显式位置参数不属于
可省略的 --workspace 选择器，保持不变；ecc init 的当前目录语义也保持不变。

#### 实现与验证契约

`resolve_current_location(project, workspace, workspace_supported=...)` 只读推导位置。
共享 invocation 的 `apply_location_defaults(input)` 返回类型相同的不可变 input，
将项目和工作区默认值同步交给 context 与 handler。param list 在推导后选择 renderer，
保证 workspace plain 输出仍为严格关联行记录，而不是误用静态 catalog 格式。

默认值重复应用保持幂等，不修改 manifest、workspace 状态、配置或文件。

命令总览：

```
$ ecc --help
Commands:
  version       Show ECC runtime, component, and installed tool versions
  doc           Show a bundled guide (config = config reference, ug = user guide, tutorial)
  gdsview       Open a workspace step's GDS in the KLayout viewer
  chipview       打开 workspace 指定 step 的 geometry 版图数据
  init          Create a new ECC project
  check         Validate the current project setup
  run           Run the configured RTL-to-GDS flow
  status        Show a quick run/step progress summary (full evidence: 'ecc report step')
  log           Show available logs or step log content
  config        Show resolved project or step configuration
  migrate       Migrate a legacy runs/ project to the manifest layout
  doctor        Check host environment: PDK, tools, and components
  rtl           Import project RTL sources
  param         Manage EDA parameters
  flow          Inspect available ECC flows
  macro         Manage manual macro placement (macro_location.tcl)
  pdk           Show and configure the PDK path used by this project
  project       Edit project declarations in ecc.toml
  process       Inspect, cancel, or reconcile ECC run processes
  workspace     Import or refresh managed workspaces
  signoff       Inspect and export signoff packages
  report        Generate design-summary, QoR score, checklist, step reports, and saved snapshots
  compare       Compare saved Engineering Snapshots without running EDA tools
  reproducible  Export and verify reproducible ECC evidence packages
  sweep         Run deterministic parameter sweeps
  explore       Rank and select sweep candidates
```

## 1.5. doc — 在终端阅读内置指南

`ecc doc` 将随包内置的 CLI 指南直接渲染到终端，因此在打包安装（无源码、无文档目录）的环境中也能离线查阅完整参考。

```bash
ecc doc config              # 完整配置参考（渲染输出）
ecc doc ug --lang cn        # 本指南的中文版
ecc doc config --plain      # 原始 markdown，逐字节输出
```

- 主题：`config`（配置参考）、`ug`（用户指南，即 user guide）、`tutorial`（教程）；`--lang` 选择 `en`（默认）或 `cn`。
- 终端下渲染输出带高亮并进入分页器翻阅（`$PAGER`，回退到 `less`/`more`；未设置 `LESS` 时默认 `LESS=FRX`，保证 `less` 下颜色生效）；管道场景全量直出、不带颜色。
- 非法的主题/语言取值由参数校验拒绝（退出码 2）。
- 管道输出保留 unicode 渲染版式；`--plain` 原样输出原始 markdown，适合脚本处理。

## 1.6. Shell 补全

`ecc` 内置 bash、zsh、fish、powershell 的 Shell 补全。打印激活脚本并加载到当前会话：

```bash
eval "$(ecc --show-completion)"     # 自动探测当前 shell
```

- 把该行写入 `~/.zshrc` / `~/.bashrc`（或 home-manager 的 `initExtra`）即可永久启用。zsh 需要先初始化 `compinit`。
- 在 NixOS 等声明式管理的环境中，请用上面的 `eval` 方式而不是 `--install-completion`：后者会原地改写 `~/.zshrc` / `~/.bashrc`，对只读 rc 符号链接会失败，且与 home-manager 冲突。

## 1.7. 命令总索引

全部命令与子命令一览（语义、选项与样例见对应章节；`--project`/`--workspace`/`--plain`/`--json` 等公共选择器约定见 §1 与 §1.1）：

| 命令 | 用途 | 章节 |
|---|---|---|
| `ecc version` | 查看运行时、组件与工具版本（`--json` 输出机器可读契约） | §2 |
| `ecc doc TOPIC` | 终端阅读内置指南（`config` / `ug` / `tutorial`） | §1.5 |
| `ecc gdsview` | 在 KLayout 中打开 workspace step 的 GDS | §13 |
| `ecc chipview` | 打开 workspace step 的 geometry snapshot | §14 |
| `ecc init NAME` | 创建项目骨架 | §3 |
| `ecc check` | 校验项目配置、RTL 源与 PDK 内容 | §4 |
| `ecc run` | 执行 flow（新建/续跑/范围/单步，项目与 workspace 模式） | §5 |
| `ecc status` | run 与步骤进度速查 | §6 |
| `ecc log [STEP]` | 列出或查看日志 | §7 |
| `ecc config [STEP]` | 查看解析后的项目/步骤配置 | §8 |
| `ecc migrate` | legacy `runs/` 布局迁移 | §5.4 |
| `ecc doctor` | 环境体检（9 项组件） | §4 |
| `ecc rtl import` | 把 RTL/filelist 导入项目 `rtl/` | §8.5 |
| `ecc param apply / list / show / set / unset / diff` | 参数管理（项目/工作区双作用域） | §9 |
| `ecc flow list / show / validate` | 查看与校验已注册 flow | §8.6 |
| `ecc macro set / remove / import / show` | 手工宏单元摆放 | §9.5 |
| `ecc pdk set-root / show / verify / unset` | PDK 路径配置与内容校验 | §10 |
| `ecc project apply / baseline / reconcile / set / unset / add / remove / show / doctor` | 编辑 `ecc.toml` 声明、选 QoR 基线、清单健康检查 | §8.5 |
| `ecc process inspect / cancel / reconcile` | 运行进程的查看/取消/恢复 | §6.5 |
| `ecc workspace create / import / derive / archive / delete / reset-flow / refresh / reconcile-deletes` | workspace 生命周期管理 | §8.5 |
| `ecc signoff inspect / check / export` | 签核就绪度、质量门禁、导出签核包 | §11 |
| `ecc report summary / qor / checklist / step / snapshot / project` | 设计总结、QoR 计分、清单、单步证据、快照、项目矩阵 | §12 |
| `ecc compare run` | 比较两份 Engineering Snapshot | §12.6 |
| `ecc reproducible export / inspect / verify / report` | 可复现证据包的导出/查看/校验/汇总 | §11.5 |
| `ecc sweep create / show / list / run / compare / verify` | 确定性参数扫描 | §11.5 |
| `ecc explore rank / export / promote` | 候选排序、导出与提升 | §11.5 |
| `ecc diagnose run` | 工作区诊断与恢复建议 | §11.5 |
| `ecc experience` | 案例采集、串行 campaign、受限推荐/优化、release 与经验包交换 | [经验测试手册](../../ecc_experience/docs/ecc-experience-testing-guide.cn.md#串行-baseline-批次) |

## 2. version — 查看版本

```bash
ecc version           # 文本
ecc version --json    # 版本与 CLI 契约的 JSON
ecc --version         # 仅一行 ecc 版本
```

前四行是捆绑组件元数据（Python 包版本）。`yosys` / `sizer` / `klayout`
三行按流程运行时相同的方式从当前环境解析，显示工具二进制自身的版本；
工具缺失时显示 `not installed`，无法查询版本时显示 `unknown`。

```console
$ ecc version
ecc 0.1.0a12
dreamplace 0.1.0a7
ecc_tools 0.1.0a13
runtime ECC CLI
yosys 0.69+24
sizer 0.1.0-alpha
klayout 0.30.2
```

`--json` 输出机器可读契约：`schema_version` 是该 JSON 的版本，`cli_contract` 是 CLI 命令面/退出码契约的版本号（ECOS Studio 用它与 `runtime` 字段判定 runtime 兼容性），`tools` 是按 flow 运行时相同方式从当前环境解析的工具版本：

```console
$ ecc version --json
{"schema_version": 2, "runtime": "ECC CLI", "ecc": "0.1.0a12", "dreamplace": "0.1.0a7", "ecc_tools": "0.1.0a13", "cli_contract": 1, "tools": {"yosys": "0.69+24", "sizer": "0.1.0-alpha", "klayout": "0.30.2"}}
```

## 3. init — 创建项目

```bash
ecc init <NAME> [--project-name TEXT] [--design-name TEXT] [--plain]
# ECOS Studio 资源登记（可选，写入生成的 manifest）：
#   --mpc-resource-id / --mpc-display-name / --mpc-version / --mpc-root / --mpc-design-index
```

在 `NAME/` 下生成 `ecc.toml`、`rtl/`、`constraints/` 骨架（workspace 由首个 `ecc run` 创建）：

```console
$ ecc init gcd
[init]
  project: gcd
  status: created
  path: gcd
  check: ecc check --project gcd
  run: ecc run --project gcd
```

生成的 `ecc.toml`（后续按需修改 `design.*` 与 `pdk.root`）：

```toml
[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/gcd.v"]      # 一个或多个 Verilog 源文件，也可指向一个 filelist（如 rtl/filelist.f）
# 非 RTL 范围可按需声明入口输入：
# netlist = "inputs/gcd.v"
# golden_netlist = "inputs/gcd-golden.v"
# def = "inputs/gcd.def"
# sdc = "constraints/gcd.sdc"
# spef = "inputs/gcd.spef"
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"           # 目前支持 ics55
root = ""                # icsprout55-pdk 路径；留空则用 CHIPCOMPILER_ICS55_PDK_ROOT / ICS55_PDK_ROOT 环境变量

[flow]
# preset: rtl2gds | syn_sta | synthesis_lec
preset = "rtl2gds"
# LEC is skipped by default; clear the list to enable it.
skip_steps = ["lec"]
```

## 4. check — 校验项目配置

```bash
ecc check [--project DIR] [--workspace NAME] [--plain]
```

校验 `ecc.toml` 必填项（design/pdk/flow）、PDK 名称与内容（tech LEF/LEF/liberty），并逐一校验每个声明的 RTL 源文件（源文件缺失即失败）。指定 `--workspace NAME` 时改为按该 workspace 解析出的有效配置校验（应用 manifest 回退与入口层范围），而不是裸项目：

```console
$ ecc check        # PDK 未就绪时
[check]
  fail pdk.root is required
  inspect: ecc check
rc=1

$ ecc check        # 全部就绪后
[check]
  project: gcd
  status: checked
  config: ecc.toml
  inspect: ecc status
  run: ecc run
  rtl: pass
    path: rtl/gcd.v
  inspect: ecc check
rc=0
```

### 环境自检：ecc doctor

`ecc doctor` 一条命令体检全部依赖，共 9 项组件（PDK、yosys、yosys-slang、随包捆绑的 ecc-tools/dreamplace、必需的 Sizer、LEC 等价性检查所需的 kepler-formal 与 lec-dual 双引擎预检，以及可选的 KLayout），每项给出 pass/fail 与修复建议；只有**必需项**失败才返回非零：

```bash
ecc doctor [--project DIR] [--plain|--json]
```

```console
$ ecc doctor          # 在项目目录内执行（PDK 探测需要 ecc.toml 或 --project）
[status]
  doctor: environment
  status: attention          # ok=全过 / attention=仅可选项失败(rc=0) / failed=必需项失败(rc=1)
  checked: 9
  failed: 0                  # failed 只统计必需项失败；可选项失败计入 attention
  attention: 1
  run: ecc run
  component: yosys
  status: pass
  detail: ~/.local/oss-cad-suite/bin/yosys
  component: yosys-slang
  status: pass
  detail: read_slang frontend available
  component: ecc-tools       # 其余组件同理：dreamplace / sizer / kepler-formal /
                             # lec-dual / pdk（必需）；klayout（可选）
  ...
```

- `kepler-formal`（必需）：LEC/postRouteLec 等价性检查工具。先按 `CHIPCOMPILER_KEPLER_FORMAL_ROOT` 解析（根级 `kepler-formal` wrapper 或 `bin/kepler-formal`），再回退 PATH。
- `lec-dual`（必需）：双引擎 LEC 预检，分别探测两个物理引擎。允许降级运行——缺一个引擎仍为 pass（detail 注明 `degraded`，该步骤只跑可用引擎、结果保持非 proven）；两个都缺才 fail。
- `klayout`（可选）：其 Python 模块用于兼容旧版 flow 缩略图，GUI 可执行文件
  由 `gdsview` 使用；可通过 `KLAYOUT_BIN` 显式指定，否则从 `PATH` 查找。

`--json` 输出记录数组：首条为汇总，其后每组件一条，字段含 `component`、`status`、`required`、`detail`：

```console
$ ecc doctor --json
[
  {
    "doctor": "environment",
    "status": "ok",
    "checked": 9,
    "failed": 0,
    "attention": 0,
    "run": "ecc run"
  },
  {
    "component": "yosys",
    "status": "pass",
    "required": true,
    "detail": "~/.local/oss-cad-suite/bin/yosys"
  },
  ...
]
```

此外，对新建或 `--overwrite` 的目标，`ecc run` 会按目标 flow 实际步骤的工具映射预检组件（被 `skip_steps` 跳过的步骤不探测其工具）：所有 flow 预检捆绑 ecc-tools；含综合预检 Yosys；含布局/合法化预检 DreamPlace；含 Timing optimization 预检 Sizer（包括 `rtl2gds`）；未跳过 LEC 的目标还会预检 kepler-formal 与 lec-dual。这些组件缺失时会以 `env_not_ready` fail-fast：

```console
$ ecc run
[error]
  env_not_ready
  reason: yosys: Yosys executable not found. ...
  preset: rtl2gds
  doctor: ecc doctor
rc=1
```

补充说明：

- PDK 根目录解析优先级：`ecc.toml` 的 `pdk.root` > 环境变量 `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT` > 仓库默认 `<ecc 检出目录>/../pdk/icsprout55-pdk`（ecos-studio workspace 布局；数据层与 `ecc pdk show` 使用。`ecc check`/`ecc run` 仍要求前三者之一，未设置时报 `pdk.root is required`）。
- 综合步骤内部仍有 slang fail-fast（日志报 `yosys slang frontend check failed`），事后排查用 `ecc log synthesis`。
- 重装/补齐工具链：重新运行第 0 节的安装脚本（加 `--with-toolchain`）。

### 手动排查清单（无 doctor 时备用）

`ecc check` 只覆盖「项目配置（design/pdk/flow 必填项）+ **PDK 内容**（tech LEF / LEF / liberty）+ 每个声明的 RTL 源文件」，**不检查外部工具**。手动逐项确认：

| 依赖 | 检查命令 | 就绪标志 |
|---|---|---|
| Python 组件（ecc-tools / dreamplace，随 CLI 捆绑） | `ecc version` | `ecc_tools` / `dreamplace` 显示版本号而非 `unknown` |
| PDK（ics55） | `ecc check` | `status: checked`；liberty 缺失时按 README 执行 `make unzip` |
| Yosys（综合） | `which yosys && yosys -V`，或 `echo $CHIPCOMPILER_OSS_CAD_DIR` | 二者其一可用（优先 `CHIPCOMPILER_OSS_CAD_DIR` 指向 OSS CAD Suite） |
| Yosys slang 前端 | `yosys -Q -T -p "help read_slang"` | 输出**不含** `No such command`（yosys ≥ v0.67 内置；旧版需可加载的 slang 插件） |
| KLayout GUI（仅 `gdsview` 需要） | `KLAYOUT_BIN=/path/to/klayout ecc gdsview --help` 或 `command -v klayout` | 可执行文件可解析；需在桌面会话中运行 |
| Sizer（`ecc doctor` 的必需组件；完整 rtl2gds 链的 Timing optimization 步骤需要） | `which Sizer`；可选 `echo $CHIPCOMPILER_ECC_SIZER_ROOT` | 可执行文件和含 `src/sizer_os.tcl` 的 root 均须可解析；root 可显式设置，或由二进制位置自动发现。新建或 `--overwrite` 的 `rtl2gds` 会在预检检查 Sizer；已有 workspace 或 `--workspace` 重跑不预检，缺失时仍可能在流中段失败 |
| kepler-formal（`ecc doctor` 的必需组件；LEC/postRouteLec 等价性检查需要，默认 `skip_steps = ["lec"]` 时不预检） | `echo $CHIPCOMPILER_KEPLER_FORMAL_ROOT`；`which kepler-formal` | 二者其一可解析出可执行文件（root 下根级 wrapper 或 `bin/kepler-formal`） |

可整体复制的一段自检脚本：

```bash
ecc version                                                     # ① Python 组件
ecc check                                                       # ② 配置 + RTL + PDK
which yosys >/dev/null || [ -x "$CHIPCOMPILER_OSS_CAD_DIR/bin/yosys" ] \
  && echo "yosys: OK" || echo "yosys: 缺失（装 OSS CAD Suite 并 export CHIPCOMPILER_OSS_CAD_DIR）"
yosys -Q -T -p "help read_slang" 2>&1 | grep -q "No such command" \
  && echo "slang 前端: 缺失（需 yosys >= v0.67 或可用的 slang 插件）" \
  || echo "slang 前端: OK"
```

说明：

- PDK 根目录解析优先级：`ecc.toml` 的 `pdk.root` > 环境变量 `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT` > 仓库默认 `<ecc 检出目录>/../pdk/icsprout55-pdk`（`ecc check`/`ecc run` 仍要求前三者之一）。
- ECC-Tools / DreamPlace 以 Python wheel（`ecc-tools-bin`、`ecc-dreamplace`）形式捆绑在 CLI 包内，正常安装即就绪。

## 5. run — 执行 flow

### 5.1 项目模式（常规）

```bash
ecc run [OPTIONS]
  --project TEXT     项目目录（缺省 cwd）
  --workspace TEXT   创建、选择或续跑 workspace 名称或绝对路径
  --resume           从第一个非成功步骤继续
  --from TEXT        从一个步骤重跑，或与 --to 配对创建范围 workspace
  --to TEXT          有界范围的包含式终点（必须与 --from 同用）
  --only TEXT        只运行一个已持久化步骤
  --force            强制重跑已成功的 --only 步骤
  --preset TEXT      本次运行的 flow preset 覆盖（不写回 ecc.toml），如 --preset syn_sta
  --overwrite        覆盖已存在的 workspace（仅删除真正的 ECC workspace 目录，含安全校验）
  --set KEY=VALUE    参数覆盖，可重复（如 --set place.target_density=0.65），会记录到 run 的 provenance
  --plain           面向脚本的 key=value 输出
```

自动化选项（供 ECOS Studio 与 CI 驱动使用，交互式使用可忽略）：`--expected-revision N`
在 workspace revision 已变化时报 `revision_conflict`（退出码 21）；`--command-id TEXT`
为变更打上幂等/审计标记；`--no-wait` 在 workspace 忙时不等待（直接报错）；
`--run-id`/`--runtime-id` 命名登记的运行进程；`--log-file PATH` 在预检前以受限权限
创建运行日志并把整个 run 的 stdout/stderr 重定向进去。这些选项同样出现在其他变更类
命令上（`param apply`、`macro import`、`workspace …`、`signoff export`）。以这种方式
登记的 run 用 `ecc process` 控制（§6.5）。

新建或 `--overwrite` 的 workspace 会按以下流程执行：读 `ecc.toml` → 只解析入口步骤所需的设计文件以及 PDK/参数 → 预检所需工具 → 先写入 `project.json` 登记 → `--workspace` 是名称时默认在 `<project>/<workspace 名称>` 创建，是绝对路径时在该完整目录创建 → 将声明的设计输入复制到 `origin/`、写入对应步骤配置并运行 flow。绝对路径必须是完整的项目外目录且父目录已存在；新路径以 basename 作为 workspace ID，已登记路径沿用清单中的 ID。外部目录中已有有效 ECC workspace 时，也可以用同一命令登记并续跑。workspace 不会存放第二份项目输入清单。已有 workspace 按持久化 flow 续跑，不会改写已有输入或步骤配置。`rtl2gds` 是完整 18 步链（Synthesis→LEC（默认 kepler-formal 等价性检查；默认跳过——`[flow] skip_steps` 默认为 `["lec"]`，设为 `[]` 才启用）→preFloorplan→macroPlacement→postFloorplan→place→CTS→legalization→Timing optimization（sizer）→route→filler→LVS→DRC→postRouteLec（kepler-formal 等价性检查）→RCX→sta→powerAnalysis→Harden，Harden 产出 GDS + Abstract LEF + 时序 LIB）。

#### 外部 workspace 路径

当 workspace 必须放在项目目录外时，把完整绝对目录直接作为 `--workspace` 的路径参数。它表示 workspace 的完整目录，不是父目录：

```bash
# 原有行为：在项目下创建并登记 workspace。
ecc run --project /projects/gcd --workspace <project-local-path>

# 在项目外创建并运行受工具管理的 workspace。
ecc run --project /projects/gcd \
  --workspace /data/ecc-runs/gcd/archive

# 登记后按清单中的 ID 选择外部 workspace。
ecc run --project /projects/gcd --workspace archive --resume
ecc status --project /projects/gcd --workspace archive
```

路径必须是绝对路径。`ecc` 只创建最后一级目录，因此父目录必须已存在；已有非空目录必须已经是有效 ECC workspace。项目根目录和 legacy `runs/` 目录是受项目保护目录，包含项目目录的路径也会被拒绝。同一个 workspace ID 不能重新绑定到另一个路径，已登记给其他 ID 的路径也不能重复使用。要登记已有 workspace 但不执行或修改它，请使用 `ecc workspace import`。

`synthesis_lec` preset 需要默认策略跳过的 LEC，因此本示例的项目先编辑 `ecc.toml`（`sed -i 's/skip_steps = \["lec"\]/skip_steps = []/' ecc.toml` 或手动修改）显式设置 `skip_steps = []`：

```console
$ ecc run --preset synthesis_lec
[workspace]
  workspace id: default
  status: success
  workspace: /tmp/gcd/default
  inspect: ecc status --workspace default
  log: ecc log --workspace default

$ ecc run --workspace default          # 已全部成功时再跑一次 → 无事可做（no_op）
[workspace]
  workspace id: default
  status: success
  workspace: /tmp/gcd/default
  inspect: ecc status --workspace default
  log: ecc log --workspace default
```

run 汇总记录会带 `no_op: true`（`--plain` 输出可见；用 `--resume`/`--only` 等选择器时还会带 `executed_steps` 列表）。若 `ecc.toml` 与 `project.json` 记录的基线值实际不一致（如 `pdk.root` 解析到了与首次运行记录不同的 PDK，或 `flow.preset` 与 workspace 声明的范围不一致），汇总块前会多一行 `warning: ...` 提示（`config_layer_diverged`），不影响执行结果。

**已有 workspace 的目标对齐（reconcile）**：再次 `ecc run` 时，CLI 会把 workspace 已持久化的 flow 与当前目标（`ecc.toml` 的 `flow.preset`，或 `project.json` 中该 workspace 声明的 start/end 范围）对齐：

- 已持久化步骤是目标的**前缀**且未跑完 → 续跑，必要时**自动扩展**到目标终点（例如先用 `--preset synthesis_lec` 建的 workspace，`ecc.toml` 是 `rtl2gds`，再裸跑 `ecc run` 会从当前进度继续把物理流程跑完）；
- 已持久化范围 ⊇ 目标且全部成功 → `no_op`（默认 resume 不会越过目标终点重跑更宽的账本）；
- 目标与持久化 flow **分叉**（既非前缀也非超集）→ `flow_mismatch`，按提示 `--overwrite` 重建或换新的 `--workspace`。

参数与选择器的边界：

- `--set KEY=VALUE` 只在**新建** workspace 时生效并记录到 `home/cli-param-overrides.json`；对已有 workspace 使用会报 `set_requires_fresh_run`（提示改用 `--overwrite` 或新 `--workspace`）；
- `ecc.toml` 的 `[params.*]` 对已有 workspace 同样不再生效（workspace 复用创建时的 `home/params.toml`），此时会附 `params_ignored_on_existing_run` 警告；
- `--preset` 只影响本次调用的目标，**不写回** `ecc.toml`：

```console
$ ecc run --preset bogus  # 非法 preset（不修改 ecc.toml）
[error]
  unsupported_preset
  preset: bogus
  presets: rtl2gds, syn_sta, synthesis_lec
  inspect: ecc config
rc=1
```

典型用法：

```bash
ecc run                                        # 创建 default；已有唯一活跃 workspace 时自动选择并续跑
ecc run --workspace baseline --preset rtl2gds  # 创建命名的完整流程 workspace
ecc run --workspace syn-only --preset syn_sta  # 只做综合的单步 workspace
ecc run --workspace cts-only --from cts --to cts      # 新建范围 workspace（别名写法 OK）
ecc run --workspace cts-route --from cts --to routing # 同上；两端都接受别名
```

新建范围 workspace 时只校验**入口步骤**所需的设计输入：Synthesis 要 `rtl`；LEC/postRouteLec 要 `netlist` + `golden_netlist`；preFloorplan 要 `netlist`；macroPlacement、postFloorplan 和其余物理步骤（place/CTS/legalization/timing optimization/route/filler/rcx/drc/lvs/harden）要 `def` + `netlist`；sta 还要 `spef`；`sdc` 声明了才校验。缺输入时按 `step_input_missing` 报错：

```console
$ ecc run --from cts --to route          # 新建范围但缺 def/netlist
[error]
  step_input_missing step_input_missing: cts requires design.def
  step_input_missing step_input_missing: cts requires design.netlist
rc=1
```

例如，要复用已有 workspace `2` 的 post-floorplan 产物，新建一个只跑 placement 到 routing 的 workspace，先把**匹配的一对** DEF 和门级网表声明为新 workspace 的入口输入，再创建范围 flow：

```bash
PROJECT=~/projects/benchmark/gcd
SOURCE="$PROJECT/2/postFloorplan_ecc/output"

ecc project set design.def "$SOURCE/gcd_postFloorplan.def.gz" --project "$PROJECT"
ecc project set design.netlist "$SOURCE/gcd_postFloorplan.v.gz" --project "$PROJECT"
ecc run --project "$PROJECT" --workspace floorplan-2-place-route \
  --from placement --to routing
```

`ecc run` 不提供 `--def` 或 `--netlist` 选项；范围入口从 `ecc.toml` 的 `design.def` / `design.netlist` 读取。这个例子会在 `project.json` 中登记 `floorplan-2-place-route`，将两个文件复制到新 workspace 的 `origin/`，并从 placement 开始执行至 routing（不重跑 postFloorplan）。由于前两条命令会改动项目级 `ecc.toml`，它们也影响之后新建的 workspace；若原先未声明这些字段，可在创建完成后用 `ecc project unset design.def --project "$PROJECT"` 和 `ecc project unset design.netlist --project "$PROJECT"` 恢复项目默认入口。

### 5.2 workspace 模式（调试/复跑）

```bash
ecc run [--workspace NAME] [--resume | --from STEP [--to STEP] | --only STEP [--force]]
```

- `--resume`：从第一个非成功的步骤继续（不给选择器时的默认行为）；
- `--from STEP`：已有 workspace 时从该步起重跑其后缀；与 `--to STEP` 配对可运行已有 flow 的包含式范围；
- 新 workspace 必须同时给出 `--from` 与 `--to`，动态构建这段包含式 flow；
- `--only STEP [--force]`：只跑一步，`--force` 用于该步已成功时强制重跑；
- `--resume`、`--only` 与范围选择互斥；新建范围不能与 `--preset`、`--resume`、`--only`、`--force`、`--overwrite` 组合；`--workspace` 可与 `--project` 组合；
- `--workspace` 可以是单段名称或绝对路径。绝对路径用于创建或登记项目外目标；登记后所有按 workspace 作用域的命令都可以使用清单中的 ID；
- **已有 workspace 上的 `--from`/`--only`/`--to` 必须用持久化名**（`home/flow.json` 中的原始名，见第 1 节词表，如 `place`、`CTS`、`Timing optimization`）；新建范围（`--from A --to B` 同时给出）才接受小写别名。拼错时报 `unknown_step` 并列出全部可用名：

```console
$ ecc run --workspace default --from synthesis   # 持久化名是 "Synthesis"
[error]
  unknown_step unknown step 'synthesis'; available steps: Synthesis, lec, preFloorplan,
  macroPlacement, postFloorplan, place, CTS, legalization, Timing optimization, route, filler, lvs, drc,
  postRouteLec, RCX, sta, powerAnalysis, Harden
  workspace: /tmp/gcd/default
```

- 原地修改 workspace：被重跑步骤的 `output/` 会被替换，下游步骤标记为 `Unstart`（输出文件保留，等后续运行）。某步的子目录从未创建过（如工具缺失导致 `Incomplete`）时，选择器会拒绝执行并报 `step_unavailable`。

```bash
ecc run --workspace default --resume               # 从第一个非成功步骤继续
ecc run --workspace default --from CTS --to route  # 重跑一个包含式范围
ecc run --workspace default --only place           # 只跑一步（已成功则 no_op）
ecc run --workspace default --only place --force   # 已成功也强制重跑这一步
ecc run --workspace default --from Synthesis       # 从头重跑整个持久化后缀
```

误用选择器会得到明确报错（均 rc=1）：

```console
$ ecc run --resume            # 项目里还没有任何 workspace
[error]
  selector_requires_workspace

$ ecc run --to route          # --to 不能脱离 --from 单独出现
[error]
  flow_range_requires_pair

$ ecc run --from cts          # 新建目标上 --from 必须与 --to 配对
[error]
  flow_range_requires_pair

$ ecc run --force             # --force 只属于 --only
[error]
  force_requires_only

$ ecc run --from cts --to route --preset rtl2gds   # 新建范围与其他选择器互斥
[error]
  selector_conflict

$ ecc run --workspace a/b     # 相对路径非法；应使用单段名称或完整绝对路径
[error]
  invalid_workspace invalid_workspace: 'a/b' is not a single workspace name
```

### 5.3 run 错误码速查

| 错误码 | 触发场景 | 处理 |
|---|---|---|
| `run_exists` | 目标目录已存在但不是有效 ECC workspace（无 `home/flow.json`） | `--overwrite`（有安全校验）或换 `--workspace` |
| `overwrite_refused` | `--overwrite` 的目标不是真正的 ECC workspace 目录 | 人工确认目录内容后手动清理 |
| `invalid_workspace` | workspace 名含 `/`、是相对路径或 `.`/`..`；或目录不是可加载的 workspace | 使用简单名称（如 myproject）或完整绝对路径 / 检查目录（如 /home/user/myproject） |
| `workspace_required` | 项目有多个活跃 workspace 但没传 `--workspace` | 按报错列出的名称指定其一 |
| `workspace_not_declared` | `--workspace` 名与 `project.json` 声明的 id 不一致（含别名指向已声明路径） | 使用报错中给出的已声明 id |
| `workspace_path_not_absolute` | 导入路径不是绝对路径 | 为 `workspace import` 传入绝对 workspace 目录 |
| `workspace_path_unsafe` | 路径是项目根目录、legacy `runs/` 目录、包含项目目录，或父目录不存在 | 选择安全目录，并确保父目录已存在 |
| `workspace_id_conflict` | workspace ID 已登记在另一个路径 | 使用已登记的 ID/路径，或更换目录 basename |
| `workspace_path_conflict` | 规范化后的路径已登记给另一个 workspace ID | 使用已登记 ID 或更换目录 |
| `workspace_not_importable` | 目录不是受支持的 ECC workspace，或其 design/PDK 身份与项目不匹配 | 指向该项目的有效 workspace |
| `workspace_conflict` | 同名 workspace 已声明在另一个路径 | 换名称 |
| `workspace_registration_failed` | 向 `project.json` 登记新 workspace 失败（清单不可写等） | 检查 `project.json` 可读写后重试 |
| `legacy_workspace_migration_required` | 在 legacy `runs/` 项目上执行 `ecc run` | 先 `ecc migrate`（提示记录会给出完整命令） |
| `selector_requires_workspace` | 全新项目上直接用 `--resume`/`--only` | 先跑一次 `ecc run` |
| `selector_conflict` | `--resume`/`--from`/`--only` 组合使用，或新建范围搭配 `--preset` 等 | 只保留一个选择器 |
| `flow_range_requires_pair` | `--to` 单独出现；或新建目标上 `--from` 无 `--to` | 补齐配对参数 |
| `force_requires_only` | `--force` 未搭配 `--only` | 加 `--only STEP` |
| `unsupported_preset` | `--preset` 不在受支持列表 | 从报错中的 `presets:` 选择 |
| `step_input_missing` | 新建目标的入口步骤缺 `rtl`/`netlist`/`def`/`spef` 等输入 | 在 `ecc.toml` 补齐对应 `[design]` 字段 |
| `unknown_step` | 选择器步骤名不在持久化 flow 里 | 照抄报错列出的可用步骤名 |
| `step_unavailable` | 选择的步骤在 workspace 中没有可用子目录（此前创建失败） | 先修复环境（`ecc doctor`）后 `--overwrite` 重建 |
| `flow_mismatch` | 目标 flow 与 workspace 持久化 flow 分叉 | `--overwrite` 重建，或新 `--workspace` |
| `set_requires_fresh_run` | 对已有 workspace 用 `--set` | `--overwrite` 或新 `--workspace` |
| `env_not_ready` | 新建/`--overwrite` 目标预检发现必需工具缺失 | 按 `ecc doctor` 输出补齐 |
| `step_input_missing` 之外的 `config_error` | `ecc.toml`/清单参数校验失败 | `ecc check` 查看具体字段 |

### 5.4 migrate — 旧布局迁移（过渡期命令）

```bash
ecc migrate [--project DIR] [--yes] [--plain]
```

把 legacy `runs/` 布局项目迁移到 manifest 布局：每个安全的 `runs/<id>` workspace 都会移动到 `<project>/<id>`，重写 workspace 内部路径，并登记到新建或更新的 `project.json`。缺省先输出迁移计划，确认后才执行；`--yes` 跳过确认。该命令为过渡期保留（代码标注 deprecated），存量项目迁完即可弃用。`run`/`check`/`status` 在 legacy 项目上会自动附带迁移提示记录。

## 6. status — 查看 run 与步骤状态

```bash
ecc status [--project DIR] [--workspace NAME] [--plain|--json]
```

`status` 是轻量进度速查；完整的分步证据报告用 `ecc report step`（§12.4）。
`--workspace` 是已存在的受管 workspace 名称，可与 `--project` 组合。`--json`
以 JSON 记录数组输出各步骤记录。

```console
$ ecc status
[status]
  workspace id: default
  status: failed
  workspace: /tmp/gcd/default
  inspect: ecc status --workspace default
  log: ecc log --workspace default

  steps:
    synthesis (yosys) success 0:0:17
      log: ecc log synthesis --workspace default
    lec (kepler_formal) success 0:0:1
      log: ecc log lec --workspace default
    pre_floorplan (ecc) success 0:0:1
      log: ecc log pre_floorplan --workspace default
    macro_placement (dreamplace) success 0:0:5
      log: ecc log macro_placement --workspace default
    post_floorplan (ecc) success 0:0:1
      log: ecc log post_floorplan --workspace default
    placement (dreamplace) incomplete
      log: ecc log placement --workspace default
    cts (ecc) unstart
      log: ecc log cts --workspace default
    ...

$ ecc status --plain
workspace_id=default status=failed workspace=/tmp/gcd/default inspect_cmd="ecc status --workspace default" log_cmd="ecc log --workspace default"
step=synthesis tool=yosys status=success runtime=0:0:17 log_cmd="ecc log synthesis --workspace default"
step=lec tool=kepler_formal status=success runtime=0:0:1 log_cmd="ecc log lec --workspace default"
...
```

run 级状态取全部步骤的聚合：`success / partial / failed / ongoing / unstart`（flow.json 缺失/损坏时为 `missing / corrupt`；`partial` 表示范围重跑后成功与未开始步骤并存）；步骤级状态为 `success / incomplete / unstart / ongoing / pending / invalid`。新 workspace 还可能在 step 记录中包含 `checklist_status`、`checklist_blocked` 和 `checklist_failed_items`；旧 workspace 没有这些字段时保持原输出。综合级 LEC 未证明时步骤失败并终止流程。

## 6.5. process — 查看、取消或恢复运行进程

以自动化选项（`--run-id`、`--no-wait`、`--log-file`；见 §5.1）启动的 run 会把自身登记
到项目 manifest，detached 或崩溃的 run 因此始终可观测：

```bash
ecc process inspect [--run-id ID] [--project DIR] [--workspace NAME] [--plain]
ecc process cancel --run-id ID [--force] [--project DIR] [--workspace NAME] [--plain]
ecc process reconcile [--run-id ID] [--no-wait] [--project DIR] [--workspace NAME] [--plain]
```

- `inspect` 报告所选 workspace（或某个 `--run-id`）的存活运行进程条目：run id、runtime id、
  pid 和日志路径；登记的身份已失效且没有存活进程持有 workspace 锁时报 `process_not_found`。
- `cancel` 请求取消登记的 run：默认发送经 pid 校验的优雅取消信号，在下一个步骤边界生效；
  `--force` 向 run 的整个进程组发送 SIGTERM（run 必须仍拥有独立进程组，否则报
  `process_identity_changed`）。
- `reconcile` 在 run 崩溃或被杀后修复持久化 flow：把没有终态的步骤恢复到一致状态并清除
  过期的登记条目；记录列出 `recovered_steps`。当 `workspace_busy` 或进程过期报错已不符合
  现实时使用它。

三个子命令都接受标准 `--project`/`--workspace` 选择器；reconcile 的 `--no-wait` 在 manifest
锁被占时不等待（直接报 `workspace_busy`）。

```console
$ ecc process inspect --workspace trial     # 没有登记的运行进程时
[error]
  process_not_found No runtime process is registered
rc=22
```

## 7. log — 查看日志

```bash
ecc log [STEP] [--project DIR] [--workspace NAME] [--plain]
```

不带 STEP 列出全部日志文件（run 级 flow 日志 + 各步骤日志，含尾部预览）；带 STEP 打印该步骤日志内容（TEXT 模式高亮 ERROR/WARNING 行）。STEP 接受展示名（`synthesis`）与持久化名（`Synthesis`）两种写法；步骤尚未运行（日志不存在）时报 `log status: missing`，名字拼错报 `unknown_step`。

```console
$ ecc log
[logs]
  run  log/gcd.2026-09-03_17-34-35
    tail:
      flow : /path/gcd/default/home/flow.json
      name | tool | state | runtime
      Synthesis | yosys | Success | 0:0:15
  inspect: ecc log --workspace default
  synthesis  Synthesis_yosys/log/Synthesis.log
    tail:
      synthesizing gcd...
  inspect: ecc log synthesis --workspace default

$ ecc log synthesis
[log] step=synthesis
  source: Synthesis_yosys/log/Synthesis.log
        synthesizing gcd...
  inspect: ecc log synthesis --workspace default

$ ecc log nosuchstep
[error]
  error
  step: nosuchstep
  status: unknown_step
  inspect: ecc status --workspace default
rc=1
```

## 8. config — 查看解析后的配置

```bash
ecc config [STEP] [--project DIR] [--workspace NAME] [--plain|--json]
```

`--workspace` 将步骤视图限定到指定的受管 workspace；项目级视图仍以项目为作用域，读取项目目录
的 `ecc.toml`。`lec`、`lvs`、`postroutelec`、`harden` 没有步骤级配置（Tcl 驱动、工具默认或
复用 `db_ecc.json`）。

不带 STEP 输出项目级配置（`ecc.toml` 键 + 解析后的绝对路径）；带 STEP 列出该步骤在 workspace `config/` 下实际生效的配置文件。

```console
$ ecc config --plain    # 项目级（节选）
config=design.name scope=project value=gcd resolved=gcd source=ecc.toml
config=design.top scope=project value=gcd resolved=gcd source=ecc.toml
config=pdk.name scope=project value=ics55 resolved=ics55 source=ecc.toml
...

$ ecc config floorplan  # 步骤级
[config]
  step:
    db_ecc.json (config)
      path: default/config/db_ecc.json
  inspect: ecc config floorplan
    floorplan_ecc.json (config)
      path: default/config/floorplan_ecc.json
  inspect: ecc config floorplan
```

## 8.5. project / workspace — 编辑项目资源与刷新 workspace

`ecc project` 只写项目根目录的 `ecc.toml`；它不修改已创建 workspace。支持的字段覆盖 `[design]` 的 `name`、`top`、`rtl`、`netlist`、`golden_netlist`、`def`、`sdc`、`spef`、`clock_port`、`frequency_mhz`，以及 `pdk.name`、`pdk.root` 和 `flow.preset`。

```bash
ecc project set design.def inputs/gcd.def
ecc project set design.rtl rtl/gcd.sv rtl/alu.sv  # 整体替换 RTL 列表
ecc project add design.rtl rtl/fifo.sv
ecc project remove design.rtl rtl/alu.sv
ecc project unset design.spef
ecc project show [KEY]
ecc project apply [--set KEY=VALUE...] [--unset KEY...] [--add-rtl FILE...] [--remove-rtl FILE...]
                                      # 一次 manifest 修订内原子应用多项修改
ecc project baseline <WORKSPACE_ID> [--reason TEXT]   # 选定以哪个 workspace 的已存 QoR 作为项目基线
ecc project reconcile                 # 修复可证明的项目中间状态（如未完成的删除）
ecc project doctor [--fix]            # 交叉核对 project.json 与 workspace 目录；--fix 显式修复
```

`project apply` 把 `set`/`unset`/`add`/`remove` 的修改打包成一次原子 manifest 更新
（失败时不会出现改了一半的组合）。`project baseline` 记录后续 run 以哪个已声明
workspace 的已存 QoR 为对比基线。`project doctor`（不要与环境自检 `ecc doctor`
混淆，见 §4）报告派生字段与 workspace 目录不一致的条目、指向缺失目录的条目，
以及未登记的 workspace 目录；存在不一致时退出码为 1，`--fix` 会逐项显式修复。

### 将 RTL 导入项目

`ecc rtl import` 会把设计输入复制到项目自己的 `rtl/` 目录，
并同步更新 `ecc.toml` 与 `project.json`。建议在用 ECOS Studio 打开项目前
先完成这一步，这样后续创建 Workspace 时不再依赖原始源码目录：

```bash
ecc rtl import \
  --filelist /designs/gcd/sources/sources.f \
  --project /projects/gcd

ecc rtl import \
  --verilog /designs/gcd/top/gcd.v \
  --verilog /designs/gcd/common/defs.vh \
  --project /projects/gcd
```

对于 filelist，路径以 filelist 所在目录为基准解析。filelist 本身和它引用
的文件都会复制到 `<project>/rtl/` 下，并保留原有的相对目录结构。复制后的
filelist 会被重写为只引用项目内路径。目标文件默认不能覆盖，确认要覆盖时
才使用 `--force`。不支持的递归/库文件选项（`-f`、`-v`、`-y`）需要在导入
前手动展开。

该命令会写入 `ecc.toml` 的 `design.rtl`，并更新
`project.json.base_design.rtl_list` 及源输入元数据。创建 Workspace 前建议先
检查项目：

```bash
ecc check --project /projects/gcd
ecc workspace create default --project /projects/gcd
```

如果项目中已经存在 Workspace，导入新的 RTL 不会直接修改已有 Workspace。
需要显式使用更新后的项目配置重建：

```bash
ecc workspace refresh default --project /projects/gcd
```

随后可以在 ECOS Studio 中打开 `/projects/gcd/project.json`；Workspace 创建流程
会使用项目内的 RTL 声明。导入后不要直接删除或移动 `rtl/` 目录，除非同步更新
`ecc.toml`。

`ecc workspace import WORKSPACE --path DIR --project PROJECT` 把已有 ECC workspace 登记到 `project.json`，不执行 flow、不修改 workspace 内文件，也不移动目录。`WORKSPACE` 是后续命令使用的逻辑 ID；`--path` 必填且必须是完整绝对目录。导入会只读检查持久化 flow、状态、design、PDK 和参数，然后原子地登记路径：

```bash
ecc workspace import archive \
  --project /projects/gcd \
  --path /data/ecc-runs/gcd/archive

# 导入后按 ID 选择 workspace。
ecc status --project /projects/gcd --workspace archive
ecc run --project /projects/gcd --workspace archive --resume
```

导入会拒绝格式错误或不兼容的 workspace、重复 ID/路径、受保护路径，以及仍需先执行 `ecc migrate` 的 legacy 项目。如果只有 `ecc.toml` 而还没有 `project.json`，成功导入时会先创建 schema-v1 manifest，再登记该 workspace。

`ecc workspace refresh NAME --project DIR` 用当前 `ecc.toml` 重建一个已在 `project.json` 声明的 workspace，但不执行 flow。它会在清单已声明的路径上替换该 workspace 的复制输入、工具配置、状态和产物；完成后再执行 `ecc run --workspace NAME`。替换前会把受管 JSON 配置和 `macro_location.tcl` 与 `home/config-derived-manifest.json` 比对；如其中任一文件在上次派生后被改过，则返回 `derived_configs_modified`、列出文件，并保持 workspace 不变。应先审查修改，尽量通过 `ecc param`/`ecc macro`/`ecc.toml` 表达；确定丢弃时才传 `--force`。旧 workspace 若还没有派生清单，因无比对基线，首次 refresh 会直接进行。`ecc run --workspace NAME --overwrite` 仍是显式重建并立即执行的快捷方式：

```console
$ ecc workspace refresh default
[status]
  workspace id: default
  status: refreshed
  workspace: /tmp/gcd/default
  run: ecc run --workspace default

$ ecc workspace refresh nosuch
[error]
  workspace_not_declared workspace_not_declared: unknown workspace 'nosuch'; declared workspaces: default
rc=1

$ ecc workspace refresh default --force   # 明确要丢弃检测到的配置修改
$ ecc workspace refresh default --keep-backup   # 被替换的目录保留为归档的 .replace-backup-* 同级目录
```

入口输入、PDK 路径和 `flow.preset` 的改动必须走 refresh，因为它们会改变 workspace 的输入快照或 flow 结构。只调已有 workspace 的参数还可以用 `ecc param set KEY VALUE --workspace NAME`（见 §9），不经过 `ecc.toml`。

### Workspace 生命周期：create、derive、archive、delete、reset

其余 `ecc workspace` 子命令在不执行 flow 的前提下管理声明生命周期：

```bash
ecc workspace create <NAME> [--path DIR] [--from STEP] [--to STEP] [--set KEY=VALUE...]
                                    # 创建并登记空的受管 workspace（不运行）
ecc workspace derive <SOURCE> <TARGET> [--from STEP]
                                    # 从已有 workspace 的完成状态分叉出新 workspace
ecc workspace archive <NAME>        # 标记归档：保留在磁盘上，但退出自动选择
ecc workspace delete <NAME> [--delete-directory]
                                    # 移除 manifest 条目；--delete-directory 同时删除文件
ecc workspace reset-flow <NAME>     # 清除持久化 flow 状态，下次 run 从头开始
ecc workspace reconcile-deletes     # 崩溃后收尾未完成的 workspace 删除
```

`create` 是 `ecc run` 在执行前所做创建动作的独立形式，供 GUI/自动化流程先登记 ID；
`--from/--to` 声明有界范围，`--set` 在创建时记录参数覆盖（与 `ecc run --set` 的
fresh-run 语义相同）。`derive` 把源 workspace 已完成的步骤复制到
`<project>/<TARGET>`——可以只从指定步骤开始——并在 `project.json` 中登记分叉关系，
使实验可以从中间结果继续而不影响源。`archive` 是让 workspace 退出自动选择的推荐方式
（不必手改 `project.json`）；`delete` 取消登记并可选删除目录。自动化选项按需适用
（archive/delete/reset-flow 带 `--expected-revision`；创建/分叉类子命令带
`--command-id` 与 `--no-wait`；见 §5.1），对占用中的 workspace 执行变更会报
`workspace_busy`（退出码 20）。

```console
$ ecc workspace create trial
[status]
  workspace id: trial
  status: refreshed
  workspace: /tmp/gcd/trial
  run: ecc run --workspace trial

$ ecc workspace create trial    # 入口输入缺失时（create 与 run 一样校验入口输入）
[error]
  step_input_missing step_input_missing: design.rtl does not exist: /tmp/gcd/rtl/gcd.v
rc=1

$ ecc project baseline trial --reason "first experiment"
[status]
  project: baseline
  status: selected
  workspace: trial

$ ecc workspace derive trial branch_a
[status]
  workspace id: branch_a
  status: derived
  workspace: /tmp/gcd/branch_a
  workspace revision: 1
```

## 8.6. flow — 查看已注册的 flow 目录

```bash
ecc flow list [--plain|--json]
ecc flow show <FLOW_ID> [--project DIR] [--plain|--json]
ecc flow validate [--flow FLOW_ID] [--project DIR] [--plain|--json]
```

`flow list` 以 `flow_step` 记录输出每个已注册 flow preset 及其有序步骤
（`rtl2gds`、`syn_sta`、`synthesis_lec`），含 `ordinal`、`skippable` 和
`default skipped` 标志——即 `ecc run --preset` 选择所用的同一目录。`flow show
FLOW_ID` 只显示一个 preset（未注册的名字报 `unknown_flow`，退出码 2）。`flow
validate` 校验 flow 定义与步骤元数据，并对每个 flow 输出一条 `flow_validation`
记录；三者均为只读，不需要运行中的 workspace。

```console
$ ecc flow show rtl2gds
[result]
  record: flow_step
  flow id: rtl2gds
  step id: Synthesis
  ordinal: 0
  skippable: False
  default skipped: False
  ...                            # 依次列出 18 个步骤；lec 为 skippable=True 且默认跳过

$ ecc flow validate
[status]
  record: flow_validation
  status: valid
  flow id: rtl2gds
  step count: 18
  ...                            # 其余 flow 各一条记录

$ ecc flow list --json
[
  {
    "record": "flow_step",
    "flow_id": "rtl2gds",
    "step_id": "Synthesis",
    "ordinal": 0,
    "skippable": false,
    "default_skipped": false
  },
  ...
]
```

## 9. param — 参数管理

```bash
ecc param list                      # 简明列表：旧参数 + 已显式覆盖的直配参数
ecc param list --step cts           # 查看一个步骤的完整已审核 schema
ecc param list --all                # 查看完整 schema（含所有模板直配字段）
ecc param show KEY                  # 查看单个参数（值/默认/来源/类型/范围/映射）
ecc param set KEY VALUE             # 写入 ecc.toml（保留注释与格式）
ecc param unset KEY                 # 移除覆盖，恢复默认值
ecc param diff                      # 只显示与默认值不同的参数
ecc param apply [--set KEY=VALUE...] [--unset KEY...]   # set/unset 的原子批量形式
ecc param set KEY VALUE --workspace NAME  # 仅修改指定 workspace，不写 ecc.toml
```

`list`、`show`、`diff` 另有 `--json`（记录数组视图）。`param apply` 把多个
`set`/`unset` 修改打包——默认项目作用域，或以 `--workspace NAME` 指定一个
workspace——整批落地为一次原子更新和一次失效；批内任一校验失败则什么都不写。
workspace 作用域下 `--step STEP` 进一步把批次限制为该步骤可配置的参数（否则报
`parameter_not_applicable`），`--expected-revision`/`--command-id`/`--no-wait`
承载自动化契约（见 §5.1）。

通用选项：`--project DIR`、`--plain`。`list`、`show`、`set`、`unset` 和 `diff` 还接受 `--workspace NAME`。此时参数写入该 workspace 的 `home/params.toml`（不写 `ecc.toml`），刷新其生成配置，并将参数所属步骤及其后缀标记为待执行；后续 `ecc run --workspace NAME` 从该步骤继续。workspace 局部设置会记录到 `workspace_param_overrides`（含修改前的 `baseline`）——`param diff --workspace NAME` 与该 baseline 对比，`param unset KEY --workspace NAME` 恢复 baseline。只有 `ecc param list --all` 中的已审核参数可局部设置，且参数所属步骤必须存在于该 workspace 的持久化 flow 中（否则报 `workspace_param_refresh_failed`，例如对只有综合的 workspace 设 `place.*`）；`pdk.*` 路径字段仍需修改 `ecc.toml` 后执行 `ecc workspace refresh`：

```console
$ ecc param set design.frequency_mhz 150 --workspace default --plain
param=design.frequency_mhz value=150.0 status=set source=workspace workspace=default from_step=Synthesis invalidated_steps=['Synthesis']

$ ecc param list --workspace default      # workspace 作用域：只列局部覆盖
    design.frequency_mhz           150.0  (workspace)

$ ecc param show design.frequency_mhz --workspace default
  design.frequency_mhz
    value          150.0
    source         workspace

$ ecc param diff --workspace default --plain
param=design.frequency_mhz value=150.0 baseline=100.0 source=workspace workspace=default

$ ecc param unset design.frequency_mhz --workspace default --plain
param=design.frequency_mhz value=100.0 status=unset source=workspace workspace=default from_step=Synthesis invalidated_steps=['Synthesis']
```

```console
$ ecc param list
  design
    design.frequency_mhz           100.0  (ecc.toml)
  floorplan
    floorplan.core_util            0.4
    floorplan.core_margin          [2, 2]
    floorplan.aspect_ratio         1.0
  cts
    cts.max_fanout                 32
  place
    place.target_density           0.2
    place.target_overflow          0.1
    place.global_right_padding     0
    place.cell_padding_x           200
    place.routability_opt          1
  route
    route.bottom_layer             MET2
    route.top_layer                MET5
  sta
    sta.max_paths                  1000

$ ecc param set place.target_density 0.65
  set place.target_density = 0.65 (ecc.toml)

$ ecc param set cts.skew_bound 0.05
  set cts.skew_bound = 0.05 (ecc.toml)

$ ecc param set pdk.tech prtech/techLEF/N551P6M_ecos.lef
  set pdk.tech = prtech/techLEF/N551P6M_ecos.lef (ecc.toml)

$ ecc param diff
  place.target_density           0.65 (was 0.2, ecc.toml)

$ ecc param show place.target_density
  place.target_density
    value          0.65
    default        0.2
    source         ecc.toml
    type           float
    applies        placement
    maps to        DreamPlace.target_density
    description    Target placement density
    range          [0.1, 1.0]
    ...

$ ecc param set route.top_layer MET9     # 非法取值
[error]
  invalid_value value 'MET9' not in allowed choices ('MET2', 'MET3', 'MET4', 'MET5', 'MET6') for route.top_layer
  param: route.top_layer
rc=1
```

`set` 会在 `ecc.toml` 末尾维护对应分组表；`unset` 后表被清理：

```toml
[params.place]
target_density = 0.65

[params.floorplan.die_builder]
mode = "die_size"

[pdk.overrides]
tech = "prtech/techLEF/N551P6M_ecos.lef"
```

旧的语义参数（13 个）保持原有名称和含义；所有工具模板中经过审核的静态字段均由每个步骤的 `config_params/*.py` schema 提供。用 `ecc param list --step <step>` 或 `ecc param list --all` 获取当前版本的完整清单和类型；列表与对象值必须使用 JSON 字面量，例如 `ecc param set cts.routing_layer '[4, 5]'`。

以下是旧的语义参数：

| 参数 | 类型 | 默认值 | 约束 | 生效步骤 |
|---|---|---|---|---|
| `design.frequency_mhz` | float | 100.0 | [1e-6, 10000] MHz | synthesis |
| `floorplan.core_util` | float | 0.4 | [0.01, 1.0] | floorplan |
| `floorplan.core_margin` | list[int] | [2, 2] | — | floorplan |
| `floorplan.aspect_ratio` | float | 1.0 | [0.1, 10.0] | floorplan |
| `cts.max_fanout` | int | 32 | [1, 200] | cts |
| `place.target_density` | float | 0.2 | [0.1, 1.0] | placement |
| `place.target_overflow` | float | 0.1 | [0.0, 1.0] | placement |
| `place.global_right_padding` | int | 0 | [0, 100] | placement |
| `place.cell_padding_x` | int | 200 | [0, 10000] | placement |
| `place.routability_opt` | int | 1 | {0, 1} | placement |
| `route.bottom_layer` | str | MET2 | MET1–MET5 | routing |
| `route.top_layer` | str | MET5 | MET2–MET6 | routing |
| `sta.max_paths` | int | 1000 | [1, 100000] | sta |

优先级：CLI `--set` > `ecc.toml` `[params.*]` > 模板默认值。`pdk.*` 路径参数写入 `[pdk.overrides]`：`pdk.tech`、`pdk.lefs`、`pdk.libs`、`pdk.mapping_file` 相对 `pdk.root` 解析，`pdk.sdc` 和 `pdk.spef` 相对项目目录解析；六者都会校验文件。

## 9.5. macro — 手动宏单元摆放

```bash
ecc macro set INSTANCE --x X --y Y --orient ORIENT [--project DIR] [--workspace NAME] [--plain]
ecc macro remove INSTANCE [--project DIR] [--workspace NAME] [--plain]
ecc macro import PATH [--project DIR] [--workspace NAME] [--expected-revision N] [--command-id TEXT] [--no-wait] [--plain]
ecc macro show [--project DIR] [--workspace NAME] [--plain]
```

含硬宏（SRAM 等）的设计默认在 `macroPlacement` 步骤由 DreamPlace 自动摆放，结果写入 `config/macro_location.tcl`。`ecc macro` 管理手工摆放参数 `macro.placements`：坐标单位微米，实例以 `fixed` 状态提交。参数非空时 `macroPlacement` 保留 load/save 流程但跳过 DreamPlace，由 `postFloorplan` 按该文件提交宏。方向取值 `R0`、`R90`、`R180`、`R270`、`MX`、`MY`、`MX90`、`MY90`；同一实例重复 `set` 为原地更新。`import` 解析 `placeInstance` 交接文件（微米、R 记法，跳过注释与 `setInstancePlacementStatus` 行）并**整表替换** `macro.placements`；空文件等于清空参数，畸形语句整体报错不写入。

与 `ecc param` 相同的两种 scope：

- 项目（默认）：写入 `ecc.toml` `[params.macro]`，在下一次新建 workspace（`ecc run` / `--overwrite`）或 `ecc workspace refresh` 时渲染进 Tcl；
- `--workspace NAME`：写入该 workspace 的 `home/params.toml`，立即重生成 `config/macro_location.tcl`，并把 `macroPlacement` 及其后缀标记为待执行，之后 `ecc run --workspace NAME` 从 `macroPlacement` 续跑。

`ecc macro show --workspace NAME` 额外解析现有 `config/macro_location.tcl` 并输出 `file_placements` 与 `diverged`（文件与参数是否一致），便于发现手改文件或导入未落盘的差异。

```console
$ ecc macro set u_ram0 --x 10 --y 20.5 --orient R0
[status]
  param: macro.placements
  instance: u_ram0
  x: 10.0
  y: 20.5
  orientation: R0
  placements: [{'instance': 'u_ram0', 'x': 10.0, 'y': 20.5, 'orientation': 'R0'}]
  status: set
  source: ecc.toml

$ ecc macro set u_ram1 --x 150 --y 20.5 --orient MY
$ ecc macro show
[result]
  param: macro.placements
  placements: [{'instance': 'u_ram0', 'x': 10.0, 'y': 20.5, 'orientation': 'R0'}, {'instance': 'u_ram1', 'x': 150.0, 'y': 20.5, 'orientation': 'MY'}]
  source: ecc.toml

$ ecc macro remove u_ram1
[status]
  param: macro.placements
  instance: u_ram1
  placements: [{'instance': 'u_ram0', 'x': 10.0, 'y': 20.5, 'orientation': 'R0'}]
  status: removed
  source: ecc.toml
```

在已有 workspace 上调整宏位置并重跑受影响片段：

```bash
ecc macro set u_ram0 --x 120.0 --y 80.0 --orient MY --workspace default
ecc run --workspace default                 # 从 macroPlacement 续跑，下游步骤一并重跑
ecc macro remove u_ram0 --workspace default # 删除最后一个条目后恢复 DreamPlace 自动摆放，再续跑即回到自动结果
```

把一份现成的 `macro_location.tcl`（例如另一工程或 Chip Viewer 手摆导出的文件）导入为手工摆放：

```bash
ecc macro import /path/to/macro_location.tcl --workspace default
ecc macro show --workspace default          # file_placements 与 placements 一致、diverged 为 False
ecc run --workspace default                 # 跳过 DreamPlace，postFloorplan 按文件提交宏
```

实例名必须存在于设计中，且必须列出全部硬宏——`postFloorplan` 会按缺失实例名报错；`macro_location.tcl` 是生成物，不支持手工编辑（未设置该参数时重跑 `macroPlacement` 会重新生成）。交接文件格式与三阶段 floorplan 细节见 [floorplan-flow.cn.md](floorplan-flow.cn.md)，参数说明见[配置参考 §1.5](ecc-config-ref.cn.md)。

## 10. pdk — PDK 路径配置

PDK 本体由安装脚本（`--with-toolchain`，见教程）或手动 clone 获取。已就绪的 PDK 用 `ecc pdk set-root` 接入（写入 `ecc.toml` 的 `[pdk] root`，自动展开为绝对路径；目录必须已存在）。内容不完整（如还没 `make unzip`）不阻断设置，会给出提示：

全部 `pdk` 子命令都支持 `--project DIR` 和 `--plain`。

```bash
ecc pdk set-root ~/pdk/icsprout55-pdk   # 接入已就绪的 PDK checkout
ecc pdk show                             # 查看生效 root 与来源（ecc.toml / 环境变量 / 仓库默认）及内容校验
ecc pdk show --json                      # 同上，JSON 记录数组
ecc pdk verify                           # 只读校验解析出的 PDK 内容，不修改配置
ecc pdk unset                            # 清空 root，回落环境变量 / 仓库默认
ecc pdk set-root /bad/path               # → [error] invalid_pdk_path（目录不存在）
```

`pdk verify` 只读重跑解析 PDK 的内容校验（即 `pdk show` 报告的同一探测），但会强制
结果：内容校验未通过时退出码为 1（解析 root 不可用时报 `pdk_contents_unavailable`）
——打包 smoke 测试用的就是这一形式。`show` 与 `verify` 都支持 `--json`。

```console
$ ecc pdk set-root ~/pdk/icsprout55-pdk
[status]
  pdk: set-root
  status: set
  path: /home/user/pdk/icsprout55-pdk
  config: ecc.toml
  check: ecc check
```

解析优先级不变：`ecc.toml [pdk] root` > `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT` > 仓库默认 `<ecc 检出目录>/../pdk/icsprout55-pdk`（ecos-studio workspace 布局）。除 root 使用 `ecc pdk set-root` 外，`pdk.tech`、`pdk.lefs`、`pdk.libs`、`pdk.mapping_file`、`pdk.sdc` 和 `pdk.spef` 可由 `ecc param set KEY VALUE` 管理，写入 `[pdk.overrides]`。

## 11. signoff — 签核包

`ecc signoff export` 需要就绪的 Harden 签核包。`ecc signoff inspect` 可审阅尚未完成的 workspace。两个子命令都接受 `--project DIR` 与可选的受管 `--workspace NAME`，以及 `--plain`。

### 11.1 inspect — 就绪度审阅

```bash
ecc signoff inspect [--project DIR] [--workspace NAME] [--plain|--json]
```

刷新已完成步骤的 analysis 与 `home/checklist.json` 后，输出签核包的就绪状态（`ready / attention / blocked`）、七个分组（initial/config/harden/final_design/sta/spef/reports）与风险清单。**blocked 也返回 rc=0**（检查是建议性的，门禁在 export）：

```console
$ ecc signoff inspect --workspace default
[signoff]
  status    : blocked
  workspace : default
  export    : ecc signoff export -o <path>
  report    : ecc report summary

  groups:
    initial        ready      (2/2)
    config         ready      (4/4)
    harden         blocked    (1/3)
    sta            blocked    (3/6)
    ...

  risks:
    [blocked] Harden signoff requirements block export
              Current-output analysis refresh failed: ...
```

### 11.2 check — 只读质量门禁

```bash
ecc signoff check [--profile rtl2gds] [--project DIR] [--workspace NAME] [--plain]
ecc signoff check --json
```

`check` 不刷新分析、不启动 EDA、不写入 workspace，只读取当前 flow、QoR、checklist
和 DRC/LVS/STA 证据，返回统一 gate 状态：`pass`、`fail` 或 `unknown`。缺少证据不会
被当作通过；总体状态只在全部 gate 为 `pass` 时为 `pass`，任一 gate 失败为 `fail`，
其余情况为 `unknown`。首版 `rtl2gds` profile 包含 `flow_complete`、`qor_available`、
`checklist_ready`、`drc_clean`、`lvs_clean`、`sta_setup_clean` 和 `sta_hold_clean`。

`--json` 返回记录数组，每个 gate 使用统一字段：`gate`、`required`、`status`、`reason`、
`source`、`failed_items`、`violation_count`、`stale` 和 `provisional`；artifact gate
还可能包含 `bytes` 与 `sha256`。`physical_signoff` profile
额外检查 `lec_proven`、`final_gds_available` 和 `final_netlist_available`：

```bash
ecc signoff check --profile physical_signoff --json
```

该 profile 读取 postRouteLec 的 proven result 和 Harden/filler 的最终输出，不验证文件
内容 hash；缺少或无法唯一定位的 artifact 返回 `unknown`。`physical_signoff` 的总体
结果只由物理签核必需 gate 决定；QoR 和 checklist 作为信息 gate 输出，字段
`required=false`，不会因缺少 QoR 单独阻断物理签核判断。

gate 结果是当前已保存证据的判断，不等同于 tapeout 批准。未知 profile 返回
`unknown_signoff_profile`，参数错误退出码为 2，workspace/读取失败遵循公共 CLI 错误契约。

### 11.3 export — 导出签核包 tar.gz（有门禁）

```bash
ecc signoff export -o <path>.tar.gz [--include-debug] [--additional-files -] [--project DIR] [--workspace NAME] [--plain]
```

`--additional-files -` 从 stdin 读取一个 tar 流，把其中的普通文件一并嵌入导出包
（只接受相对 POSIX 路径；最多 256 个条目、单文件 16 MiB、总量 64 MiB——这是
ECOS Studio 附加用户自选文件的通道）。该命令还接受自动化选项
`--expected-revision` 与 `--no-wait`（见 §5.1）。

直接指定已有 workspace 时，例如：

```bash
ecc signoff export --project /path/to/gcd --workspace default -o /path/to/gcd_signoff_package.tar.gz
```

与 GUI「导出签核包」同源：刷新分析 → 收集 initial/config/harden/final 全部交付物 → 原子落盘 `<design>_signoff_package.tar.gz`。就绪度不足时拒绝导出（不产生残档）：

```console
$ ecc signoff export -o gcd.tar.gz --project gcd
[error]
  signoff_incomplete signoff package is incomplete: quality.drc.clean, artifact.lvs.report, ...
  inspect: ecc signoff inspect
rc=1

$ ecc signoff export -o gcd.tar.gz --project gcd     # 就绪后
[export]
  signoff: export
  status: exported
  path: /abs/path/gcd.tar.gz
```

### 11.5 可复现证据导出、sweep 与诊断

`reproducible` 与 `diagnose` 的命令契约：

| 命令 | 必需参数 | 可选参数 | 用途 |
|---|---|---|---|
| `ecc reproducible export` | `--output PATH` | `--project DIR`、`--workspace NAME`、`--plain` | 为 workspace 导出只读证据包 tar.gz |
| `ecc reproducible inspect` | `--package PATH` | `--files`、`--type all\|rtl\|config\|flow\|checklist\|signoff`、`--plain`、`--json` | 离线查看包内容，可按文件类型筛选 |
| `ecc reproducible verify` | `--package PATH` | `--plain`、`--json` | 校验包 schema、SHA-256 与 fingerprint |
| `ecc reproducible report` | `--package PATH` | `--plain`、`--json` | 汇总文件、fingerprint、输入、runtime 与校验状态 |
| `ecc diagnose run` | — | `--project DIR`、`--workspace NAME`、`--plain`、`--json` | 一条命令汇总 flow、checklist、QoR、缺失 artifact 与恢复建议 |

实验命令组（`reproducible`/`sweep`/`explore`/`diagnose`）默认输出 JSON（机器可读），`--plain` 输出稳定的 key=value 记录。真实输出示例：

```console
$ ecc reproducible export --workspace trial --output evidence.tar.gz
{
  "file_count": 19,
  "package": "/path/to/evidence.tar.gz",
  "status": "success"
}

$ ecc reproducible verify --package evidence.tar.gz
[status]
  status: pass
  package: /path/to/evidence.tar.gz
  errors: []

$ ecc diagnose run --workspace trial --json
{
  "checklist": {"blocked_count": 27, "blocked_items": ["artifact.synthesis.netlist", "..."], "status": "blocked"},
  "errors": [],
  "flow": {"failed_steps": [], "status": "unstart"},
  "missing_artifacts": [],
  "next_actions": [
    "ecc report checklist --project /path/to/project --workspace trial",
    "ecc run --project /path/to/project --workspace trial --resume"
  ],
  "project": "/path/to/project",
  "qor": {"available": false, "score": "unknown"},
  "status": "blocked",
  "workspace": "/path/to/project/trial"
}
rc=6                        # 诊断为 failed 或 blocked 时退出码 6（见 §1 退出码表）
```

创建确定性的参数 sweep。重复使用 `--param` 定义笛卡尔积；候选记录保存在 `experiments/<name>/`，不会修改项目 manifest 或 baseline workspace。sweep/explore 的完整参考——计划与结果 schema、执行隔离、排序规则——见 [Sweep 参考手册](ecc-sweep-ref.cn.md)：

```bash
ecc sweep create --project /path/to/project --name density --param place.target_density=0.60,0.65 --param cts.target_skew=0.10,0.15
ecc sweep list --project /path/to/project                  # 已有 sweep 名称的 JSON 数组
ecc sweep show --project /path/to/project --name density    # sweep 计划（sweep.json）
ecc sweep run --project /path/to/project --name density [--max-candidates N]
ecc sweep compare --project /path/to/project --name density # candidate | flow | steps | checklist | violations | qor | exit | parameters
ecc explore rank --project /path/to/project --name density
ecc explore promote --project /path/to/project --name density --candidate candidate_0002
```

`--max-candidates N` 把 `sweep run` 限制为计划的前 N 个候选（适合对大笛卡尔积先做
一轮冒烟）。`sweep run` 可续跑：已有结果且 workspace 存在的候选不会重跑。
续跑会重新采集已有结果，修正旧缓存中的状态、step checklist 和总体 QoR。
只从 `home/qor_report.json` 读取总体分数；signoff 返回 `7` 不会成为 passed。
`sweep compare`（人类可读表格）与 `sweep show`/`explore rank`（`--json`）是
`results.json` 的只读视图；排序为 passed 优先、QoR 分数降序。`explore promote`
把获胜候选记录到 `experiments/<name>/winner.json`——只有状态为 `passed` 的候选
可以被提升。

当前版本以确定性和证据留存为主，暂不提供自动优化、分布式调度、多 SDC 或自动替换 baseline workspace。

可复现导出包现在包含 ECC runtime 版本、文件集合 fingerprint，以及项目配置和 RTL 输入
fingerprint。sweep 计划包含稳定的 `plan_fingerprint`，因此可以排除创建时间后比较两个
参数计划是否一致。

`ecc reproducible verify` 会审计包 schema、manifest 条目类型和重复路径、归档文件大小、
SHA-256、整体文件 fingerprint、输入 fingerprint 以及不安全归档路径。manifest 或证据被
篡改时返回退出码 `6`。

可复现 manifest 还会记录 ECC、ECC-Tools、DreamPlace、Yosys、Sizer、KLayout 以及 PDK 的
标识和存在性信息，便于比较不同环境生成的证据包。

可复现证据包可以复制到其他目录后独立校验；`inspect` 和 `verify` 使用包内 manifest，
不要求导出时的原始项目路径仍然存在。

无需原始 workspace 也可以离线查看证据包：

```bash
ecc reproducible inspect --package evidence.tar.gz --files --json
ecc reproducible report --package evidence.tar.gz --json
```

报告会汇总文件、fingerprint、输入、runtime 元数据和校验状态。

离线报告支持可读文本输出和文件类型筛选：

```bash
ecc reproducible report --package evidence.tar.gz
ecc reproducible inspect --package evidence.tar.gz --files --type checklist --json
```

支持的类型包括 `all`、`rtl`、`config`、`flow`、`checklist` 和 `signoff`。

离线报告还会从证据文件汇总 flow 状态、checklist 状态、QoR 和 checker 违例数。缺失或旧
格式证据统一显示为 `unknown`，不会误判为通过。

离线摘要字段现在包含证据 `sources` 和 `reasons`（`ok`、`missing`、`invalid`）；无法评级时，
摘要值仍显示为 `unknown`。

CI design matrix 的每个 design leg 会在产品 flow 后执行轻量打包 CLI smoke。smoke 使用隔离的
临时证据 workspace，检查 reproducible export、verify、report 和 sweep 计划生成，不会重复执行
第二次完整 EDA flow。

CI 打包 smoke 可以接收 E2E 输出目录。发现真实 `home/flow.json` 时，会额外针对真实 workspace
验证 `status`、reproducible export 和 verify；未发现时继续执行隔离的契约 smoke，不会误阻断 CI。

在比较或 promote candidate 前可以先校验 sweep 完整性：

```bash
ecc sweep verify --project /path/to/project --name density_test
```

命令会检查 plan fingerprint、candidate/result 对应关系、参数一致性、workspace 是否存在以及
结果缺失/重复。完整性错误返回退出码 `6`。
还会审计 schema、结果字段类型、步骤状态、有限数值 QoR、整数退出码与 flow 文件。
passed 记录不能包含非零退出码、缺失 QoR、未完成步骤或未完成 flow。
workspace 已有 checklist 文件时必须有效且通过，避免旧 passed 缓存绕过当前阻塞项。
旧结果可省略 schema 和探测退出码字段；`explore promote` 也校验候选证据。

可以将排序后的 sweep 结果导出为 CI artifact、GUI 或表格使用：

```bash
ecc explore export --project /path/to/project --name density_test --format csv --output density.csv
ecc explore export --project /path/to/project --name density_test --format markdown
```

支持 `json`、`csv` 和 `markdown` 三种格式。

打包 CI smoke 还会校验 sweep 结果完整性，并将排序结果导出为 JSON、CSV 和 Markdown，文件会
上传到对应 design 的 `cli-contract` 证据目录。

可以使用一个命令诊断 workspace：

```bash
ecc diagnose run --project /path/to/project --workspace ws_0012 --json
```

结果会汇总 flow 状态、失败 step、blocked checklist、QoR 可用性、缺失 artifact 和恢复建议。
诊断为 failed 或 blocked 时返回退出码 `6`。

打包 CLI smoke 接收到 E2E 输出目录并发现真实 workspace 后，还会执行 `diagnose run`、
`report step`、`report project` 和 `signoff check`。对应 JSON 证据会写入该 design 的
`cli-contract` artifact 目录：`diagnose.json`、`report-step.json`、`report-project.json` 和
`signoff.json`。signoff 的质量失败允许返回 `6` 或 `7` 并保留证据；CLI 参数或运行错误仍会
使 smoke 失败。
隔离的打包 smoke 还会创建确定性的 candidate 结果证据，实际执行 `sweep verify`，并验证
`explore export` 的 JSON、CSV 和 Markdown 格式，不会再次启动 EDA flow。
该检查比较完整导出内容与 compare 矩阵，覆盖非法字段拒绝以及 blocked/failed/unknown
不可 promote。真实 E2E workspace 会通过隔离的缓存候选执行 `sweep run` 采集，
校验 step state、总体 QoR、signoff 退出码，并生成 `real-sweep-verify.json` 和
`real-sweep-results.json`；原 workspace 保持只读。

诊断和离线证据摘要支持从 `flow.json` 的 step `state` 推导 flow 状态，读取真实 checklist 的
`checklist/state/blocked/policy` 字段，以及 QoR 的 `scalar_summary.score`；旧简化格式仍可读取。
signoff 的 QoR gate 使用同样的分数读取规则。缺失、未评级或无效分数不会被视为可用 QoR，
损坏 checklist 不会被诊断为 passed；执行完成与 checklist blocked 会分别报告。

## 12. report — 设计总结、QoR 总分、checklist 与单步证据

```bash
ecc report summary [-o PATH] [--project DIR] [--workspace NAME] [--plain]
ecc report qor     [-o PATH] [--project DIR] [--workspace NAME] [--plain]
ecc report checklist [-o PATH] [同样的 selector 与输出选项]
ecc report step    [STEP] [--section feature|analysis|checklist|outputs]... [同样的 selector 与输出选项]
ecc report snapshot --output PATH [--project DIR] [--workspace NAME] [--plain|--json]
ecc report project [--project DIR] [--plain|--json]
```

### 12.1 summary — 文本设计总结报告

生成与 GUI「导出报告（文本）」同版式的设计总结（8 个分区：物理/时序/时钟/多 corner/绕线/功耗/验证/执行成本），默认写入 `<workspace>/signoff/<design>_design_summary.txt`：

```console
$ ecc report summary --project gcd
[status]
  report: summary
  status: written
  path: /path/gcd/default/signoff/gcd_design_summary.txt
  design: gcd
  bytes: 3789
  view: cat /path/.../gcd_design_summary.txt
```

报告节选（缺数据的指标显示 `—`，条件行自动折叠）：

```
===================  ECOS STUDIO — DESIGN SUMMARY REPORT  ====================
Design Name        : gcd
PDK / Node         : ics55
...
[ 2. TIMING CLOSURE & PERFORMANCE ]
  Target Clock Period                  5.0 ns              Target freq: 200.0 MHz
  Setup Slack (WNS / TNS)              -0.25 ns / -1.2 ns  VIOLATION
...
[ 8. FLOW EXECUTION COST ]
  Stage              Tool                  Runtime     Peak Mem  State
  Synth              yosys                     18s          512MB  Success
```

说明：inspect/export 会先刷新各步 analysis（与 GUI 一致）；report 默认按现状抽取（可用引擎 API `generate_text_report(workspace, refresh_analysis=True)` 要求刷新）。报告不要求 flow 完成——跑到哪一步就总结到哪一步。

### 12.2 qor — QoR 总体计分报告

对当前 workspace 运行 ECC-QoR V3 引擎。它把三个问题分开：五个物理质量坐标（`timing`、`interconnect`、`area`、`power`、`robustness`）、七条零容忍可行性门禁，以及证据完整度。ECOS Studio 直接消费同一份带版本的 `home/qor_report.json`，不另维护计分表。

标量总分使用 `qor_profile` 选中的权重（缺省为 `balanced`），并且**只在可评估维度上重新归一化**。因此未声明功耗预算时 `power` 为 null，不会压缩其余维度的分数。任一可行性门禁失败都把总分置为 `0` / `FAIL`；门禁依赖的步骤未执行，或门禁证据损坏，则返回 `NOT_RATED`，不伪造分数。状态区间为 `GREEN >= 90`、`YELLOW >= 75`、`ORANGE >= 60`、`RED < 60`。文本报告默认写入 `<workspace>/signoff/<design>_qor_report.txt`。以下是基于参考 fixture 的精简 `--plain` 响应：

```console
$ ecc report qor --project gcd --plain
report=qor path=.../signoff/gcd_qor_report.txt bytes=... design=gcd \
  overall_score=98.96 qor_status=GREEN gate_status=PASS \
  dimensions="[{'dimension': 'timing', 'score': 100.0, 'state': 'OPPORTUNITY', 'features': ...}, ...]" \
  view="cat .../gcd_qor_report.txt" status=written
```

报告包含总分与 profile、五维分解、可行性门禁、证据状态、确定性诊断和按优先级排列的干预假设。公式、profile、阈值和 JSON 契约见 [ECC QoR 参考手册](ecc-qor-ref.cn.md)。

### 12.3 checklist — 签核清单报告

读取 `home/checklist.json`（schema v3 签核清单，由 flow 步骤/`ecc signoff inspect` 维护）渲染状态报告：总览（passed/blocked/attention/unavailable）、**BLOCKED 项明细**（含失败原因与 evidence 路径）、ATTENTION 项、全量表。清单不存在时返回 `checklist_unavailable`。默认写 `<workspace>/signoff/checklist_report.txt`。

```bash
ecc signoff inspect --project gcd    # 先刷新 checklist（若还没有）
ecc report checklist --project gcd
```

### 12.4 step — 单步骤 feature / analysis / checklist 报告（只读预览）

直接在终端预览**单个 step** 的三类产物，不写任何文件、不刷新任何快照（与 `report qor/checklist` 不同，本命令不加载 Workspace，因此不会触发配置迁移或追加 workspace 日志）。它是 `ecc status` 的深挖对应物：`status` 回答"run 跑到哪了"，`report step` 回答"这一步到底发生了什么"：

- 不带参数：全部 step 概览表（状态、runtime、峰值内存、指标数、quality、checklist 状态）
- 带 `STEP`：该 step 的三节明细
  - `feature`：`feature/<Step>.step.json` 的 run facts（state/runtime/peak_memory/constraints）与工具 facts + `feature/<Step>.db.json` 的分组设计统计（Design Layout / Statis / Instances）
  - `analysis`：`analysis/qor_metrics.json` 全量指标（值/单位/类别/角色）+ `analysis/qor_summary.json` 的 quality 状态与 quality gates（如 `qor.drc.clean — drc_count=336 == 0`）
  - `checklist`：`<step>/checklist.json`（v3 契约，缺失时回退 `home/checklist.json` 按步骤过滤）
- `--section` 可重复指定，只输出选中的节；某节产物缺失时该节显示 `unavailable`

step token 与 `ecc log` 同源（`synthesis/pre_floorplan/macro_placement/post_floorplan/placement/cts/...`），同时接受 flow 内部名（如 `Timing optimization`）与目录名变体（`timing_optimization`）；未知 token 返回 `unknown_step` 并列出可用值。

```console
$ ecc report step --workspace default
[report step]
  workspace : /tmp/gcd/default
  steps     : 17

  step                   tool         status    runtime  peak MB  metrics quality  checklist
  synthesis              yosys        success   0:0:17   1165.89  10      pass     ready
  lec                    kepler_formal success   0:0:1    0.164    -       -        ready
  pre_floorplan          ecc          success   0:0:1    97.516   -       -        ready
  macro_placement        dreamplace   success   0:0:5    97.516   -       -        ready
  post_floorplan         ecc          success   0:0:1    97.516   11      pass     ready
  ...
  drc                    ecc          success   0:0:3    42.0     12      blocked  blocked (1 blocked)

$ ecc report step Synthesis
[report step]
  step      : synthesis (Synthesis)
  tool      : yosys
  status    : success
  runtime   : 0:0:17, peak 1165.89 MB
  workspace : /tmp/gcd/default

  feature:
    run.peak_memory_mb                           1165.89
    run.runtime_seconds                          17.233
    run.state                                    Success
    ...

$ ecc report step drc --section analysis
  analysis:
    quality: blocked  (12 metrics, 0 missing)
    ...
    [BLOCK] qor.drc.clean — drc_count=336 == 0
```

#### 查询单步输出（outputs）

使用已有命令显式查询 Engineering Snapshot 登记的 DEF 和 Verilog 输出：

```bash
ecc report step place --workspace <workspace> --section outputs
ecc report step sta --workspace <workspace> --section outputs --json
```

默认报告仍只显示 feature、analysis、checklist，保持既有行为。
`outputs` 不执行工具、不迁移 snapshot、不刷新工作区，也不扫描目录。
索引缺失或损坏时返回 unavailable，不生成新的索引。

- `exists`、`bytes`：查询时检查工作区内部文件，不信任缓存的 exists。
- `availability`：available、missing 或 outside_workspace。外部引用不访问文件系统。
- `validity`：未成功的 step 为 not_current；成功也只标记 unknown，文件存在和
  step 成功不足以证明 hash、corner 或输入一致性。
- 本版本仅查询 snapshot 已登记的 DEF/Verilog，不承诺完整 GDS、日志或报告清单。

`report qor --json` 当前仍返回报告生成摘要，且会生成报告文件；它不是只读的完整
metrics API。不要把该输出当作完整 QoR schema。

### 12.5 snapshot — 保存已有运行快照

```bash
mkdir -p comparisons
ecc report snapshot --project /path/to/project --workspace default -o comparisons/before.json
ecc run --project /path/to/project --workspace default --only placement
ecc report snapshot --project /path/to/project --workspace default -o comparisons/after.json --json
ecc compare run --baseline comparisons/before.json --current comparisons/after.json --json
```

#### 范围与选择器

复用 report 的 `--project`、`--workspace` 与共享工作区解析。项目只有一个活动
工作区时可省略 `--workspace`；多个工作区时必须显式选择。受管的外部工作区沿用
现有绝对路径选择器。错误 manifest 或未声明的工作区不会回退到其他工作区。

只读取已提交的 `home/engineering-snapshot.json`。不加载 Workspace、不迁移或
刷新快照、不修改配置和 flow、不执行 EDA、不扫描产物目录、不复制 artifact 内容。
运行中保存只代表读取时已提交的投影，不是对执行进程的冻结或最终结果保证。
建议 before 在修改或运行前保存，after 在期望的运行完成后保存。

#### 目标与安全性

- `--output/-o` 必填，相对路径基于进程当前目录，支持 `~`。
- 目标必须位于源工作区外，父目录必须已存在；父目录符号链接解析后仍检查范围。
- 拒绝所有已有目标，包括文件、目录、正常或悬空符号链接；首版没有覆盖选项。
- 不接受 `.gz` 目标，不压缩、不迁移 schema，保留已有字段与 revision。
- 读取和保存均遵守 16 MiB 上限；非法 JSON、非有限数、schema 或身份错误均失败。
- 同目录临时文件写完后通过 hard link 原子发布，不覆盖并发创建的目标。
  不支持 hard link 的文件系统返回写入失败，不使用非原子回退。
- 失败清理本命令临时文件；已有目标和工作区文件不被修改。
- 导出内容不保证与源文件字节一致，但 JSON 对象相同；artifact 路径仍是源工作区
  的引用，不是可迁移交付包，不证明 artifact 内容保持一致。

#### 输出契约

默认文本、`--plain`、`--json` 复用共享输出方式，不可同时使用后两者。
终端只输出保存元数据，快照正文写入指定文件。JSON 顶层为记录数组：

```json
[
  {
    "report": "snapshot",
    "path": "/path/to/comparisons/before.json",
    "source": "/path/to/project/default/home/engineering-snapshot.json",
    "bytes": 2048,
    "schema_version": 4,
    "workspace_id": "workspace-gcd",
    "workspace_revision": 1,
    "status": "written"
  }
]
```

`workspace_id` 是快照内部身份，不一定等于项目 manifest 的工作区名称。
示例路径和字节数仅作说明，实际值取自保存结果。

| 情况 | 错误记录 | 退出码 |
| --- | --- | --- |
| 成功保存 | `report=snapshot, status=written` | 0 |
| 缺失、损坏、超限或身份不一致的快照 | `snapshot_read_failed` | 1 |
| 工作区内目标、父目录无效、压缩目标 | `report_destination_invalid` | 1 |
| 已有目标或并发创建目标 | `report_destination_exists` | 1 |
| 保存文件的 I/O 错误 | `report_write_failed` | 1 |
| 工作区/项目选择错误 | 共享 manifest/workspace 错误 | 1 |
| 缺少 output 或互斥输出参数 | 参数校验错误 | 2 |

#### 实现边界

`engine.snapshot` 维护 bounded reader 和身份校验；`engine.snapshot_export` 维护
目标约束和不覆盖保存；`cli.command_handlers.report_snapshot` 映射结果与错误。
`report snapshot` 与 `compare run` 使用同一快照 schema，不新增持久化格式。

### 12.6 compare run — 比较两份运行快照

#### 范围与用法

```bash
ecc compare run --baseline before.json --current after.json
ecc compare run --baseline before.json --current after.json --plain
ecc compare run --baseline before.json --current after.json --json
```

两参数均为必需的、未压缩的 Engineering Snapshot JSON 文件路径，支持相对路径和
`~`。不接受 run ID、workspace 名称或目录，不需要 `--project` / `--workspace`。
现有 `ecc run` 执行入口不变。

当前 snapshot 是 workspace 的已提交投影，不是历史运行数据库。运行前后必须分别
保存一份快照；CLI 不自动记录历史，不重建旧结果，也不读取 artifact 内容。

```bash
mkdir -p comparisons
ecc report snapshot --workspace /path/to/workspace --output comparisons/before.json
ecc param set place.target_density 0.30 --workspace /path/to/workspace
ecc run --workspace /path/to/workspace --resume
ecc report snapshot --workspace /path/to/workspace --output comparisons/after.json
ecc compare run --baseline comparisons/before.json --current comparisons/after.json --json
```

保存 before 时先确保 workspace 已停止运行；after 建议在流程完成后保存。仅重跑单步
可能使后续步骤失效，从而缺少最终 QoR；这时返回 unknown/unavailable 是正确结果。

`report snapshot` 只保存已有快照，不刷新结果；目标必须位于源工作区外，父目录必须
已存在，且目标不能已存在。保存时会校验快照；它不自动等待运行结束，也不复制
artifact 文件。详见本指南 §12.5。

#### JSON 契约

复用 ECC 公共输出契约，顶层是记录数组，首条记录为：

```json
[
  {
    "record": "run_comparison",
    "status": "success",
    "schema_version": 1,
    "baseline": {
      "workspace_id": "workspace-gcd",
      "workspace_revision": 1,
      "schema_version": 4,
      "source": "before.json"
    },
    "current": {
      "workspace_id": "workspace-gcd",
      "workspace_revision": 2,
      "schema_version": 4,
      "source": "after.json"
    },
    "summary": {
      "overall": "improved",
      "scope": "numeric_metrics_and_qor_score_only",
      "counts": {"improved": 1, "regressed": 0, "unchanged": 0, "unknown": 0}
    }
  }
]
```

示例省略了以下完整结果字段：

| 字段 | 含义 |
| --- | --- |
| `compatibility` | 保存的上下文元数据是否可比，以及不可比原因 |
| `steps` | 以 name/tool 对齐的前后 flow 记录，包含状态和已保存的 runtime 等字段 |
| `metrics` | 以 id/scope/corner/analysis_group 对齐，含前后值、单位、delta、trend、reasons |
| `qor` | 已保存的 score、各维度数值比较，以及 feasibility/evidence/power 等字段变更 |
| `parameter_changes` | 顶层参数的 added/removed/changed；保留 null 与缺失的区别 |
| `configuration_changes` | 已保存的 workspaceSpec/workspaceBindings 变更，不代表完整版本锁 |
| `signoff` / `checklist` | 前后已保存的原始投影与 change，不实时生成签核报告 |
| `artifacts` | 按相对 reference 对齐的索引变更，忽略路径身份 artifactId 的差异 |
| `warnings` | 内容未验证、总体数值趋势不等于签核结论等限制 |

文本默认显示摘要和 metric 趋势；`--json` 提供完整结构。`--plain` 使用公共 key=value
格式，复杂字段遵循既有 plain 表示；自动化解析嵌套字段请用 `--json`。

#### 比较与判定规则

- delta = current - baseline；缺失、非数值或布尔值不补零，delta 为 null。
- 单位优先读记录的 unit；现有记录未声明 unit 时复用 QoR metric registry 的单位。
  单位缺失、不一致或偏离规范单位时不计算 delta，不自动换算。
- 仅 registry 已定义方向的指标可判断 improved/regressed。未知指标、trend_only 和
  target_range 只提供可用的 delta，trend 为 unknown，不虚构阈值。
- flow 定义/顺序、design/inputs/PDK 元数据、约束参数或 corner context 等变化会
  禁用相关趋势判断。不同 workspace 可以展示差异，但首版不做跨 workspace 优劣判断。
- 优化参数变更会被列出，不会仅因 target_density 改变而禁用所有指标比较。
- QoR score 只有相同 schema/engine/profile 且两侧 available 才可判断；维度还要求
  featureIds 一致、不是 UNKNOWN。QoR 没有保存时明确 unavailable。
- summary 只汇总 metric 与 QoR score 趋势，不包含 flow/checklist/signoff 的质量判断。
  有未知项或没有可评估项时为 unknown；有改善和退化时为 mixed，否则为
  improved/regressed/unchanged。各项 counts 仍保留已识别的部分趋势。两侧都没有数值
  score 时，该项不参与汇总，不可用状态单独保留在 qor；summary 不代表完整 QoR。
- artifactId 是路径身份，不是内容 hash。所有 artifact 的 content_comparison 都是
  unknown；索引 unchanged 绝不意味着文件内容相同，也不重新读取当前文件伪造历史 hash。
- 保存的元数据一致不证明 RTL/PDK/SDC 内容一致；不作为 tapeout 判定或阈值 gate。

#### 校验与错误矩阵

支持当前 runtime 已支持的 snapshot schema，不迁移输入。单文件上限使用现有
`ENGINEERING_SNAPSHOT_MAX_BYTES`（16 MiB）。保存文件读取复用 snapshot schema 和路径
校验，但不使用文件旁边的 workspace command metadata 重新绑定历史身份。

| 情况 | 结果 | 退出码 |
| --- | --- | --- |
| 完成比较，包括 regressed/mixed/unknown | `run_comparison`，status=success | 0 |
| 缺少参数或同时使用 --plain/--json | 公共 CLI 参数错误 | 2 |
| 缺失、不可读、非法 JSON、超限、压缩输入、非有限数或非法 schema | `snapshot_read_failed`，含 role/path/reason | 1 |
| 非法 metric/step 投影、重复比较键 | `snapshot_compare_failed`，含 reason | 1 |

同文件比较合法。有有效 metric 时得到 unchanged；完全无数据时不能声称质量未变，
summary 为 unknown。对两侧文件不加锁，不支持可靠比较正在写入的文件。

#### 开发接口与测试点

```python
read_engineering_snapshot_file(path: str | Path) -> dict[str, Any]
compare_snapshots(baseline: dict, current: dict) -> dict
```

文件读取归 engine/snapshot 所有，纯比较归 engine/snapshot_compare 所有。CLI 使用
独立 typed input、command handler、shared create_app/execute_command 和渲染注册。
不加载 workspace、不执行 EngineFlow、不生成报告、不创建目录或锁。

测试覆盖：三种输出、输入大小/编码/schema/路径、重复键、正负数/零/缺失/布尔/非有限数、
单位与分析上下文、QoR profile、同文件、回归退出码、artifact 身份语义和只读性。

错误：以相同 artifactId 推断 GDS 内容相同；把缺失 WNS 当 0。
正确：内容比较标 unknown；缺失值保留 null 并给出 value_unavailable。

### 12.7 project — 项目工作区 QoR / step / checker 矩阵

```bash
ecc report project --project /path/to/project
ecc report project --project /path/to/project --json
ecc report project --project /path/to/project --plain
```

在项目根目录或其受管工作区根目录可省略 --project。显式 --workspace 不用于此
项目级报告。首版无 --output，终端输出可通过 shell 重定向保存。

#### 矩阵与排序

读取清单中全部工作区，包括 archived 和合法外部工作区，不扫描无关项目子目录。
每行包含 workspace、QoR 分数、flow 总状态、清单状态，以及 step/tool 状态列。
列集按清单与各 flow 的已有顺序取并集，与 QoR 排序后的行顺序无关；不声称
不同 flow 存在统一执行拓扑。相同步骤使用不同 tool 时是不同列。

- 有效 QoR 分数降序，真实 0 分保留，相同分数维持清单顺序。
- 缺失、损坏、NOT_RATED、身份不匹配或陈旧分数为 null，排在末尾，rank=null。
- QoR 使用既有 home/qor_report.json 与 QoR v3 校验，不创建另一套评分算法。
- QoR flow_steps 必须匹配当前 flow 状态；运行中的记录带 provisional=true。
- flow 总状态复用 ecc status，与 manifest_status 分开。局部重跑可能为 partial，
  checker 运行 success 不意味着无违例。
- 确定不在该 flow 的步骤显示 N/A；flow 无法读取时，缺失列显示 unknown。
- 不同评分 profile 会警告不可直接比较；排序不是签核、tapeout 或最佳设计结论。

#### checker 证据

分类复用 flow category 与 canonical FlowStepCategory，不根据工具名称猜测。
只有当前成功步骤的匹配证据才可读取 count；未启动、运行中、失效或失败步骤，
即使旧文件还在，也不得显示当前 clean 或零违例。

| Checker | 显示依据 | 数量语义 |
| --- | --- | --- |
| DRC | schema-v3 metrics 的 drc_count | 单个明确非负整数 count |
| LVS | schema-v3 metrics 的 lvs_count | 单个明确非负整数 count |
| STA | setup/hold violation count | 分项保留，不跨 corner 相加，不给混合总数 |
| postRouteLec | 已有 result.json 的 proven 状态 | proven_saved；不验证 netlist 内容，数量和当前 has_violations 均为 null |
| RCX / powerAnalysis / 自定义 checker | 执行状态 | 无通用违例计数则 not_applicable，count=null |

计数必须与 step/tool、success 状态和 count 单位匹配；布尔、负数、分数、非有限数、
重复/缺失候选或明确无效的 metric selector 不会变成零。STA 缺少一项时，已知非零
项可证明存在违例；只有全部要求项都为零才能标 clean，不伪造缺失数量。

不把 failed checklist 条目数、WNS/TNS、corner 数量、missing corner 数或执行失败
解释成物理违例数量。文件为已保存事实，状态匹配不证明内容指纹或全局签核完整性。

#### JSON / plain 契约

JSON 顶层沿用记录数组。真实首条记录示例（节选，`columns`/`workspaces` 数组按 flow 顺序展开）：

```json
[
  {
    "report": "project",
    "schema_version": 1,
    "project": "/path/to/project",
    "design": "gcd",
    "status": "partial",
    "sort": "qor_score_descending_missing_last_manifest_order_ties",
    "columns": [
      {"step": "Synthesis", "token": "synthesis", "tool": "yosys"},
      {"step": "preFloorplan", "token": "pre_floorplan", "tool": "ecc"}
    ],
    "warnings": []
  }
]
```

字段说明：

```text
report=project
schema_version=1
project, design, status, sort
columns=[{step, token, tool}, ...]
workspaces=[{workspace_id, workspace, manifest_status, flow_status, rank, qor, steps}, ...]
warnings=[...]
```

qor 包含 score、availability、scalar_status、profile、scoring_engine、source 与
provisional。每个 step 包含 step、tool、state、category 与 checker（普通步骤为 null）。
checker 包含 availability、verdict、has_violations、violation_count、counts、source。
counts 按 canonical metric ID 分项保存。null 与真实 0/false 必须区分。

plain 使用现有严格行记录序列化：project_report、step_column、workspace、
workspace_step、checker_count、warning。关联以 workspace_id 与 step/tool 为键，
不把嵌套 Python dict 转成字符串。不允许同时使用 --plain 与 --json。

#### 错误、不变性与限制

合法空项目返回空矩阵、status=available、退出码 0。工作区局部缺失保留原行并
标注原因，整体 status=partial，退出码仍为 0；不是所有工作区签核通过的保证。
项目配置错误、坏/缺失 manifest 返回 1；参数错误返回 2。

读取 flow/QoR 使用现有 16 MiB 上限，checker 小报告使用 1 MiB 上限。解析错误、
过度嵌套和越界 symlink 路径按不可用处理，不读取工作区外的证据内容。
不加载或迁移 Workspace、不启动 EDA、不刷新评分或快照、不写入任何报告文件。
项目正在运行时并不锁定所有工作区，不承诺跨文件/工作区原子视图；可在运行结束
后重新查询。要生成或保存单工作区结果，继续使用已有 run/report/snapshot 命令。

## 13. gdsview — 在 KLayout 中打开 GDS

```bash
ecc gdsview --project <project> --workspace <workspace> --step <step>
```

命令会在指定 step 的 `output` 目录中查找唯一的 `*.gds` 或 `*.gds.gz` 文件，
使用 KLayout 的交互式 `LayoutView` 打开，自动展开层次并保持窗口直到用户关闭。
命令不会生成 PNG。

命令启动 KLayout GUI 可执行文件并传入选中的 GDS，不会为 ECC CLI 额外引入
PyQt/PySide，也不会改变 ECOS Studio AppImage 的打包内容。Qt 运行时由
KLayout 自己提供；可执行文件只在执行 `gdsview` 时查找。

并不是每个 flow step 都会生成 GDS。若指定 step 没有 GDS，命令返回
`gds_view_unavailable` 并列出当前 workspace 中有 GDS 的步骤；若存在多个 GDS，
返回 `gds_view_ambiguous` 并列出候选路径。缺少 KLayout GUI 可执行文件或
Linux 图形环境时，也会返回独立的诊断，不会静默切换到其他步骤。

```bash
ecc gdsview --workspace default --step Harden
```

## 14. chipview — 打开保存的 geometry 版图

```bash
ecc chipview --project <project> --workspace <workspace> --step <step>
```

该命令打开与 ECOS Studio 点击版图缩略图相同的原生 Chip Viewer。命令读取
`<step>/output/geometry/geometry.manifest` 及其 sidecar 文件，不读取 GDS，
也不生成 PNG。请从 ECOS Studio AppImage 的内置终端运行，以便
`ECOS_CHIP_VIEWER_BIN` 指向 AppImage 内的 `chip-viewer-native`；开发环境也
可以通过该变量显式指定可执行文件。

命令启动前会检查项目、workspace、flow step、geometry manifest、Viewer
可执行文件和 Linux 图形环境。缺少任一条件时会返回明确的错误原因、期望路径
和修复建议。Viewer 的 stdout/stderr 保存在
`<workspace>/.chip-viewer/logs/`。

命令支持 `--plain`（输出稳定的 `key=value` 记录）和 `--json`（输出 JSON
记录数组）。成功记录包含 `status=started`、step、manifest 路径、Viewer
路径、Viewer PID 以及日志路径。workspace/geometry、Viewer、显示环境或
Viewer 启动失败时返回退出码 `1`，常见错误码包括
`chipview_step_not_found`、`chipview_geometry_invalid`、
`chipview_viewer_unavailable`、`chipview_display_unavailable` 和
`chipview_launch_failed`。

AppImage 不作为 GDS 输入解析。命令只要求 AppImage 内的
`chip-viewer-native` 可被发现：ECOS Studio 内置终端会注入
`ECOS_CHIP_VIEWER_BIN`，也可以使用
`ECOS_ELECTRON_RESOURCES_PATH/binaries/chip-viewer-native` 或 PATH。若找不到
可执行 Viewer，请从 AppImage 内置终端运行，或显式设置
`ECOS_CHIP_VIEWER_BIN`；命令不会回退到 `gdsview`。

## 15. 端到端典型工作流

```bash
ecc init gcd && cd gcd
# 放入 RTL，编辑 ecc.toml（top/clock/frequency、pdk.root、flow.preset）——
# 也可以不打开编辑器，直接用命令声明：
ecc project set design.top gcd && ecc project add design.rtl rtl/gcd.v
ecc pdk set-root ~/pdk/icsprout55-pdk   # （可选）手动下载的 PDK 用这条接入
ecc doctor                         # 环境体检（PDK/yosys/slang/组件）
ecc check                          # 项目配置校验通过再运行
ecc run --preset rtl2gds           # 一次性跑完整链（Synthesis→…→Harden）
ecc run                            # 再跑一次：已成功 → no_op；中断/失败 → 自动续跑
ecc status                         # 看步骤状态；失败时：
ecc log placement                  # 看出错步骤日志（TEXT 模式自动高亮错误行）
ecc param set place.target_density 0.55   # 调参数后重跑
ecc run --overwrite --preset rtl2gds
ecc param set place.target_density 0.65 --workspace default   # 或只局部调一个 workspace 的参数，不动 ecc.toml
ecc run --workspace default        # 从失效步骤继续跑
ecc run --workspace default --only place --force   # 或原地单步复跑（已成功需 --force）
ecc run --workspace default --from CTS --to route  # 或原地重跑一段（用持久化名）
ecc workspace refresh default      # ecc.toml 的输入/PDK/preset 变了，重建 workspace 但不执行
ecc config place                   # 查看该步实际生效的配置文件
ecc signoff inspect                # 签核就绪度（blocked 也 rc=0）
ecc signoff export -o gcd_signoff.tar.gz    # 就绪后导出签核包
ecc report summary                 # 生成文本设计总结（signoff/<design>_design_summary.txt）
ecc report qor                     # QoR 总分报告（signoff/<design>_qor_report.txt）
ecc report checklist               # 签核清单报告（signoff/checklist_report.txt）
ecc report step drc                # 终端预览单步骤 feature/analysis/checklist（只读）
ecc gdsview --workspace default --step Harden
ecc chipview --workspace default --step Harden
```

创建多个受管 workspace 做对比实验（每个独立目录、互不干扰）：

```bash
# `--workspace` 在创建前自动登记到 project.json。
ecc init gcd && cd gcd
ecc run --workspace baseline --preset rtl2gds                 # 基线：默认参数
ecc run --workspace exp1 --preset rtl2gds --set place.target_density=0.65
ecc status --workspace exp1
ecc log --workspace exp1
ecc report qor --workspace baseline    # 两个 run 的 QoR 报告分别对比
ecc report qor --workspace exp1

# 已有现成综合网表时，也可以从中间步骤起建范围 workspace（入口输入要求见 §5.1）：
ecc run --workspace pnr --from prefloorplan --to route
```

含硬宏的设计可改用手工摆放（完整说明见 §9.5）：

```bash
ecc macro set u_ram0 --x 10 --y 20.5 --orient R0 --workspace default
ecc run --workspace default   # 从 macroPlacement 续跑：跳过 DreamPlace，按手工位置提交宏
ecc macro show --workspace default
```

`project.json` 生成后，项目级查看、签核和报告命令按已声明的 workspace 选择；只有一个活跃 workspace 时自动选中，多个活跃 workspace 时必须显式传 `--workspace NAME`（否则报 `workspace_required` 并列出可用名称）。不再使用的 workspace 可在 `project.json` 中把其 `status` 改为 `archived`，使其退出自动选择。

## 16. 自动化使用与安全边界

本节面向自动化代理（agent）、脚本和批量实验补充操作约束，前文的命令契约仍然有效。

### 16.1 公开边界与状态判定

- 项目、workspace、参数、宏、PDK、运行、报告和签核状态，一律只通过公开的 `ecc` CLI 修改。
- 不要绕过 CLI 直接编辑 `ecc.toml`、`project.json`、`home/params.toml`、`home/flow.json`、受管的 JSON/Tcl、分析报告或 checklist。
- CLI 尚未暴露的字段，如实报告能力缺口（capability gap）即可；不要编造命令，也不要强行写内部文件。`--plain` 输出要按重复的 `key=value` 记录来解析——它不是 JSON，也不要对它用 `eval` 或 `source`。
- CLI 执行成功、请求的 flow 完成、QoR/签核门禁通过、导出物可复现，这四件事要分开报告。缺失的数据不是零；ECC 的 export-ready 也不等于代工厂的 tapeout 认证。

### 16.2 实验、恢复与诊断

默认串行执行，同一个 workspace 不要并发地运行、调参、刷新或导出。每个新候选都用新 workspace，并记录输入、PDK/库、工具版本、参数覆盖（override）、seed、线程数、设备、资源预算和原始报告。恢复运行前先查看 `status`、`log` 和 ledger，优先用 `--resume` 或按精确范围重跑；不要未经确认就 `--overwrite`、删目录或杀掉无关进程。失败时保留第一个错误及其上下文，然后按顺序排查：版本、项目声明、workspace 注册、`doctor`、PDK/库文件、入口输入、失败步骤的日志。不要靠放宽约束、降低频率、删除 corner 或跳过验证来"制造成功"。
### 16.3 自动化契约：退出码与打包 smoke

`ecc signoff check` 即使门禁不通过也会输出完整 JSON 记录。自动化脚本应同时检查
汇总记录和进程退出码：`0` 表示通过，`6` 表示必需门禁失败，`7` 表示由于证据缺失、
过期或不明确而无法评级。参数错误仍为 `2`；已有 workspace/process 退出码（`20`–`23`）
保持不变。

可以使用真实项目验证打包后的可执行文件，不需要导入源码树：

```bash
python packaging/cli_smoke.py \
  --binary dist/ecc \
  --project /path/to/gcd \
  --workspace default
```

smoke runner 会依次检查 `status`、`report step`、`report project`、`signoff check` 和
`pdk verify`，要求每个命令输出非空 JSON 记录数组，并保留质量门禁的非零退出码供 CI 汇报。
