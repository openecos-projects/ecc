# ECC CLI 用户指南（当前支持的全部命令）

`ecc` 是 ECOS Chip Compiler 的项目制命令行入口，覆盖 RTL-to-GDS 流水的建项、校验、运行、状态/日志/配置查询与参数管理。本文基于 `ecc/` 子模块当前源码（v0.1.0-alpha.11）整理，所有示例输出均为真实执行结果（示例中的 run 状态为手工构造的演示数据）。

- 源码位置：[chipcompiler/cli/](../chipcompiler/cli/)
- 命令扩展开发方式见同目录 [ecc-cli-dev.cn.md](ecc-cli-dev.cn.md)
- RPC sidecar 协议详见 [workspace-cli.md](workspace-cli.md)

## 0. 调用方式

### 一键安装（推荐）

安装脚本 `ecc-cli-setup.sh`（位于 ecos-studio 仓库的 `.claude/` 目录）：下载安装 ecc CLI、配置 PATH、自检环境、并补齐缺失的 PDK（icsprout55-pdk + liberty/GDS）与 Yosys（OSS CAD Suite 最新版）。幂等可重复运行，已就绪的部件自动跳过：

```bash
bash ecc-cli-setup.sh                 # 一键安装 + 自检 + 补齐
bash ecc-cli-setup.sh --check-only    # 只做环境体检，不安装任何东西
bash ecc-cli-setup.sh --force         # 强制重装 ecc CLI
bash ecc-cli-setup.sh --skip-pdk --skip-tools   # 只装 ecc CLI 本体
bash ecc-cli-setup.sh --no-shell-rc   # 不修改 shell rc（默认会幂等地写入加载行）
```

可配置项（环境变量覆盖，版本/地址变化时改这里，无需改脚本）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ECC_VERSION` | `latest` | ecc 发行版 tag（如 `v0.1.0-alpha.11`） |
| `ECC_RELEASE_BASE` | ecc 官方 Releases 页 | 发行页地址（换镜像/换仓库时改） |
| `ECC_ASSET_NAME` | `ecc-cli-linux-x86_64.tar.gz` | 资产名（布局变化时改） |
| `ECC_CLI_URL` | 空 | 完整直链，优先级最高 |
| `ECC_INSTALL_DIR` | `~/.local/ecc` | 安装目录 |
| `ECC_PDK_DIR` | `~/.local/icsprout55-pdk` | PDK 目录（仓库地址固定为 https://github.com/openecos-projects/icsprout55-pdk.git） |
| `ECC_OSS_CAD_DIR` | `~/.local/oss-cad-suite` | OSS CAD Suite 目录（Yosys） |
| `OSS_CAD_URL` | 空 | OSS CAD Suite 完整直链覆盖（默认自动取最新发行版） |
| `GH_PROXY` | 空 | GitHub 下载代理前缀（如 `https://gh-proxy.org/`），直连不畅时使用 |

脚本产出 `~/.ecc-env.sh`（PATH + `CHIPCOMPILER_ICS55_PDK_ROOT` + `CHIPCOMPILER_OSS_CAD_DIR`），并幂等地让 `~/.bashrc`/`~/.zshrc` 加载它；另建 `~/.local/bin/ecc` 软链接。网络受限环境示例：

```bash
GH_PROXY=https://gh-proxy.org/ bash ecc-cli-setup.sh
```

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
ln -s ~/.local/ecc/ecc ~/.local/bin/ecc

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
- 项目定位：多数命令接受 `--project <dir>`（缺省为当前目录，需含 `ecc.toml`）与 `--run-id <id>`（缺省用 `ecc.toml` 里 `[flow] run`，再缺省为 `default`，对应 `runs/<id>/`；也接受绝对路径或含 `/` 的相对路径）。
- 输出模式（inspect 类命令通用）：`--json`（`{"records":[...]}`）、`--jsonl`（每行一条记录）、`--plain`（`key=value`，便于脚本解析）、默认人类可读 TEXT。
- 退出码：成功 0；业务失败 1（错误记录形如 `[error] error=<机器可读错误码>`）。
- 步骤名（step token）在展示层统一为小写：`synthesis / floorplan / fixfanout / placement / cts / legalization / routing / drc / filler`；`--from`/`--only` 需用 `home/flow.json` 中的原始名（如 `place`、`CTS`）。

命令总览：

