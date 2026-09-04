# ECC CLI 用户指南（当前支持的全部命令）

`ecc` 是 ECOS Chip Compiler 的项目制命令行入口，覆盖 RTL-to-GDS 流水的建项、校验、运行、状态/日志/配置查询、参数管理、签核与报告。本文基于 `ecc/` 子模块当前源码（v0.1.0-alpha.11）整理，所有示例输出均为真实执行结果（示例中的 run 状态为手工构造的演示数据）。

- 源码位置：[chipcompiler/cli/](../chipcompiler/cli/)
- 命令扩展开发方式见同目录 [ecc-cli-dev.cn.md](ecc-cli-dev.cn.md)
- RPC sidecar 协议详见 [workspace-cli.md](workspace-cli.md)

## 0. 调用方式

### 一键安装（推荐）

仓库自带安装脚本 [ecc-cli-setup.sh](ecc-cli-setup.sh)（本目录）：下载安装 ecc CLI、配置 PATH、自检环境、并补齐缺失的 PDK（icsprout55-pdk + liberty/GDS）、Yosys（OSS CAD Suite 最新版，含 slang 前端；LEC 等价性检查复用该 yosys）与 Timing optimization 所需的 Sizer（存在预编译 ecc-sizer 包时自动安装）。幂等可重复运行，已就绪的部件自动跳过：

```bash
bash ecc-cli-setup.sh                 # 一键安装 + 自检 + 补齐
bash ecc-cli-setup.sh --check-only    # 只做环境体检，不安装任何东西
bash ecc-cli-setup.sh --force         # 强制重装 ecc CLI
bash ecc-cli-setup.sh --skip-pdk --skip-tools --skip-sizer   # 只装 ecc CLI 本体；必需依赖未就绪时最终自检会失败
bash ecc-cli-setup.sh --no-shell-rc   # 不修改 shell rc（默认会幂等地写入加载行）
```

可配置项（环境变量覆盖，版本/地址变化时改这里，无需改脚本）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ECC_VERSION` | `latest` | ecc 发行版 tag（如 `v0.1.0-alpha.11`） |
| `ECC_RELEASE_BASE` | ecc 官方 Releases 页 | 发行页地址（换镜像/换仓库时改） |
| `ECC_ASSET_NAME` | `ecc-cli-linux-x86_64.tar.gz` | 资产名（布局变化时改） |
| `ECC_CLI_URL` | 空 | 完整直链或本地压缩包路径，优先级最高 |
| `ECC_INSTALL_DIR` | `~/.local/ecc` | 安装目录 |
| `ECC_PDK_DIR` | `~/.local/icsprout55-pdk` | PDK 目录（仓库地址固定为 https://github.com/openecos-projects/icsprout55-pdk.git） |
| `ECC_OSS_CAD_DIR` | `~/.local/oss-cad-suite` | OSS CAD Suite 目录（Yosys） |
| `OSS_CAD_URL` | 空 | OSS CAD Suite 完整直链覆盖（默认自动取最新发行版） |
| `OSS_ARCH_PATTERN` | `linux-x64` | OSS CAD Suite 资产架构匹配串（非 x86_64 时改） |
| `ECC_SIZER_DIR` | `~/.local/ecc-sizer` | Sizer 安装根目录（含 `bin/Sizer` 与 `src/sizer_os.tcl`） |
| `ECC_SIZER_URL` | 空 | ecc-sizer 预编译包完整直链覆盖（官方无 Release 时可手动指定） |
| `GH_PROXY` | 空 | GitHub 下载代理前缀（如 `https://gh-proxy.org/`），直连不畅时使用 |

脚本产出 `~/.ecc-env.sh`（PATH（含 Sizer 的 bin）+ `CHIPCOMPILER_ICS55_PDK_ROOT` + `CHIPCOMPILER_OSS_CAD_DIR` + 装有 Sizer 时的 `CHIPCOMPILER_ECC_SIZER_ROOT`），并幂等地让 `~/.bashrc`/`~/.zshrc`（以及 bash 登录 shell 的 `~/.profile`）加载它；另建 `~/.local/bin/ecc` 软链接。网络受限环境示例：

