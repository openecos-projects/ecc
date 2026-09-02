# ECC CLI 命令扩展开发指南

本文面向需要在 `ecc` CLI 中新增/修改命令的开发者，基于 `ecc/` 子模块当前源码（`chipcompiler` 包，v0.1.0-alpha.11）整理。代码路径均相对 `ecc/` 子模块根目录。

相关文档：[architecture.md](architecture.md)（架构）、[development.md](development.md)（开发工作流）、[workspace-cli.md](workspace-cli.md)（RPC sidecar 协议）、[../CLAUDE.md](../CLAUDE.md)（仓库约定）。

## 1. 入口与整体结构

```
pyproject.toml                    # scripts.ecc = "chipcompiler.cli.main:main"
chipcompiler/cli/main.py          # run(argv) / main()，仅做薄封装
chipcompiler/cli/app.py           # 根 typer app；invoke_typer_app() 统一执行与退出码
chipcompiler/cli/commands/        # typer 命令定义层（薄）
  ├── project.py                  # init/check/run/status/log/config 的注册与参数声明
  ├── doctor.py                   # doctor 顶层命令（环境体检）
  ├── param.py                    # param 子应用（list/show/set/unset/diff）
  ├── pdk.py                      # pdk 子应用（setup/set-root/show/unset）
  ├── signoff.py                  # signoff 子应用（inspect/export/report）
  ├── report.py                   # report 子应用（qor/checklist）
  └── rpc.py                      # rpc 子应用（serve）
chipcompiler/cli/command_handlers/  # 业务处理层（有状态/重逻辑）
  ├── project.py                  # init / check / run（含 preset 解析与环境预检）
  ├── inspect.py                  # status / log / config
  ├── doctor.py                   # doctor（组装 env_probe 结果为 records）
  ├── pdk.py                      # pdk 三子命令（TOML 定点改写 + root 来源解析）
  ├── signoff.py                  # signoff 三子命令 + inspect 的 TEXT 渲染
  └── report.py                   # report 两子命令（写文件 + 记录汇总）
chipcompiler/cli/handlers/param.py  # param 子命令处理 + param 的 TEXT 渲染
chipcompiler/cli/core/            # 框架层
  ├── inputs.py                   # 各命令的 frozen dataclass 输入模型
  ├── invocation.py               # execute_command()：上下文构建→handler→渲染→退出码
  ├── options.py                  # 共享 Annotated 选项别名
  ├── output.py                   # disclosure_cmd() / step 名与状态归一化
  ├── records.py                  # error_record()
  ├── types.py                    # CommandContext / CommandResult / OutputMode
  └── version_info.py             # version 命令的版本信息
chipcompiler/cli/inspection/      # 只读探查逻辑
  ├── discovery.py / config_view.py / log_view.py
  └── env_probe.py                # doctor/run 预检的环境探查（ProbeResult 体系）
chipcompiler/cli/project/         # ecc.toml 解析校验（config.py）、参数注册表（params.py）
chipcompiler/cli/rendering/       # 输出渲染（render / renderers / pretty / progress）
chipcompiler/engine/signoff/      # 签核收集器 + 设计/checklist 报告（包，见 §5.4）
chipcompiler/engine/qor_report.py # QoR 总分计分（GUI 规则移植，见 §5.5）
```

模块归属由 `test/cli/test_cli_module_layout.py` 强制：核心框架必须在 `cli/core/`、命令注册在 `cli/commands/`、处理逻辑在 `cli/command_handlers/`（项目类）与 `cli/handlers/`（param 类）、只读探查在 `cli/inspection/`、渲染在 `cli/rendering/`；旧的 `chipcompiler/cli/*.py` 平铺模块必须不可导入。新增文件时放进对应子包，不要在 `cli/` 根下新建模块。

## 2. 一次命令调用的完整链路

以 `ecc check --project gcd --json` 为例：

1. `main.py::run()` 把 `sys.argv[1:]` 交给 `app.py::invoke_typer_app(raw)`（`cli/app.py`）。
2. typer 解析参数，命中 `commands/project.py::check_cmd`（`cli/commands/project.py`）。命令函数只做一件事：把 typer 参数装进 frozen dataclass `CheckInput`（定义在 `cli/core/inputs.py`），然后调用：
   ```python
   execute_command("check", command_input, project_handlers.check)
   ```