```
$ ecc --help
Commands:
  version       Show ECC runtime and component versions
  layout-image  Render a GDS file into a layout image
  init          Create a new ECC project
  check         Validate the current project setup
  run           Run the configured RTL-to-GDS flow
  status        Show run and step status
  log           Show available logs or step log content
  config        Show resolved project or step configuration
  doctor        Check host environment: PDK, tools, and components
  param         Manage EDA parameters
  signoff       Inspect and export signoff packages
  report        Generate QoR score and signoff checklist reports
  rpc           Run the private ECC JSON-RPC runtime
```

## 2. version — 查看版本

```bash
ecc version          # 文本
ecc version --json   # JSON（含 schema_version/ecc/dreamplace/ecc_tools）
ecc --version        # 仅一行 ecc 版本
```

```console
$ ecc version
ecc 0.1.0-alpha.11
dreamplace 0.1.0a7
ecc_tools 0.1.0a11
runtime ECC CLI

$ ecc version --json
{"schema_version": 1, "runtime": "ECC CLI", "ecc": "0.1.0-alpha.11", "dreamplace": "0.1.0a7", "ecc_tools": "0.1.0a11"}
```

## 3. init — 创建项目

```bash
ecc init <NAME> [--plain]
```

在 `NAME/` 下生成 `ecc.toml`、`rtl/`、`constraints/`、`runs/` 骨架：

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
# preset: rtl2gds | rcx | harden | syn_sta
preset = "rtl2gds"
run = "default"          # run id，对应 runs/<id>/
```

## 4. check — 校验项目配置

```bash
ecc check [--project DIR] [--json | --plain]
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

`ecc doctor` 一条命令体检全部依赖（PDK、yosys 含 slang 前端、随包捆绑的 ecc-tools/dreamplace、可选的 klayout/sizer），每项给出 pass/fail/skip 与修复建议；只有**必需项**失败才返回非零：

```bash
ecc doctor [--project DIR] [--json | --jsonl | --plain]
```

```console
$ ecc doctor          # 在项目目录内执行（PDK 探测需要 ecc.toml 或 --project）
[status]
  doctor: environment
  status: attention          # ok=全过 / attention=仅可选项失败(rc=0) / failed=必需项失败(rc=1)
  checked: 7
  failed: 1
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

此外 `ecc run` 启动前会自动预检所选 preset 必需的工具（yosys↔含综合、dreamplace↔含布局/合法化），缺失则 fail-fast：

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

- PDK 根目录解析优先级：`ecc.toml` 的 `pdk.root` > 环境变量 `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT`。
- 综合步骤内部仍有 slang fail-fast（日志报 `yosys slang frontend check failed`），事后排查用 `ecc log synthesis`。
- 安装/补齐环境的脚本：`bash ecc-cli-setup.sh`（见第 0 节，`--check-only` 只体检）。

### 手动排查清单（无 doctor 时备用）

`ecc check` 只覆盖「项目配置 + RTL + **PDK 内容**（tech LEF / LEF / liberty）」，**不检查外部工具**。手动逐项确认：

| 依赖 | 检查命令 | 就绪标志 |
|---|---|---|
| Python 组件（ecc-tools / dreamplace，随 CLI 捆绑） | `ecc version` | `ecc_tools` / `dreamplace` 显示版本号而非 `unknown` |
| PDK（ics55） | `ecc check` | `status: checked`；liberty 缺失时按 README 执行 `make unzip` |
| Yosys（综合） | `which yosys && yosys -V`，或 `echo $CHIPCOMPILER_OSS_CAD_DIR` | 二者其一可用（优先 `CHIPCOMPILER_OSS_CAD_DIR` 指向 OSS CAD Suite） |
| Yosys slang 前端 | `yosys -Q -T -p "help read_slang"` | 输出**不含** `No such command`（yosys ≥ v0.67 内置；旧版需可加载的 slang 插件） |
| KLayout（仅 `layout-image` 需要） | `python3 -c "from klayout import lay"` | 无 ImportError |
| Sizer（仅部分 flow 需要） | `which Sizer` | 输出路径 |

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

- PDK 根目录解析优先级：`ecc.toml` 的 `pdk.root` > 环境变量 `CHIPCOMPILER_ICS55_PDK_ROOT` > `ICS55_PDK_ROOT`。
- ECC-Tools / DreamPlace 以 Python wheel（`ecc-tools-bin`、`ecc-dreamplace`）形式捆绑在 CLI 包内，正常安装即就绪。

## 5. run — 执行 flow

### 5.1 项目模式（常规）

```bash
ecc run [OPTIONS]
  --project TEXT     项目目录（缺省 cwd）
  --run-id TEXT      run id（缺省读 [flow] run / default）
  --preset TEXT      本次运行的 flow preset 覆盖（不写回 ecc.toml），如 --preset harden
  --overwrite        覆盖已存在的 run（仅删除真正的 ECC run 目录，含安全校验）
  --set KEY=VALUE    参数覆盖，可重复（如 --set place.target_density=0.65），会记录到 run 的 provenance
  --json / --jsonl / --plain