```bash
GH_PROXY=https://gh-proxy.org/ bash ecc-cli-setup.sh
```

### 本地源码构建包

安装本地 checkout 构建的 bundle 时，先打包再把安装器指向该压缩包。
`ECC_CLI_URL` 接受绝对本地路径或 `file://` URL；本地文件直接复制，不经过
`GH_PROXY`。

```bash
cd ecc
bash docs/ecc-cli-local-build.sh

# 替换 CLI 并补齐必需依赖。
ECC_CLI_URL="$PWD/dist/release/ecc-cli-linux-x86_64.tar.gz" \
  bash docs/ecc-cli-setup.sh --force
```

PDK、Yosys 与 Sizer 都已就绪时，只替换 CLI：

```bash
ECC_CLI_URL="file://$PWD/dist/release/ecc-cli-linux-x86_64.tar.gz" \
  bash docs/ecc-cli-setup.sh --force --skip-pdk --skip-tools --skip-sizer
```

最终自检仍要求全部必需依赖就绪，否则会以非零状态退出。

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

> 注意「官方发行版」与「源码构建版」的差异：`ecc doctor / signoff / report` 等新命令目前只在**源码构建版**里有（官方 Releases 尚未发布）。本地改完代码可用 PyInstaller 重打包并覆盖 `~/.local/ecc`（流程见 [ecc-cli-dev.cn.md §6](ecc-cli-dev.cn.md)）；重新运行 `bash ecc-cli-setup.sh --force` 则会装回官方发行版（新命令随之消失，属预期回退行为）。

> 注：`ecc` 的项目定位默认取当前目录（`ecc.toml` 所在处），所以「任意文件夹启动」是常态用法；在其他目录操作项目时加 `--project <dir>` 即可。

### 源码运行

```bash
# Nix（ecc 仓库内）
nix run . -- --help

# uv 开发环境（ecc 仓库内）
uv run ecc --help
```

## 1. 通用约定

- 全局：`ecc --version`（单行版本号）、`ecc --help`。
- 项目定位：项目级命令接受 `--project <dir>`（缺省为当前目录），其中与 run 有关的命令还接受 `--run-id <id>`。**新项目**（没有 `project.json`、没有 `runs/`）首个 workspace 落在 `<project>/<run-id>`，并自动生成 `project.json` 登记。**manifest 项目**从其中已声明的 workspace 表解析查看类命令（恰有一个活跃 workspace 时自动选中）；id 必须是非空单个路径段。`ecc run --run-id` 可以创建未声明的单路径段 workspace，但会给出 `workspace_not_registered`；之后项目级 `status`、`log`、`config`、`signoff` 和 `report` 无法选中它。**legacy 项目**（有非空 `runs/`）仍使用 `runs/<run-id>`，接受绝对路径或含 `/` 的相对路径，并可用 `ecc migrate` 升级。三种状态都可带 `ecc.toml`；只有缺少 `ecc.toml` 的 manifest 项目会被 `ecc param` 拒绝（`param_requires_ecc_toml`）。
- 结构化输出：`init`、`check`、`run`、`status`、`log`、`config`、`migrate`、`doctor`、`param`、`pdk`、`signoff`、`report` 都支持 `--json`（`{"records":[...]}`）、`--jsonl`（每行一条记录）和 `--plain`（`key=value`，便于脚本解析），缺省为人类可读 TEXT。`ecc version` 也支持这三种选项，但使用版本专用 schema；`rpc serve` 和 `layout-image` 使用各自的协议。
- 退出码：成功 0；业务失败 1（错误记录形如 `[error] error=<机器可读错误码>`）。
- 步骤名（step token）在展示层统一为小写：`synthesis / lec / floorplan / placement / cts / legalization / timing optimization / routing / filler / lvs / drc / postroutelec / rcx / sta / harden`；`--from`/`--only` 需用 `home/flow.json` 中的原始名（如 `place`、`CTS`、`Timing optimization`）。