3. `core/invocation.py::execute_command()`（`cli/core/invocation.py`）依次：
   - `build_context()`：解析项目目录（`--project`，缺省为 cwd）→ 读 `ecc.toml` 得 `ProjectConfig` → 解析 run 目录（`--run-id` > 配置的 `[flow] run` > `runs/default`，见 `cli/project/config.py` 与 `cli/inspection/discovery.py`）→ 由 `--json/--jsonl/--plain` 推导 `OutputMode`，组装成 `CommandContext`（`cli/core/types.py`）。
   - 调 handler：`handler(command_input, ctx) -> CommandResult`。
   - 渲染：`rendering/renderers.py::render_command_result()` 先查 `RENDERERS[(render_key, output_mode)]` 定制渲染器，没有则落到通用 `rendering/render.py::render_result()`。
   - `raise typer.Exit(code=result.exit_code)` 把退出码透传给 `invoke_typer_app`。
4. `invoke_typer_app` 以 `standalone_mode=False` 运行 click 命令，捕获 `click.exceptions.Exit` / `ClickException` 并转换成进程退出码，保证测试里 `cli_main.run([...])` 能拿到返回值。

## 3. 输出约定（records 模型）

所有命令的输出统一为「记录列表」：

- handler 返回 `CommandResult.ok(records)` / `CommandResult.err(records, exit_code=1)`（`cli/core/types.py`）；`records` 是 `tuple[dict, ...]`，每个 dict 是一行结构化记录。
- 四种输出模式（优先级 jsonl > json > plain > text，见 `cli/core/invocation.py`）：
  - `--json`：`{"records": [...]}` 单个 JSON 对象；
  - `--jsonl`：每条记录一行 JSON；
  - `--plain`：`key=value` 逐行（含空格的值会加引号），面向脚本 grep；
  - 默认 TEXT：走 pretty 渲染；无定制渲染器时打印 `key=value`，键名去掉 `_cmd` 后缀。
- 错误记录用 `core/records.py::error_record(...)`，产出 `{"kind": "error", "error": "<机器可读错误码>", ...}`；TEXT 模式下由 `render_error` 打成 `[error]` 块。错误码是稳定契约（如 `missing_config`、`run_exists`、`unknown_parameter`、`invalid_value`），测试会对它们断言。
- 给用户的「下一步」提示统一用 `core/output.py::disclosure_cmd("ecc status", project, run_id)` 生成可复制的完整命令，记录里放在 `inspect` / `log_cmd` / `run` 等字段。

## 4. 新增一个顶层命令（Step by Step）

以新增 `ecc check` 这样的命令为例，共 5 步（前 3 步必须，后 2 步按需）：

### 4.1 定义输入模型

在 `cli/core/inputs.py` 增加 frozen dataclass，必须满足 `CommandInput` 协议（`cli/core/invocation.py`）——即带 `output: OutputOptions` 与 `project: ProjectOptions` 两个字段：

```python
@dataclass(frozen=True)
class CheckInput:
    output: OutputOptions
    project: ProjectOptions
    # 命令私有字段放这里
```

### 4.2 编写 handler

放在 `cli/command_handlers/`（会改项目/跑 flow 的命令）或 `cli/handlers/`（param 类轻命令），签名固定：

```python
def check(command_input: CheckInput, ctx: CommandContext) -> CommandResult:
    if ctx.config is None:
        return CommandResult.err([error_record("missing_config", path=...)])
    ...
    return CommandResult.ok([{...}, ...])
```

约定：handler 不直接 print、不解析命令行字符串；重逻辑延迟导入（现有代码普遍在函数体内 `from chipcompiler... import ...`，保持该风格以缩短 CLI 启动时间）；处理只读探查的逻辑放 `cli/inspection/`，handler 做记录拼装。

### 4.3 注册 typer 命令

在 `cli/commands/project.py`（或新模块）声明命令函数并注册，共享选项直接用 `cli/core/options.py` 的别名：