```

流程：读 `ecc.toml` → 解析 RTL/PDK/参数 → 预检 preset 必需工具 → 在 `runs/<run-id>/` 创建 workspace → 按 preset（`rtl2gds | rcx | harden | syn_sta`）构建步骤并执行（TTY 下有进度渲染）。`harden` 是完整 13 步链（Synthesis→…→DRC→LVS→filler→RCX→sta→Harden，Harden 产出 GDS + 抽象 LEF + 时序 LIB）。

```console
$ ecc run                # 该 run 已存在时拒绝覆盖
[error]
  run_exists
  run: default
  workspace: /path/gcd/runs/default
  overwrite: ecc run --overwrite
rc=1

$ ecc run --preset bogus  # 非法 preset（不修改 ecc.toml）
[error]
  unsupported_preset
  preset: bogus
  presets: harden, rcx, rtl2gds, syn_sta
  inspect: ecc config --resolved
rc=1
```

典型用法：

```bash
ecc run                                        # 首次运行（用 ecc.toml 的 preset）
ecc run --preset harden                        # 一次性跑到 Harden（GDS/LEF/LIB）
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
ecc run --workspace runs/default --resume
ecc run --workspace runs/default --from CTS
ecc run --workspace runs/default --only place --force
```

误在项目模式使用选择器会得到明确报错：

```console
$ ecc run --resume
[error]
  selector_requires_workspace
rc=1
```

## 6. status — 查看 run 与步骤状态

```bash
ecc status [--project DIR] [--run-id ID] [--json | --jsonl | --plain]
```

```console
$ ecc status
[status]
  run: default
  status: failed
  workspace: /tmp/gcd/runs/default
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
{"run": "default", "status": "failed", "workspace": "/tmp/gcd/runs/default", "inspect_cmd": "ecc status", "log_cmd": "ecc log"}
{"step": "synthesis", "tool": "yosys", "status": "success", "runtime": "0:00:18", "log_cmd": "ecc log synthesis"}
{"step": "floorplan", "tool": "ecc", "status": "success", "runtime": "0:00:04", "log_cmd": "ecc log floorplan"}
...
```

run 级状态取全部步骤的聚合：`success / failed / ongoing / unstart / missing / corrupt`。

## 7. log — 查看日志

```bash
ecc log [STEP] [--project DIR] [--run-id ID] [--json | --jsonl | --plain]
```

不带 STEP 列出全部日志文件（含尾部预览）；带 STEP 打印该步骤日志内容（TEXT 模式高亮 ERROR/WARNING 行）。

```console
$ ecc log
[logs]
  synthesis  Synthesis_yosys/log/synthesis.log
    tail:
      synthesizing gcd...
  inspect: ecc log synthesis

$ ecc log synthesis
[log] step=synthesis
  source: Synthesis_yosys/log/synthesis.log
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
ecc config [STEP] --resolved [--project DIR] [--run-id ID] [--json | --jsonl | --plain]
```

`--resolved` 必选。不带 STEP 输出项目级配置（`ecc.toml` 键 + 解析后的绝对路径）；带 STEP 列出该步骤在 `runs/<id>/config/` 下实际生效的配置文件。

```console
$ ecc config --resolved --plain    # 项目级（节选）
config=design.name scope=project value=gcd resolved=gcd source=ecc.toml
config=design.top scope=project value=gcd resolved=gcd source=ecc.toml
config=pdk.name scope=project value=ics55 resolved=ics55 source=ecc.toml
...

$ ecc config floorplan --resolved  # 步骤级
[config]
  step:
    flow_ecc.json (config)
      path: runs/default/config/flow_ecc.json
  inspect: ecc config floorplan --resolved --json
    db_ecc.json (config)
      path: runs/default/config/db_ecc.json
  inspect: ecc config floorplan --resolved --json