命令总览：

```
$ ecc --help
Commands:
  version       Show ECC runtime, component, and installed tool versions
  layout-image  Render a GDS file into a layout image
  init          Create a new ECC project
  check         Validate the current project setup
  run           Run the configured RTL-to-GDS flow
  status        Show a quick run/step progress summary (full evidence:...)
  log           Show available logs or step log content
  config        Show resolved project or step configuration
  migrate       Migrate a legacy runs/ project to the manifest layout
  doctor        Check host environment: PDK, tools, and components
  param         Manage EDA parameters
  pdk           Show and configure the PDK path used by this project
  signoff       Inspect and export signoff packages
  report        Generate design-summary, QoR score, checklist, and step reports
  rpc           Run the private ECC JSON-RPC runtime
```

## 2. version — 查看版本

```bash
ecc version           # 文本
ecc version --json    # JSON（含 schema_version/ecc/dreamplace/ecc_tools/tools）
ecc version --jsonl   # 每行一个 {"component", "version"} 对象
ecc version --plain   # 一条 key=value 记录
ecc --version         # 仅一行 ecc 版本
```

前四行是捆绑组件元数据（Python 包版本）。`yosys` / `sizer` / `klayout`
三行按流程运行时相同的方式从当前环境解析，显示工具二进制自身的版本；
工具缺失时显示 `not installed`，无法查询版本时显示 `unknown`。

```console
$ ecc version
ecc 0.1.0a11
dreamplace 0.1.0a7
ecc_tools 0.1.0a12
runtime ECC CLI
yosys 0.68+132
sizer not installed
klayout 0.30.2

$ ecc version --json
{"schema_version": 1, "runtime": "ECC CLI", "ecc": "0.1.0a11", "dreamplace": "0.1.0a7", "ecc_tools": "0.1.0a12", "tools": {"yosys": "0.68+132", "sizer": "not installed", "klayout": "0.30.2"}}
```

## 3. init — 创建项目

```bash
ecc init <NAME> [--json | --jsonl | --plain]
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
rtl = ["rtl/gcd.v"]      # 单个 Verilog 文件，或多源时指向一个 filelist（如 rtl/filelist.f）
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"           # 目前支持 ics55
root = ""                # icsprout55-pdk 路径；留空则用 CHIPCOMPILER_ICS55_PDK_ROOT / ICS55_PDK_ROOT 环境变量

[flow]
# preset: rtl2gds | syn_sta | synthesis_lec
preset = "rtl2gds"
run = "default"          # run id（workspace 默认 <项目>/<id>；legacy 项目为 runs/<id>）
```

## 4. check — 校验项目配置

```bash
ecc check [--project DIR] [--json | --jsonl | --plain]
```

校验 `ecc.toml` 必填项、RTL 路径/filelist 有效性、PDK 名称与内容（tech LEF/LEF/liberty）：

```console
$ ecc check        # RTL 未就绪时
[check]
  fail pdk.root is required
  inspect: ecc check --json
  fail rtl path does not exist: rtl/gcd.v
  inspect: ecc check --json
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
  inspect: ecc check --json
rc=0
```

### 环境自检：ecc doctor

`ecc doctor` 一条命令体检全部依赖（PDK、yosys 含 slang 前端、随包捆绑的 ecc-tools/dreamplace、必需的 Sizer，以及可选的 KLayout），每项给出 pass/fail/skip 与修复建议；只有**必需项**失败才返回非零：

```bash
ecc doctor [--project DIR] [--json | --jsonl | --plain]
```