```python
from chipcompiler.cli.core.options import JsonOption, PlainOption, ProjectOption

def register_project_commands(app: typer.Typer) -> None:
    app.command("check", help="Validate the current project setup")(check_cmd)

def check_cmd(
    *,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = CheckInput(
        output=output_options(json_output=json_output, jsonl=False, plain=plain),
        project=project_options(project),
    )
    execute_command("check", command_input, project_handlers.check)
```

顶层单命令直接 `app.command(...)`（现成范例：`cli/commands/doctor.py`，全链路最短）；命令组则新建 `xxx_app = typer.Typer(...)` 再在 `app.py` 里 `app.add_typer(xxx_app, name="xxx")`（现成范例：`cli/commands/signoff.py`，含子命令经 `execute_command(..., render_key=f"signoff:{sub}")` 复用同一 handler 模块）。注意 `app.py` 构建的根 app 设置了 `add_completion=False, no_args_is_help=True`。

### 4.4 （可选）定制 TEXT 渲染

默认 TEXT 是 `key=value`。若要更友好的输出：

- 单命令：在 `cli/rendering/pretty.py` 的 `get_pretty_renderer()` 注册表加一个渲染函数（现有 `init/check/run/status/config` 即此路径）；
- 子命令组：在 `cli/rendering/renderers.py` 的 `RENDERERS` 字典加 `(render_key, OutputMode)` 条目，`render_key` 通过 `execute_command(..., render_key="param:show")` 传入（param 即此路径）。

JSON/JSONL/PLAIN 无需任何定制。

### 4.5 补测试

CLI 测试全部位于 `ecc/test/cli/`，目录按所有权划分（仓库 CLAUDE.md 第 5 节）：

- 命令行为 → `test/cli/commands/test_<command>.py`；param → `test/cli/params/`；只读探查 → `test/cli/inspect/`；渲染 → `test/cli/rendering/`。
- 测试直接调 Python 入口而非子进程：
  ```python
  from chipcompiler.cli import main as cli_main

  rc = cli_main.run(["check", "--project", project_dir, "--json"])
  assert rc == 0
  data = json.loads(capsys.readouterr().out)
  ```
- 复用 `test/cli/conftest.py` 的 fixture：`create_cli_project`（生成带 `ecc.toml` 的临时项目）、`create_flow_json`（伪造 `runs/<id>/home/flow.json`）、`create_step_dir`、`create_workspace_config`、`mock_pdk_validation` 等。**注意 autouse 的 `_stub_run_preflight`**：它把 `env_probe.probe_environment` 打桩为空，保证 CLI 测试不依赖宿主工具（doctor/预检相关测试自行覆盖该补丁即可覆盖生效）。
- 引擎层报告/签核的测试放顶层 `test/`（如 `test/test_signoff_report.py`、`test/test_qor_report.py`、`test/test_signoff_package.py`），伪造 workspace 复用其 fixture。
- 新命令别忘了在 `test/cli/test_typer_cli.py::test_root_help_returns_zero_and_lists_commands` 与 `test/cli/test_cli_module_layout.py`（commands 元组）里登记。

运行方式（ecc 目录下）：

```bash
nix develop   # 可选
uv sync --no-build-isolation-package ecc-dreamplace --no-build-isolation-package ecc-tools-bin
.venv/bin/python -m pytest test/cli -q
```

## 5. 常见扩展场景

### 5.1 新增可调参数（param 体系）

旧的语义参数仍在 `cli/project/params.py::_LEGACY_PARAM_REGISTRY`。工具 JSON 的直配字段按 owner 分别放在 `cli/project/config_params/`（`cts.py`、`floorplan.py`、`dreamplace.py` 等），每项都必须人工审核。`ParamSchema` 只能拥有一种目标：旧的 `maps_to`、JSON `config_target` 或白名单 PDK `pdk_target`。

已审核的静态模板字段使用 `config_param()` 声明：

```python
# cli/project/config_params/cts.py
config_param(
    "cts.skew_bound",
    "cts",
    ("skew_bound",),
    "0.08",
    applies="cts",
)
```

该声明会同时启用 `ecc param list/show/set/unset/diff`、重复的 `ecc run --set key=value`，以及嵌套 `[params.*]` TOML 的读写与校验。默认 `ecc param list` 保持简明；用 `--step <owner>` 或 `--all` 查看直配 schema。命令行列表和对象值使用 JSON 字面量。