```

## 9. param — 参数管理

```bash
ecc param list                      # 列出全部参数（按组，标注来源）
ecc param show KEY                  # 查看单个参数（值/默认/来源/类型/范围/映射）
ecc param set KEY VALUE             # 写入 ecc.toml 的 [params.<group>]（保留注释与格式）
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
  synth
    synth.max_fanout               20
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
```

当前注册的全部参数（13 个）：

| 参数 | 类型 | 默认值 | 约束 | 生效步骤 |
|---|---|---|---|---|
| `design.frequency_mhz` | float | 100.0 | [1e-6, 10000] MHz | synthesis |
| `floorplan.core_util` | float | 0.4 | [0.01, 1.0] | floorplan |
| `floorplan.core_margin` | list[int] | [2, 2] | — | floorplan |
| `floorplan.aspect_ratio` | float | 1.0 | [0.1, 10.0] | floorplan |
| `synth.max_fanout` | int | 20 | [1, 200] | fixfanout |
| `place.target_density` | float | 0.2 | [0.1, 0.95] | placement |
| `place.target_overflow` | float | 0.1 | [0.0, 1.0] | placement |
| `place.global_right_padding` | int | 0 | [0, 100] | placement |
| `place.cell_padding_x` | int | 300 | [0, 10000] | placement |
| `place.routability_opt` | int | 1 | {0, 1} | placement |
| `route.bottom_layer` | str | MET2 | MET1–MET5 | routing |
| `route.top_layer` | str | MET5 | MET2–MET6 | routing |
| `sta.max_paths` | int | 1000 | [1, 100000] | sta |

优先级：CLI `--set` > `ecc.toml` `[params.*]` > 默认值。

## 10. signoff — 签核包与设计报告

flow 跑完（harden preset 全部步骤 Success）后使用。三个子命令都接受 `--project DIR`/`--run-id ID`（定位 `runs/<id>`）或 `--workspace PATH`（直接指定 workspace），以及 `--json/--jsonl/--plain`。

### 10.1 inspect — 就绪度审阅（不改任何东西）

```bash
ecc signoff inspect [--project DIR | --workspace PATH]
```

输出签核包的就绪状态（`ready / attention / blocked`）、七个分组（initial/config/harden/final_design/sta/spef/reports）与风险清单。**blocked 也返回 rc=0**（检查是建议性的，门禁在 export）：

```console
$ ecc signoff inspect --workspace runs/default
[signoff]
  status    : blocked
  workspace : runs/default
  export    : ecc signoff export -o <path>
  report    : ecc signoff report

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

### 10.2 export — 导出签核包 tar.gz（有门禁）

```bash
ecc signoff export -o <path>.tar.gz [--include-debug] [--project DIR | --workspace PATH]
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

### 10.3 report — 文本设计总结报告

```bash
ecc signoff report [-o PATH] [--project DIR | --workspace PATH]
```

生成与 GUI「导出报告（文本）」同版式的设计总结（8 个分区：物理/时序/时钟/多 corner/绕线/功耗/验证/执行成本），默认写入 `<workspace>/signoff/<design>_design_summary.txt`：

```console
$ ecc signoff report --project gcd
[status]
  signoff: report
  status: written
  path: /path/gcd/runs/default/signoff/gcd_design_summary.txt
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

## 11. report — QoR 总分与 checklist 报告

```bash
ecc report qor        [-o PATH] [--project DIR | --run-id ID | --workspace PATH]
ecc report checklist  [-o PATH] [同上]
```

### 11.1 qor — QoR 总体计分报告

按 GUI 项目看板的计分规则给当前 workspace 打分：每条 v3 `qor_metrics.json` 指标按固定失败阈值折算 0-100 分（slack 类线性、core_utilization 目标区间 [0.45,0.70]、lower/higher_is_better 比例），维度内取平均，再按权重（Timing 0.35 / Power 0.25 / Routability 0.2 / Area 0.1 / Clock-DFM 0.1）加权出总分——**缺项维度不重归一化**（与 GUI 一致，缺项会拉低总分）；60 分为通过线。默认写 `<workspace>/signoff/<design>_qor_report.txt`：

```console
$ ecc report qor --project gcd --plain
report=qor path=.../signoff/gcd_qor_report.txt bytes=1717 design=gcd \
  overall_score=61.8 qor_status=Green gate_status=pass \
  dimensions="[{'dimension': 'Timing', 'score': 75.0, 'weight': 0.35, 'metrics': 2}, ...]" \
  view="cat .../gcd_qor_report.txt" status=written
```