```console
$ ecc doctor          # 在项目目录内执行（PDK 探测需要 ecc.toml 或 --project）
[status]
  doctor: environment
  status: attention          # ok=全过 / attention=仅可选项失败(rc=0) / failed=必需项失败(rc=1)
  checked: 7
  failed: 0                  # failed 只统计必需项失败；可选项失败计入 attention
  attention: 1
  run: ecc run
  component: yosys
  status: pass
  detail: ~/.local/oss-cad-suite/bin/yosys
  component: yosys-slang
  status: pass
  detail: read_slang frontend available
  component: ecc-tools       # 其余组件同理：dreamplace / klayout / sizer / pdk
  ...
```

此外，对新建或 `--overwrite` 的目标，`ecc run` 会预检捆绑 ecc-tools、含综合的 preset 所需 Yosys、含布局/合法化的 preset 所需 DreamPlace，以及含 Timing optimization 的 preset 所需 Sizer（包括 `rtl2gds`）；这些组件缺失时会以 `env_not_ready` fail-fast：

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
- 安装/补齐环境的脚本：`bash docs/ecc-cli-setup.sh`（见第 0 节，`--check-only` 只体检）。

### 手动排查清单（无 doctor 时备用）

`ecc check` 只覆盖「项目配置 + RTL + **PDK 内容**（tech LEF / LEF / liberty）」，**不检查外部工具**。手动逐项确认：

| 依赖 | 检查命令 | 就绪标志 |
|---|---|---|
| Python 组件（ecc-tools / dreamplace，随 CLI 捆绑） | `ecc version` | `ecc_tools` / `dreamplace` 显示版本号而非 `unknown` |
| PDK（ics55） | `ecc check` | `status: checked`；liberty 缺失时按 README 执行 `make unzip` |
| Yosys（综合） | `which yosys && yosys -V`，或 `echo $CHIPCOMPILER_OSS_CAD_DIR` | 二者其一可用（优先 `CHIPCOMPILER_OSS_CAD_DIR` 指向 OSS CAD Suite） |
| Yosys slang 前端 | `yosys -Q -T -p "help read_slang"` | 输出**不含** `No such command`（yosys ≥ v0.67 内置；旧版需可加载的 slang 插件） |
| KLayout（仅 `layout-image` 需要） | `python3 -c "from klayout import lay"` | 无 ImportError |
| Sizer（`ecc doctor` 的必需组件；完整 rtl2gds 链的 Timing optimization 步骤需要） | `which Sizer`；可选 `echo $CHIPCOMPILER_ECC_SIZER_ROOT` | 可执行文件和含 `src/sizer_os.tcl` 的 root 均须可解析；root 可显式设置，或由二进制位置自动发现。新建或 `--overwrite` 的 `rtl2gds` 会在预检检查 Sizer；已有 workspace 或 `--workspace` 重跑不预检，缺失时仍可能在流中段失败 |

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
  --run-id TEXT      run id（缺省读 [flow] run / default）
  --preset TEXT      本次运行的 flow preset 覆盖（不写回 ecc.toml），如 --preset syn_sta
  --overwrite        覆盖已存在的 run（仅删除真正的 ECC run 目录，含安全校验）
  --set KEY=VALUE    参数覆盖，可重复（如 --set place.target_density=0.65），会记录到 run 的 provenance
  --json / --jsonl / --plain
```

新建或 `--overwrite` 的 run 会按以下流程执行：读 `ecc.toml` → 解析 RTL/PDK/参数 → 预检捆绑的 ecc-tools，以及 preset 选中的 Yosys、DreamPlace 和 Sizer（仅含 Timing optimization 的 flow，如 `rtl2gds`）→ 在解析出的 run 目标下创建 workspace（新项目为 `<project>/<run-id>` 并写入 `project.json` 登记；legacy 项目为 `runs/<run-id>`）→ 按 preset（`rtl2gds | syn_sta | synthesis_lec`）构建步骤并执行（TTY 下有进度渲染）。已有 workspace 直接按持久化 flow 续跑，不做 preset 预检；因此已有 workspace 或 `--workspace` 模式缺 Sizer 时，仍可能在 Timing optimization 步骤失败。`rtl2gds` 是完整 15 步链（Synthesis→LEC（Yosys 等价性检查）→Floorplan→place→CTS→legalization→Timing optimization（sizer）→route→filler→LVS→DRC→postRouteLec（Yosys 等价性检查）→RCX→sta→Harden，Harden 产出 GDS + 抽象 LEF + 时序 LIB）。

```console
$ ecc run                # 该 run 已存在时拒绝覆盖
[error]
  run_exists
  run: default
  workspace: /path/gcd/default
  overwrite: ecc run --overwrite