项目 run 创建时，非默认 `config_target` 会以结构化 `Config Overrides` 存入 `home/parameters.json`；每次刷新 workspace 配置后由 `data.workspace.config_overrides` 重放。PDK 路径 schema 在 `config_params/pdk.py`，写入 `[pdk.overrides]`；`pdk.root` 始终使用 `ecc pdk set-root`。不得将 workspace 的输入、输出、临时、生成产物或 STA 多 corner liberty 路径暴露为 CLI 参数。

`config_params/coverage.py` 会把每个 JSON 模板字段与唯一一个直配 schema、旧映射或受保护路径清单比对。模板变化时必须同步更新该清单和 `test/cli/params/test_config_coverage.py`。解析和定点 TOML 编辑仍在 `params.py`，命令测试仍放在 `test/cli/params/`。

### 5.2 扩展 `ecc run`

`run` 有两条互斥路径（`cli/command_handlers/project.py` 的 `run()` / `_run_workspace()`）：

- **项目模式**（默认）：读 `ecc.toml` → 解析 RTL/PDK/参数与 `--preset` 覆盖 → **环境预检**（`_preflight_environment`：按 preset 所需工具调用 `inspection/env_probe.py`，缺失 → `env_not_ready` fail-fast）→ `runs/<run-id>/` 下 `create_workspace` → 从 `rtl2gds.get_flow_builders()` 取步骤构建 `EngineFlow` → 运行（TTY 下走 `rendering/progress.py::run_flow_with_progress` 的进度渲染，否则直接 `run_steps`）。`--overwrite` 会先做安全校验（只删真正的 ECC run 目录）；`--preset` 不写回 `ecc.toml`，与 `--workspace` 互斥。
- **workspace 模式**（`--workspace`）：`load_workspace` 后用 `chipcompiler.engine.rerun` 的 `run_resume / run_from / run_only` 原地复跑；`--resume/--from/--only` 三个选择器互斥且仅在该模式合法；该模式不做环境预检。

改 flow 步骤序列本身在 `chipcompiler/engine`（`EngineFlow.build_default_steps()` / `add_step()`），不在 CLI 层；CLI 只负责参数解析、进度渲染选择与结果映射。

### 5.3 扩展环境探查（doctor / 预检）

`cli/inspection/env_probe.py` 是唯一的探查层：`ProbeResult(component, status, required, detail, remediation)` + 每组件一个 probe 函数（yosys / yosys-slang / ecc-tools / dreamplace / klayout / sizer / pdk）。新增组件 = 加一个 probe 函数并登记进 `_PROBES`/`ALL_COMPONENTS`；`probe_environment()` 对异常兜底（探查失败计为 fail 而非崩溃）。`probe_components_for_preset()` 决定 run 预检的范围（yosys↔含 Synthesis、dreamplace↔含 place/legalization；PDK 由 `validate_project_config` 覆盖、slang 留给综合步骤）。

### 5.4 扩展签核（`ecc signoff` 与引擎报告）

- **CLI 层**：`cli/commands/signoff.py` + `cli/command_handlers/signoff.py`。`_resolve_workspace()` 统一解析 `--workspace` 与 `--project/--run-id`（互斥冲突 → `project_workspace_conflict`）。inspect 复用 `runtime/signoff_export.py::inspect_signoff_package`（blocked 也 rc=0）；export 复用 `export_signoff_package_archive`（`RuntimeApiError` → `signoff_incomplete`）。
- **引擎层**：`chipcompiler/engine/signoff/` 包——`__init__.py` 是签核收集器 `SignoffPackageCollector`（`text_report()` 薄入口）+ 公共 API 再导出；文本设计报告的实现按职责分模块（`report.py` 编排 / `report_data.py` 数据契约 / `report_extract.py` 解析器+workspace 收集 / `report_sections.py` 分区抽取 / `report_timing.py` timing 链 / `report_text.py` 格式化），全部经包 `__init__` 对外暴露（`from chipcompiler.engine.signoff import generate_text_report`）。对外导入面保持单一；新增报告分区 = 在 `report_sections.py`（或 timing 链）加一个 `_extract_<family>(q)` 并在 `report.py` 编排处调用。