报告含：总分与判定（PASS/BELOW THRESHOLD/NOT RATED）、Flow 状态色（Green/Yellow/Orange/Red/Blocked）与 gate（DRC/LVS/RCX/STA 步骤状态）、Area 计分步（最后一个成功的 area 指标步）、维度表、逐指标明细分（corner 维度独立计分）。

### 11.2 checklist — 签核清单报告

读取 `home/checklist.json`（schema v3 签核清单，由 flow 步骤/`ecc signoff inspect` 维护）渲染状态报告：总览（passed/blocked/attention/unavailable）、**BLOCKED 项明细**（含失败原因与 evidence 路径）、ATTENTION 项、全量表。清单不存在时返回 `checklist_unavailable`。默认写 `<workspace>/signoff/checklist_report.txt`。

```bash
ecc signoff inspect --project gcd    # 先刷新 checklist（若还没有）
ecc report checklist --project gcd
```

## 12. rpc — JSON-RPC runtime sidecar（私有）

```bash
ecc rpc serve --stdio [--persistent-db]
```

供 GUI 等前端使用的 JSON-RPC 2.0 服务，`Content-Length` 帧封装于 stdio。`--persistent-db` 额外开放 `db.ensure` / `db.release` 方法。握手与调用示例（完整方法列表和参数见 [workspace-cli.md](workspace-cli.md)）：

```console
→ {"jsonrpc":"2.0","method":"rpc.hello","params":{"version":1},"id":"hello-1"}
← {"jsonrpc":"2.0","result":{"version":1,"eccVersion":"0.1.0-alpha.11","capabilities":["rpc.hello","rpc.ping","rpc.shutdown","runtime.v2","operation.events","workspace.create","workspace.open","workspace.close","workspace.home","workspace.info","workspace.refresh_config","workspace.sync_config","workspace.reset_flow","workspace.export_signoff","workspace.inspect_signoff","flow.run","flow.run_step","operation.start_flow","operation.start_step","operation.status","operation.cancel","operation.ack_step_rendered","workspace.snapshot"]},"id":"hello-1"}

→ {"jsonrpc":"2.0","method":"rpc.ping","params":{},"id":"ping-1"}
← {"jsonrpc":"2.0","result":{"ok":true},"id":"ping-1"}
```

## 13. layout-image — GDS 渲染为图片

```bash
ecc layout-image --gds <in.gds> --image <out.png> [--width N] [--height N]
```

基于 KLayout 把 GDS 版图渲染为快照图片（默认 1920×1920；需要环境中有 KLayout）：

```bash
ecc layout-image --gds runs/default/GDS_ecc/result.gds --image layout.png --width 2560 --height 1600
```

## 14. 端到端典型工作流

```bash
ecc init gcd && cd gcd
# 放入 RTL，编辑 ecc.toml（top/clock/frequency、pdk.root、flow.preset）
ecc doctor                         # 环境体检（PDK/yosys/slang/组件）
ecc check                          # 项目配置校验通过再运行
ecc run --preset harden            # 一次性跑完整链（Synthesis→…→Harden）
ecc status                         # 看步骤状态；失败时：
ecc log place                      # 看出错步骤日志（TEXT 模式自动高亮错误行）
ecc param set place.target_density 0.55   # 调参数后重跑
ecc run --overwrite --preset harden
ecc run --workspace runs/default --only place --force   # 或原地单步复跑
ecc config place --resolved        # 查看该步实际生效的配置文件
ecc signoff inspect                # 签核就绪度（blocked 也 rc=0）
ecc signoff export -o gcd_signoff.tar.gz    # 就绪后导出签核包
ecc signoff report                 # 生成文本设计总结（signoff/<design>_design_summary.txt）
ecc report qor                     # QoR 总分报告（signoff/<design>_qor_report.txt）
ecc report checklist               # 签核清单报告（signoff/checklist_report.txt）
ecc layout-image --gds runs/default/Harden_ecc/result.gds --image gcd.png
```

多 run 对比：

```bash
sed -i 's/^run = "default"/run = "exp1"/' ecc.toml   # 或直接 --run-id exp1
ecc run --run-id exp1 --set place.target_density=0.65
ecc status --run-id exp1
ecc log --run-id exp1
```