rc=1

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
ecc run                                        # 首次运行（用 ecc.toml 的 preset）
ecc run --preset rtl2gds                       # 一次性跑完整链至 Harden（GDS/LEF/LIB）
ecc run --run-id exp1 --set place.target_density=0.65
ecc run --run-id exp1 --overwrite              # 重跑同名的 run
```

### 5.2 workspace 模式（调试/复跑）

```bash
ecc run --workspace <dir> [--resume | --from STEP | --only STEP [--force]]
```

- `--resume`：从第一个非成功的步骤继续（不给选择器时的默认行为）；
- `--from STEP`：重跑某步及其后所有步骤；
- `--only STEP [--force]`：只跑一步，`--force` 用于该步已成功时强制重跑；
- 三个选择器互斥；`--workspace` 不能与 `--project/--run-id/--overwrite/--set/--preset` 组合；STEP 名须与 `home/flow.json` 完全一致（如 `place`、`CTS`）；
- 原地修改 workspace：被重跑步骤的 `output/` 会被替换，下游步骤标记为 `Unstart`。

```bash
ecc run --workspace default --resume
ecc run --workspace default --from CTS
ecc run --workspace default --only place --force
```

误在项目模式使用选择器会得到明确报错：

```console
$ ecc run --resume
[error]
  selector_requires_workspace
rc=1
```

### 5.3 migrate — 旧布局迁移（过渡期命令）

```bash
ecc migrate [--project DIR] [--yes] [--json | --jsonl | --plain]
```

把 legacy `runs/` 布局项目迁移到 manifest 布局：每个安全的 `runs/<id>` workspace 都会移动到 `<project>/<id>`，重写 workspace 内部路径，并登记到新建或更新的 `project.json`。缺省先输出迁移计划，确认后才执行；`--yes` 跳过确认。该命令为过渡期保留（代码标注 deprecated），存量项目迁完即可弃用。`run`/`check`/`status` 在 legacy 项目上会自动附带迁移提示记录。

## 6. status — 查看 run 与步骤状态

```bash
ecc status [--project DIR] [--run-id ID | --workspace PATH] [--json | --jsonl | --plain]
```

`status` 是轻量进度速查；完整的分步证据报告用 `ecc report step`（§12.4）。
`--workspace` 指向一个已存在的 workspace 目录，与 `--project`/`--run-id` 互斥。

```console
$ ecc status
[status]
  run: default
  status: failed
  workspace: /tmp/gcd/default
  inspect: ecc status
  log: ecc log

  steps:
    synthesis (yosys) success 0:00:18
      log: ecc log synthesis
    floorplan (ecc) success 0:00:04
      log: ecc log floorplan
    placement (dreamplace) incomplete 0:00:31
      log: ecc log placement
    cts (ecc) unstart

$ ecc status --jsonl
{"run": "default", "status": "failed", "workspace": "/tmp/gcd/default", "inspect_cmd": "ecc status", "log_cmd": "ecc log"}
{"step": "synthesis", "tool": "yosys", "status": "success", "runtime": "0:00:18", "log_cmd": "ecc log synthesis"}
{"step": "floorplan", "tool": "ecc", "status": "success", "runtime": "0:00:04", "log_cmd": "ecc log floorplan"}
...
```

run 级状态取全部步骤的聚合：`success / warning / failed / ongoing / unstart / missing / corrupt`；综合级 LEC 未证明时为 `warning`，但仍保留 LEC 证据并继续物理流程。

## 7. log — 查看日志

```bash
ecc log [STEP] [--project DIR] [--run-id ID | --workspace PATH] [--json | --jsonl | --plain]
```

不带 STEP 列出全部日志文件（run 级 flow 日志 + 各步骤日志，含尾部预览）；带 STEP 打印该步骤日志内容（TEXT 模式高亮 ERROR/WARNING 行）。

```console
$ ecc log
[logs]
  run  log/gcd.2026-09-03_17-34-35
    tail:
      flow : /path/gcd/default/home/flow.json
      name | tool | state | runtime
      Synthesis | yosys | Success | 0:0:15
  synthesis  Synthesis_yosys/log/Synthesis.log
    tail:
      synthesizing gcd...
  inspect: ecc log synthesis