### 5.5 扩展 QoR 计分 / checklist 报告（`ecc report`）

- `engine/qor_report.py`：GUI `projectQorTrend.ts` 的单 workspace 移植——常量表（`METRIC_FAIL_VALUES`/`DIMENSION_WEIGHTS`/`QOR_SCORE_THRESHOLD`）+ 归一化 + 项目级记录选择（role 优先级 final>gate>trend、area_cost 只取最后成功的 area 步）+ `score_record` 计分公式 + 维度加权（不重归一化）。新增可计分指标 = 在 GUI 与 `METRIC_FAIL_VALUES` 同步加阈值。
- `engine/signoff/report_checklist.py`：只读渲染 `home/checklist.json`（不合法时报 unavailable，绝不回写文件）。
- CLI：`cli/commands/report.py` + `cli/command_handlers/report.py`；workspace 解析复用 `inspection/discovery.py::resolve_command_workspace`（signoff/report 共用）。

### 5.6 扩展 RPC（`ecc rpc serve`）

`rpc serve --stdio` 启动 JSON-RPC 2.0 sidecar（`chipcompiler/runtime/stdio_server.py`）。方法在 `chipcompiler/runtime/methods.py::RUNTIME_METHODS` 声明（`method_name` + pydantic `request_model` + `handler_name`），handler 实现在 `chipcompiler/runtime/workspace_api.py`，由 `runtime/server.py` 统一挂载；协议细节见 [workspace-cli.md](workspace-cli.md)。新增方法 = 加一个 `RuntimeMethodSpec` + 对应 API 方法 + 请求模型，无需改 CLI 层。

## 6. 构建 CLI 安装包（改完代码的实测环节）

命令本体可直接用 `.venv/bin/ecc` 或 `uv run ecc` 验证；要测安装版行为（PATH/软链/env 不变的真实体验）则重打 PyInstaller 包——与官方 release 完全同流程（`ecc.spec` + `.github/actions/build-pyinstaller-bundle`）：

```bash
cd ecc
.venv/bin/python -m PyInstaller ecc.spec --clean --noconfirm   # 产物 dist/ecc/（onedir，~3.6G；首跑会触发 dreamplace 的 cmake 安装，属正常）

# 安装到本机（ecc-cli-setup.sh 的默认安装位；~/.local/bin/ecc 软链与 ~/.ecc-env.sh 均无需改动）
rm -rf ~/.local/ecc && mkdir -p ~/.local/ecc && cp -a dist/ecc/. ~/.local/ecc/
ecc --help            # 验证 doctor / signoff / report 已列出

# 需要分发时按官方格式打 tar.gz
tar -cf /tmp/ecc.tar -C dist/ecc . && gzip -n -9 -c /tmp/ecc.tar > dist/release/ecc-cli-linux-x86_64.tar.gz
```

回退官方发行版：`bash docs/ecc-cli-setup.sh --force`（见 [ecc-cli-setup.sh](ecc-cli-setup.sh)）。

## 7. 约束与注意事项（来自仓库约定）

- **模块体积**：文件超过约 800 LoC 时新功能放新模块，不要继续堆（[../CLAUDE.md](../CLAUDE.md) 第 6 节）。
- **Python 3+**：不用 `__future__`；最低版本看 `pyproject.toml` 的 `requires-python`。
- **测试放置**按所有权边界；优先整对象比较；不为静态定义的值写测试；不为已删除的逻辑保留负向测试。
- **代码评审**必须执行 [review-guidelines.md](review-guidelines.md) 的附加标准。
- `uv.lock` 是依赖事实源；`requirements_lock.txt` 自动生成且被 gitignore。
- ECC-Tools 在代码里的工具标识是 `"ecc"`（不是 `"ecc-tools"`）；每个工具模块需实现 `is_eda_exist / build_step / run_step`；步骤在 `multiprocessing.Process` 中执行，状态持久化在 `workspace.flow.json`。
- 依赖安装后 `ecc` 以 editable 方式生效，改源码下次导入即生效，无需重装。