$ ecc log synthesis
[log] step=synthesis
  source: Synthesis_yosys/log/Synthesis.log
        synthesizing gcd...
  inspect: ecc log synthesis

$ ecc log nosuchstep
[error]
  error
  step: nosuchstep
  status: unknown_step
  inspect: ecc status
rc=1
```

## 8. config — 查看解析后的配置

```bash
ecc config [STEP] [--project DIR] [--run-id ID | --workspace PATH] [--json | --jsonl | --plain]
```

`--workspace` 将步骤视图限定到指定 workspace 目录（与
`--project`/`--run-id` 互斥）；项目级视图仍以项目为作用域，读取项目目录
的 `ecc.toml`。

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
  inspect: ecc config floorplan --json
    floorplan_ecc.json (config)
      path: default/config/floorplan_ecc.json
  inspect: ecc config floorplan --json
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
```

通用选项：`--project DIR`、`--json / --jsonl / --plain`。

```console
$ ecc param list
  design
    design.frequency_mhz           100.0  (ecc.toml)
  floorplan
    floorplan.core_util            0.4
    floorplan.core_margin          [2, 2]
    floorplan.aspect_ratio         1.0
  cts
    cts.max_fanout                 20
  place
    place.target_density           0.2
    place.target_overflow          0.1
    place.global_right_padding     0
    place.cell_padding_x           300
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
    range          [0.1, 0.95]
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
| `cts.max_fanout` | int | 20 | [1, 200] | cts |
| `place.target_density` | float | 0.2 | [0.1, 0.95] | placement |
| `place.target_overflow` | float | 0.1 | [0.0, 1.0] | placement |
| `place.global_right_padding` | int | 0 | [0, 100] | placement |
| `place.cell_padding_x` | int | 300 | [0, 10000] | placement |
| `place.routability_opt` | int | 1 | {0, 1} | placement |
| `route.bottom_layer` | str | MET2 | MET1–MET5 | routing |
| `route.top_layer` | str | MET5 | MET2–MET6 | routing |
| `sta.max_paths` | int | 1000 | [1, 100000] | sta |

优先级：CLI `--set` > `ecc.toml` `[params.*]` > 模板默认值。`pdk.*` 路径参数写入 `[pdk.overrides]`：`pdk.tech`、`pdk.lefs`、`pdk.libs`、`pdk.mapping_file` 相对 `pdk.root` 解析，`pdk.sdc` 和 `pdk.spef` 相对项目目录解析；六者都会校验文件。

## 10. pdk — PDK 路径配置

接入 PDK 有两条路：`ecc pdk setup` 一条到位（自动 clone + `make unzip`，已就绪的目录则跳过下载只接入），或对已就绪的 PDK 用 `ecc pdk set-root` 直接接入（写入 `ecc.toml` 的 `[pdk] root`，自动展开为绝对路径；目录必须已存在）。内容不完整（如还没 `make unzip`）不阻断设置，会给出提示：

全部 `pdk` 子命令都支持 `--project DIR` 和 `--json/--jsonl/--plain`。

```bash
ecc pdk setup [~/pdk/icsprout55-pdk]     # 一条到位：clone（缺时）→ make unzip（缺 liberty 时，支持 GH_PROXY+重试）→ 接入；缺省装到 ~/.local/icsprout55-pdk
ecc pdk set-root ~/pdk/icsprout55-pdk   # 仅设置（已就绪的 PDK）
ecc pdk show                             # 查看生效 root 与来源（ecc.toml / 环境变量 / 仓库默认）及内容校验
ecc pdk unset                            # 清空 root，回落环境变量 / 仓库默认
ecc pdk set-root /bad/path               # → [error] invalid_pdk_path（目录不存在）
```

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

`ecc signoff export` 需要就绪的 Harden 签核包。`ecc signoff inspect` 可审阅尚未完成的 workspace。两个子命令都接受 `--project DIR`（可选 `--run-id ID`），或直接指定 workspace 的 `--workspace PATH`，以及 `--json/--jsonl/--plain`。`--workspace` 与 `--project`、`--run-id` 互斥。

### 11.1 inspect — 就绪度审阅

```bash
ecc signoff inspect ([--project DIR] [--run-id ID] | --workspace PATH) [--json | --jsonl | --plain]
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

### 11.2 export — 导出签核包 tar.gz（有门禁）

```bash
ecc signoff export -o <path>.tar.gz [--include-debug] ([--project DIR] [--run-id ID] | --workspace PATH) [--json | --jsonl | --plain]
```

直接指定已有 workspace 时，例如：

```bash
ecc signoff export --workspace /path/to/gcd/default -o /path/to/gcd_signoff_package.tar.gz
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

## 12. report — 设计总结、QoR 总分、checklist 与单步证据

```bash
ecc report summary [-o PATH] ([--project DIR] [--run-id ID] | --workspace PATH) [--json | --jsonl | --plain]
ecc report qor     [-o PATH] ([--project DIR] [--run-id ID] | --workspace PATH) [--json | --jsonl | --plain]
ecc report checklist [-o PATH] [同样的 selector 与输出选项]
ecc report step    [STEP] [--section feature|analysis|checklist]... [同样的 selector 与输出选项]
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

按 GUI 项目看板的计分规则给当前 workspace 打分：每条 v3 `qor_metrics.json` 指标按固定失败阈值折算 0-100 分（slack 类线性、core_utilization 目标区间 [0.45,0.70]、lower/higher_is_better 比例），维度内取平均，再按权重（Timing 0.35 / Power 0.25 / Routability 0.2 / Area 0.1 / Clock-DFM 0.1）加权出总分——**缺项维度不重归一化**（与 GUI 一致，缺项会拉低总分）；60 分为通过线。默认写 `<workspace>/signoff/<design>_qor_report.txt`：

```console
$ ecc report qor --project gcd --plain
report=qor path=.../signoff/gcd_qor_report.txt bytes=1717 design=gcd \
  overall_score=61.8 qor_status=Green gate_status=pass \
  dimensions="[{'dimension': 'Timing', 'score': 75.0, 'weight': 0.35, 'metrics': 2}, ...]" \
  view="cat .../gcd_qor_report.txt" status=written
```

报告含：总分与判定（PASS/BELOW THRESHOLD/NOT RATED）、Flow 状态色（Green/Yellow/Orange/Red/Blocked）与 gate（DRC/LVS/RCX/STA 步骤状态）、Area 计分步（最后一个成功的 area 指标步）、维度表、逐指标明细分（corner 维度独立计分）。

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

step token 与 `ecc log` 同源（`synthesis/floorplan/placement/cts/...`），同时接受 flow 内部名（如 `Timing optimization`）与目录名变体（`timing_optimization`）；未知 token 返回 `unknown_step` 并列出可用值。

```console
$ ecc report step --workspace default
  step                   tool         status    runtime  metrics quality  checklist
  synthesis              yosys        success   0:0:17   10      pass     ready
  ...
  drc                    ecc          success   0:0:3    12      blocked  blocked (1 blocked)

$ ecc report step drc --section analysis
  analysis:
    quality: blocked  (12 metrics, 0 missing)
    ...
    [BLOCK] qor.drc.clean — drc_count=336 == 0
```

## 13. rpc — JSON-RPC runtime sidecar（私有）

```bash
ecc rpc serve --stdio [--persistent-db]
```

供 GUI 等前端使用的 JSON-RPC 2.0 服务，`Content-Length` 帧封装于 stdio。`--persistent-db` 额外开放 `db.ensure` / `db.release` 与 `layout.edit.*` / `floorplan.edit.*` 系列方法。握手与调用示例（完整方法列表和参数见 [workspace-cli.md](workspace-cli.md)）：

```console
→ {"jsonrpc":"2.0","method":"rpc.hello","params":{"version":1},"id":"hello-1"}
← {"jsonrpc":"2.0","result":{"version":1,"eccVersion":"0.1.0a11","capabilities":["rpc.hello","rpc.ping","rpc.shutdown","runtime.v2","operation.events","workspace.create","workspace.open","workspace.close","workspace.home","workspace.info","workspace.refresh_config","workspace.sync_config","workspace.reset_flow","workspace.export_signoff","workspace.inspect_signoff","flow.run","flow.run_step","operation.start_flow","operation.start_step","operation.status","operation.cancel","operation.ack_step_rendered","workspace.snapshot","workspace.recover_interrupted"]},"id":"hello-1"}

→ {"jsonrpc":"2.0","method":"rpc.ping","params":{},"id":"ping-1"}
← {"jsonrpc":"2.0","result":{"ok":true},"id":"ping-1"}
```

## 14. layout-image — GDS 渲染为图片

```bash
ecc layout-image --gds <in.gds> --image <out.png> [--width N] [--height N]
```

基于 KLayout 把 GDS 版图渲染为快照图片（默认 1920×1920；需要环境中有 KLayout）：

```bash
ecc layout-image --gds default/Harden_ecc/output/gcd_Harden.gds --image layout.png --width 2560 --height 1600
```

## 15. 端到端典型工作流

```bash
ecc init gcd && cd gcd
# 放入 RTL，编辑 ecc.toml（top/clock/frequency、pdk.root、flow.preset）
ecc pdk set-root ~/pdk/icsprout55-pdk   # （可选）手动下载的 PDK 用这条接入
ecc doctor                         # 环境体检（PDK/yosys/slang/组件）
ecc check                          # 项目配置校验通过再运行
ecc run --preset rtl2gds           # 一次性跑完整链（Synthesis→…→Harden）
ecc status                         # 看步骤状态；失败时：
ecc log place                      # 看出错步骤日志（TEXT 模式自动高亮错误行）
ecc param set place.target_density 0.55   # 调参数后重跑
ecc run --overwrite --preset rtl2gds
ecc run --workspace default --only place --force   # 或原地单步复跑
ecc config place        # 查看该步实际生效的配置文件
ecc signoff inspect                # 签核就绪度（blocked 也 rc=0）
ecc signoff export -o gcd_signoff.tar.gz    # 就绪后导出签核包
ecc report summary                 # 生成文本设计总结（signoff/<design>_design_summary.txt）
ecc report qor                     # QoR 总分报告（signoff/<design>_qor_report.txt）
ecc report checklist               # 签核清单报告（signoff/checklist_report.txt）
ecc report step drc                # 终端预览单步骤 feature/analysis/checklist（只读）
ecc layout-image --gds default/Harden_ecc/output/gcd_Harden.gds --image gcd.png
```

选择一个可跟踪的 run：

```bash
# 在第一次运行前选定 id，使自动生成的 manifest 登记它。
ecc init gcd && cd gcd
ecc run --run-id exp1 --set place.target_density=0.65
ecc status --run-id exp1
ecc log --run-id exp1
```

`project.json` 生成后，项目级查看、签核和报告命令只会选择已声明的 workspace。CLI 可以运行未声明的单路径段 id，但它不会被登记并会输出 `workspace_not_registered`；需要作为可跟踪的额外 run 使用时，应先通过拥有 manifest 的 UI 增加 workspace 条目。
