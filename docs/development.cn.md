# 开发指南

ECOS Chip Compiler 的开发环境搭建与工作流，含 `ecc` CLI 的扩展开发方式。代码路径均相对 `ecc/` 子模块根目录。

## 安装

ECC 使用 `uv` 管理。ECC 主工作区以 editable 方式从本地源码树安装 `ecc`。

如果本机有 Nix，先进入开发 shell 再执行 `uv sync`：

```bash
nix develop
```

如果没有 Nix，在普通 shell 中执行同样的 `uv sync` 命令即可（需先装好原生构建所需的系统包）。

### ECC 工作区

在 `ecc` 仓库根目录执行：

```bash
uv sync --no-build-isolation-package ecc-dreamplace --no-build-isolation-package ecc-tools-bin --verbose
source .venv/bin/activate
```

这会创建 Python 虚拟环境并安装：

- 来自本地源码树的 `ecc`；
- 来自 `chipcompiler/thirdparty/ecc-dreamplace` 的 `ecc-dreamplace`；
- 来自 `chipcompiler/thirdparty/ecc-tools` 的 `ecc-tools-bin`。

`ecc` 是 editable 安装，Python 源码改动在下次导入时即生效。

### 用 direnv 自动加载

```bash
direnv allow
```

之后 `cd` 进入仓库时 `direnv` 会自动进入 Nix 开发 shell。

## 构建包

用 uv 构建 Python 包：

```bash
uv build
```

wheel 和 sdist 产物写入 `dist/`。

自己编译可安装的 PyInstaller CLI 包见 [README - 源码构建](../README.cn.md#源码构建)。

## 调试

常规调试：

1. 按上面的命令同步 ECC 工作区；
2. 激活 `.venv`；
3. 用 `.venv/bin/python` 运行 CLI、测试或调试器。

常规 ECC 开发不需要额外的 `PYTHONPATH` 覆盖；进程再次导入 `ecc` 时读的是源码树。

可选的 IDE 索引配置：

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python"
}
```

这只改善导航体验；运行时行为跟随激活的 uv 环境。

## 代码质量

```bash
# 格式化与 lint
uv run ruff format chipcompiler/ test/
uv run ruff check chipcompiler/ test/

# 类型检查
uv run ty check
uv run pyright chipcompiler/
uv run mypy chipcompiler/

# 旧格式化工具
uv run black chipcompiler/ test/
uv run isort chipcompiler/ test/
```

## Git 钩子

每个 clone 安装一次 pre-commit 钩子，即可在每次提交前自动运行 ruff lint/format（以及 commit message 格式检查）：

```bash
uv run prek install
```

这会注册 `.pre-commit-config.yaml` 中的 `pre-commit` 阶段（ruff lint + ruff format）和 `commit-msg` 阶段（约定式提交检查）（由其 `default_install_hook_types` 声明）。如果已装过钩子——或旧安装缺 commit-msg 钩子——用显式命令重装：

```bash
uv run prek install --config .pre-commit-config.yaml --hook-type pre-commit --hook-type commit-msg --overwrite
```

## 测试

```bash
uv run pytest test/
uv run pytest test/tools/yosys/test_utility.py -v
uv run pytest test/ --cov=chipcompiler --cov-report=term-missing
uv run pytest test/formal/ -v
```

### 形式化验证

基于 z3 的形式化验证。方法、测试清单与已知发现的 bug 见 [test/formal/README.md](../test/formal/README.md)。

## 新增 EDA 工具

### 1. 创建目录结构

```bash
mkdir -p chipcompiler/tools/<tool_name>/{configs,scripts}
touch chipcompiler/tools/<tool_name>/{__init__.py,builder.py,runner.py,utility.py}
```

### 2. 实现接口

`builder.py`：

```python
from pathlib import Path

from chipcompiler.data import Workspace, WorkspaceStep

def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
) -> WorkspaceStep:
    directory = Path(workspace.directory) / f"{step_name}_<tool_name>"
    return WorkspaceStep(name=step_name, tool="<tool_name>", directory=directory)

def build_step_space(workspace_step: WorkspaceStep) -> None:
    Path(workspace_step.directory).mkdir(parents=True, exist_ok=True)

def build_step_config(workspace: Workspace, workspace_step: WorkspaceStep) -> None:
    ...  # 根据 workspace 参数写出该步骤的配置文件
```

`runner.py`：

```python
import subprocess

from chipcompiler.data import Workspace, WorkspaceStep

def is_eda_exist() -> bool:
    try:
        subprocess.run(["<tool_name>", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def run_step(workspace: Workspace, step: WorkspaceStep, ecc_module=None) -> bool:
    result = subprocess.run(
        ["<tool_name>", str(step.script.main)],
        cwd=step.directory,
        capture_output=True,
    )
    return result.returncode == 0
```

`__init__.py`：

```python
from .builder import build_step, build_step_space, build_step_config
from .runner import is_eda_exist, run_step

__all__ = ["build_step", "build_step_space", "build_step_config", "is_eda_exist", "run_step"]
```

### 3. 添加配置与脚本

- JSON 模板放 `configs/`；
- TCL、Python 或 shell 脚本放 `scripts/`。

### 4. 接入流程

修改 `EngineFlow.build_default_steps()` 或使用 `add_step()`。

### 5. 编写测试

```python
import pytest
from chipcompiler.tools.<tool_name> import is_eda_exist, run_step

@pytest.mark.skipif(not is_eda_exist(), reason="<tool_name> not installed")
def test_run_step():
    pass
```

## 接入第三方工具

ECC 用 uv 做 Python 依赖解析。第三方仓库按独立项目对待，其包专属的搭建说明留在各自仓库中。

### 1. Python 依赖

把包加入根 `pyproject.toml`，然后执行：

```bash
uv lock
```

再按 [安装](#安装) 一节的命令同步 ECC 工作区。

### 2. 运行时接入

创建 `chipcompiler/tools/<tool>/`，包含 `__init__.py`、`builder.py`、`runner.py`。每个工具必须实现 `is_eda_exist`、`build_step`、`run_step`。通过 `EngineFlow.build_default_steps()` 或 `add_step()` 接入流程。

### Sizer 开发约定

Sizer 目前被视为外部原生工具，而不是 ECC 的 Python 工作区包。不要把 `ecc-sizer` 加入 `[tool.uv.workspace]`：`uv` 解决的是 Python 包与 lockfile，而 Sizer 是独立的 CMake/Nix C++ 项目，自带 OpenROAD 子模块树。

不要把 Sizer vendor 到 `chipcompiler/thirdparty` 下，除非 ECC 有意接管该原生运行时的构建与分发。本地开发时把 Sizer 放在同级检出目录，通过 PATH 暴露其可执行文件。只有当 CI、release bundle 或最终用户安装必须在没有单独准备 Sizer 检出的情况下可复现时，才把它提升为 ECC 的 thirdparty 输入；届时优先选 Nix input 或 release 产物，仅当该仓库本就应由 ECC 自身构建时才用 `chipcompiler/thirdparty/ecc-sizer` 检出的方式。

## 扩展 CLI

本节面向需要在 `ecc` CLI 中新增/修改命令的开发者。

### CLI 整体结构

```
pyproject.toml                    # scripts.ecc = "chipcompiler.cli.main:main"
chipcompiler/cli/main.py          # run(argv) / main()，仅做薄封装
chipcompiler/cli/app.py           # 根 typer app；invoke_typer_app() 统一执行与退出码；version / layout-image 两命令直接注册于此
chipcompiler/cli/commands/        # typer 命令定义层（薄）
  ├── project.py                  # init/check/run/status/log/config/migrate 的注册与参数声明
  ├── doctor.py                   # doctor 顶层命令（环境体检）
  ├── param.py                    # param 子应用（list/show/set/unset/diff）
  ├── pdk.py                      # pdk 子应用（set-root/show/unset）
  ├── project_config.py           # project 子应用（set/unset/add/remove/show）
  ├── workspace.py                # workspace 子应用（refresh）
  ├── signoff.py                  # signoff 子应用（inspect/export）
  └── report.py                   # report 子应用（summary/qor/checklist/step）
chipcompiler/cli/command_handlers/  # 业务处理层（唯一的处理器包，有状态/重逻辑）
  ├── project.py                  # init / check / run / migrate / workspace refresh（含 preset 解析与环境预检）
  ├── inspect.py                  # status / log / config
  ├── doctor.py                   # doctor（组装 env_probe 结果为 records）
  ├── param.py                    # param 五子命令（校验 + 经 cli/project/toml_edit.py 做 TOML 定点改写）
  ├── pdk.py                      # pdk 三子命令（TOML 定点改写 + root 来源解析）
  ├── project_config.py           # project 五子命令（声明 schema + 经 cli/project/config_fields.py 做 TOML 定点改写）
  ├── workspace_params.py         # workspace 局部 param set/unset/list/diff（改 home/params.toml + 失效后缀步骤）
  ├── signoff.py                  # signoff inspect/export
  └── report.py                   # report 四子命令（文件写出 + 记录汇总）
chipcompiler/cli/core/            # 框架层
  ├── inputs.py                   # 各命令的 frozen dataclass 输入模型
  ├── invocation.py               # execute_command()：上下文构建→handler→渲染→退出码
  ├── options.py                  # 共享 Annotated 选项别名
  ├── output.py                   # disclosure_cmd() / step 名与状态归一化
  ├── records.py                  # error_record()
  ├── types.py                    # CommandContext / CommandResult / OutputMode
  └── version_info.py             # version 命令的包元数据版本（环境工具版本见 inspection/tool_versions.py）
chipcompiler/cli/inspection/      # 只读探查逻辑
  ├── discovery.py / config_view.py / log_view.py
  ├── env_probe.py                # doctor/run 预检的环境探查（ProbeResult 体系）
  └── tool_versions.py            # ecc version 的环境工具版本（yosys/sizer/klayout）
chipcompiler/cli/project/         # config.py（ecc.toml 解析校验）/ config_fields.py（`ecc project` 的项目声明 schema）/ params.py（参数注册表）/ workspace_params.py（workspace 局部覆盖记录）/ manifest.py（项目形态分类）/ effective_config.py / config_params/（直配参数 schema）/ migrate*.py（旧布局迁移）/ run_*.py（run 目标解析与分发）
chipcompiler/cli/rendering/       # 输出渲染（render / renderers / pretty / progress）
chipcompiler/engine/signoff/      # 签核收集器 + 设计/checklist 报告（包，见下文）
chipcompiler/engine/qor_report.py # QoR 总分计分（GUI 规则移植）
```

模块归属由 `test/cli/test_cli_module_layout.py` 强制：核心框架必须在 `cli/core/`、命令注册在 `cli/commands/`、全部处理器在唯一的 `cli/command_handlers/` 包、只读探查在 `cli/inspection/`、渲染在 `cli/rendering/`；旧的 `chipcompiler/cli/*.py` 平铺模块必须不可导入。新增文件时放进对应子包，不要在 `cli/` 根下新建模块。

公开命令的归属必须严格：`ecc signoff` 只负责签核包就绪度与归档导出（`inspect`、`export`）；`ecc report` 统一承载报告输出（`summary`、`qor`、`checklist`、`step`）。`ecc config [STEP]` 始终返回解析后的数据，因此不提供 `--resolved` 开关。不要在错误的命令组中增加别名，也不要添加没有行为分支的选项。

### 一次命令调用的完整链路

以 `ecc check --project gcd --plain` 为例：

1. `main.py::run()` 把 `sys.argv[1:]` 交给 `app.py::invoke_typer_app(raw)`（`cli/app.py`）。
2. typer 解析参数，命中 `commands/project.py::check_cmd`（`cli/commands/project.py`）。命令函数只做一件事：把 typer 参数装进 frozen dataclass `CheckInput`（定义在 `cli/core/inputs.py`），然后调用：
   ```python
   execute_command("check", command_input, project_handlers.check)
   ```
3. `core/invocation.py::execute_command()`（`cli/core/invocation.py`）依次：
   - `build_context()`：解析项目目录（`--project`，缺省为 cwd）→ 读项目唯一的 `ecc.toml`（不可读时记入 `config_error`）→ `cli/project/manifest.py::classify_project()` 判定项目形态（manifest / legacy / virgin）。manifest 项目只从 `project.json` workspace 表解析 `--workspace NAME`：唯一活跃 workspace 自动选中，多个时必须选择；新的 `ecc run --workspace NAME` 会在创建文件前登记。`--workspace` 是项目内单路径段名称，不是直接路径。legacy 项目必须先迁移才能 `ecc run`；清单损坏为 `manifest_invalid`。随后由 `--plain` 推导 `OutputMode`，组装成带 `project_state` / `manifest_error` 字段的 `CommandContext`（`cli/core/types.py`）。
   - 调 handler：`handler(command_input, ctx) -> CommandResult`。
   - handler 返回后按需追加记录（`_with_legacy_hint` / `_with_config_shadow_hint`）：legacy 项目的 `run/check/status` 附加迁移提示（指向 `ecc migrate`）；workspace 的 `home/` 同时存在 `params.toml` 与旧 `parameters.json` 时打 `workspace_config_shadowed` 警告（旧 JSON 已失效）。
   - 渲染：`rendering/renderers.py::render_command_result()` 先查 `RENDERERS[(render_key, output_mode)]` 定制渲染器，没有则落到通用 `rendering/render.py::render_result()`。
   - `raise typer.Exit(code=result.exit_code)` 把退出码透传给 `invoke_typer_app`。
4. `invoke_typer_app` 以 `standalone_mode=False` 运行 click 命令，捕获 `click.exceptions.Exit` / `ClickException` 并转换成进程退出码，保证测试里 `cli_main.run([...])` 能拿到返回值。

### 输出约定（records 模型）

经 `execute_command()` 分发的命令统一使用「记录列表」：

- handler 返回 `CommandResult.ok(records)` / `CommandResult.err(records, exit_code=1)`（`cli/core/types.py`）；`records` 是 `tuple[dict, ...]`，每个 dict 是一行结构化记录。
- 两种输出模式（见 `cli/core/invocation.py`）：
  - `--plain`：`key=value` 逐行（含空格的值会加引号），面向脚本 grep；
  - 默认 TEXT：走 pretty 渲染；无定制渲染器时打印 `key=value`，键名去掉 `_cmd` 后缀。
- 错误记录用 `core/records.py::error_record(...)`，产出 `{"kind": "error", "error": "<机器可读错误码>", ...}`；TEXT 模式下由 `render_error` 打成 `[error]` 块。错误码是稳定契约（如 `missing_config`、`run_exists`、`unknown_parameter`、`invalid_value`），测试会对它们断言。
- 给用户的「下一步」提示统一用 `core/output.py::disclosure_cmd("ecc status", project, run_id)` 生成可复制的完整命令，记录里放在 `inspect` / `log_cmd` / `run` 等字段。

`ecc version` 直接格式化版本元数据；另有一个隐藏的 `--json` 选项（单对象、版本专用 schema）预留给桌面应用，不出现在 `--help` 中。`ecc layout-image` 有意不使用 records 渲染器输出模式。

### 新增一个命令

以新增 `ecc check` 这样的命令为例，共 5 步（前 3 步必须，后 2 步按需）：

1. **定义输入模型**。在 `cli/core/inputs.py` 增加 frozen dataclass，必须满足 `CommandInput` 协议（`cli/core/invocation.py`）——即带 `output: OutputOptions` 与 `project: ProjectOptions` 两个字段：

   ```python
   @dataclass(frozen=True)
   class CheckInput:
       output: OutputOptions
       project: ProjectOptions
       # 命令私有字段放这里
   ```

2. **编写 handler**，放在 `cli/command_handlers/`，签名固定：

   ```python
   def check(command_input: CheckInput, ctx: CommandContext) -> CommandResult:
       if ctx.config is None:
           return CommandResult.err([error_record("missing_config", path=...)])
       ...
       return CommandResult.ok([{...}, ...])
   ```

   约定：handler 不直接 print、不解析命令行字符串；重逻辑延迟导入（现有代码普遍在函数体内 `from chipcompiler... import ...`，保持该风格以缩短 CLI 启动时间）；处理只读探查的逻辑放 `cli/inspection/`，handler 做记录拼装。

3. **注册 typer 命令**。在 `cli/commands/project.py`（或新模块）声明命令函数并注册，共享选项直接用 `cli/core/options.py` 的别名：

   ```python
   from chipcompiler.cli.core.options import PlainOption, ProjectOption

   def register_project_commands(app: typer.Typer) -> None:
       app.command("check", help="Validate the current project setup")(check_cmd)

   def check_cmd(
       *,
       project: ProjectOption = None,
       plain: PlainOption = False,
   ) -> None:
       command_input = CheckInput(
           output=output_options(plain=plain),
           project=project_options(project),
       )
       execute_command("check", command_input, project_handlers.check)
   ```

   顶层单命令直接 `app.command(...)`（现成范例：`cli/commands/doctor.py`，全链路最短）；命令组则新建 `xxx_app = typer.Typer(...)` 再在 `app.py` 里 `app.add_typer(xxx_app, name="xxx")`（现成范例：`cli/commands/signoff.py`，含子命令经 `execute_command(..., render_key=f"signoff:{sub}")` 复用同一 handler 模块）。注意 `app.py` 构建的根 app 设置了 `add_completion=False, no_args_is_help=True`。

4. **（可选）定制 TEXT 渲染**。默认 TEXT 是 `key=value`。若要更友好的输出：

   - 单命令：在 `cli/rendering/pretty.py` 的 `get_pretty_renderer()` 注册表加一个渲染函数（现有 `init/check/run/status/config` 即此路径）；
   - 子命令组：在 `cli/rendering/renderers.py` 的 `RENDERERS` 字典加 `(render_key, OutputMode)` 条目，`render_key` 通过 `execute_command(..., render_key="param:show")` 传入（param 即此路径）。

   PLAIN 无需任何定制。

5. **补测试**。测试放置按所有权边界（见 [../CLAUDE.md](../CLAUDE.md) 第 5 节）；CLI 特有约定：

   - 命令行为 → `test/cli/commands/test_<command>.py`；param → `test/cli/params/`；只读探查 → `test/cli/inspect/`；渲染 → `test/cli/rendering/`。
   - 测试直接调 Python 入口而非子进程：
     ```python
     from chipcompiler.cli import main as cli_main

     rc = cli_main.run(["check", "--project", project_dir, "--plain"])
     assert rc == 0
     records = plain_records(capsys.readouterr().out)  # fixture 来自 test/cli/conftest.py
     ```
   - 复用 `test/cli/conftest.py` 的 fixture：`create_cli_project`（生成带 `ecc.toml` 的临时项目）、`create_flow_json`（伪造 `runs/<id>/home/flow.json`）、`create_step_dir`、`create_workspace_config`、`mock_pdk_validation` 等。**注意 autouse 的 `_stub_run_preflight`**：它把 `env_probe.probe_environment` 打桩为空，保证 CLI 测试不依赖宿主工具（doctor/预检相关测试自行覆盖该补丁即可覆盖生效）。
   - 引擎层报告/签核的测试放顶层 `test/`（如 `test/test_signoff_report.py`、`test/test_qor_report.py`、`test/test_signoff_package.py`），伪造 workspace 复用其 fixture。
   - 新命令别忘了在 `test/cli/test_typer_cli.py::test_root_help_returns_zero_and_lists_commands` 与 `test/cli/test_cli_module_layout.py`（commands 元组）里登记。

### 常见扩展场景

#### 新增可调参数（param 体系）

旧的语义参数仍在 `cli/project/params.py::_LEGACY_PARAM_REGISTRY`。工具 JSON 的直配字段按 owner 分别放在 `data/config_params/`（`cts.py`、`floorplan.py`、`dreamplace.py` 等），每项都必须人工审核。`ParamSchema` 只能拥有一种目标：旧的 `maps_to`、JSON `config_target` 或白名单 PDK `pdk_target`。

已审核的静态模板字段使用 `config_param()` 声明（`description` 为必填关键字参数，逐参数人工撰写，`test/data/test_descriptions.py` 会校验）：

```python
# chipcompiler/data/config_params/cts.py
config_param(
    "cts.skew_bound",
    "cts",
    ("skew_bound",),
    "0.08",
    applies="cts",
    description="Allowed clock skew upper bound in ns.",
)
```

该声明会同时启用 `ecc param list/show/set/unset/diff`、重复的 `ecc run --set key=value`，以及嵌套 `[params.*]` TOML 的读写与校验。默认 `ecc param list` 保持简明；用 `--step <owner>` 或 `--all` 查看直配 schema。命令行列表和对象值使用 JSON 字面量。

项目 run 创建时，非默认 `config_target` 会以结构化 `config_overrides` 存入 `home/params.toml`；每次刷新 workspace 配置后由 `data.workspace.config_overrides` 重放。PDK 路径 schema 在 `config_params/pdk.py`，写入 `[pdk.overrides]`；`pdk.root` 始终使用 `ecc pdk set-root`。不得将 workspace 的输入、输出、临时、生成产物或 STA 多 corner liberty 路径暴露为 CLI 参数。

`config_params/coverage.py` 会把每个 JSON 模板字段与唯一一个直配 schema、旧映射或受保护路径清单比对。模板变化时必须同步更新该清单和 `test/cli/params/test_config_coverage.py`。解析和定点 TOML 编辑仍在 `params.py`，命令测试仍放在 `test/cli/params/`。

#### 扩展 `ecc run`

`run` 有两条互斥路径（`cli/command_handlers/project.py` 的 `run()` / `_run_workspace()`）：

- **新建 workspace**：解析 `[design]` 输入声明、PDK、参数与请求入口步骤；只校验入口步骤所需文件；先原子登记受管名称到 `project.json`（`not_started`）；预检工具；在 `<project>/<workspace 名称>` 调用 `create_workspace`。`create_workspace` 将输入复制到 `origin/` 并产出全部步骤配置，CLI 后续不改写配置。正常新建 flow 用 preset；`--from A --to B` 改用 `rtl2gds.build_flow_range(A, B)` 动态构建包含式规范范围。新范围不能与 `--preset`、`--overwrite`、`--resume`、`--only`、`--force` 组合。
- **已有 workspace**：先由 `chipcompiler/engine/reconcile.py` 把持久化 flow 与目标对齐（前缀 → 追加扩展；超集且全成 → `no_op`；分叉 → `flow_mismatch`），再 `load_workspace` 后由 `chipcompiler.engine.rerun` 的 `run_resume`、`run_from` 或 `run_only` 原地复跑。`--from A --to B` 是已有 flow 的包含式范围，会将其后的步骤状态失效但保留其输出文件。已有 workspace 不会重新预检输入，也不会改写已复制输入或配置。

项目 preset 的步骤序列定义在 `chipcompiler/rtl2gds/builder.py`（`build_*_flow()` / `get_flow_builders()`），不在 CLI 层。`build_flow_range()` 对规范的 `build_rtl2gds_flow()` 结果切片，步骤别名和顺序只有一份来源。修改序列时须同步引擎默认 flow、`StepEnum` 与 manifest 范围映射；CLI 只负责参数解析、输入契约、进度渲染选择与结果映射。

#### 扩展环境探查（doctor / 预检）

`cli/inspection/env_probe.py` 是唯一的探查层：`ProbeResult(component, status, required, detail, remediation)` + 每组件一个 probe 函数（yosys / yosys-slang / ecc-tools / dreamplace / klayout / sizer / pdk）。新增组件 = 加一个 probe 函数并登记进 `_PROBES`/`ALL_COMPONENTS`；`probe_environment()` 对异常兜底（探查失败计为 fail 而非崩溃）。`probe_components_for_preset()` 决定当前 run 预检范围（始终 ecc-tools，yosys↔含 Synthesis，dreamplace↔含 place/legalization，sizer↔含 Timing optimization）。PDK 由配置校验覆盖，slang 留给综合步骤；Sizer 也是 doctor 的必需组件。

#### 扩展签核（`ecc signoff inspect/export`）

- **CLI 层**：`cli/commands/signoff.py` + `cli/command_handlers/signoff.py`。`inspection/discovery.py::resolve_loaded_workspace()` 在选定项目中解析受管 `--workspace NAME`（或唯一活跃 workspace）。inspect 复用 `engine/signoff_export.py::inspect_signoff_package`（blocked 也 rc=0）；export 复用 `export_signoff_package_archive`（`SignoffExportError` → `signoff_incomplete`）。
- **引擎层**：`chipcompiler/engine/signoff/` 包负责签核收集器 `SignoffPackageCollector`，以及就绪度检查和归档导出所使用的包级 API。

#### 扩展报告（`ecc report summary/qor/checklist/step`）

- **设计总结**：`ecc report summary` 调用 `chipcompiler.engine.signoff.generate_text_report`。其实现按职责分模块（`report.py` 编排 / `report_data.py` 数据契约 / `report_extract.py` 解析器+workspace 收集 / `report_sections.py` 分区抽取 / `report_timing.py` timing 链 / `report_text.py` 格式化），全部经包 `__init__` 对外暴露。新增报告分区时，在 `report_sections.py`（或 timing 链）增加 `_extract_<family>(q)`，并在 `report.py` 编排处注册。
- `engine/qor_report.py`：GUI `projectQorTrend.ts` 的单 workspace 移植——常量表（`METRIC_FAIL_VALUES`/`DIMENSION_WEIGHTS`/`QOR_SCORE_THRESHOLD`）+ 归一化 + 项目级记录选择（role 优先级 final>gate>trend、area_cost 只取最后成功的 area 步）+ `score_record` 计分公式 + 维度加权（不重归一化）。新增可计分指标 = 在 GUI 与 `METRIC_FAIL_VALUES` 同步加阈值。
- `engine/signoff/report_checklist.py`：只读渲染 `home/checklist.json`（不合法时报 unavailable，绝不回写文件）。
- CLI：`cli/commands/report.py` + `cli/command_handlers/report.py`；workspace 解析复用 `inspection/discovery.py`（`resolve_workspace_path` 是无副作用核心，`resolve_command_workspace` 是核心加 `load_workspace`；signoff、report 与只读的 status/log/config 共用）。

#### 扩展项目声明（`ecc project *` / `ecc workspace refresh`）

- `ecc project set/unset/add/remove/show` 的可编辑键在 `cli/project/config_fields.py::PROJECT_FIELDS` 声明（`key` / TOML 表 / 字段名 / 类型 / `list_value`）。加一个字段五个子命令自动生效；`add`/`remove` 硬性只支持 `design.rtl`（其余键报 `unsupported_project_collection`）。
- `ecc workspace refresh` 的实现等价于 run 路径的 `overwrite=True, execute_flow=False`（`cli/command_handlers/project.py::refresh_workspace`），因此它和新建 run 一样做环境预检（`ecc.toml` 的 `preset: rtl2gds` 要求全套工具就绪，即使并不真正执行步骤）；非 manifest 项目报 `workspace_refresh_requires_managed_workspace`。
- workspace 局部 `param set/unset/list/diff --workspace NAME` 经 `cli/command_handlers/workspace_params.py` 修改 `home/params.toml`（记录到 `workspace_param_overrides`，经 `chipcompiler.engine.rerun` 失效后缀步骤）；项目级 `param` 走 `cli/command_handlers/param.py`。

## CLI 用法

面向命令行自动化与脚本，经 Nix 运行 CLI：

```bash
nix run . -- init gcd
nix run . -- check --project gcd
nix run . -- run --project gcd
nix run . -- status --project gcd
nix run . -- log --project gcd
```

或经激活的 uv 环境运行：

```bash
uv run ecc init gcd
uv run ecc check --project gcd
uv run ecc run --project gcd
```

### 环境体检

`ecc doctor` 探查宿主环境（PDK、yosys 含 slang 前端、捆绑的 ecc-tools/dreamplace、必需的 sizer、可选的 klayout），逐项报告 pass/fail/skip 与修复建议；只有必需项失败才返回非零。`ecc run` 对所选 preset 需要的工具做同样的探查，并在创建 workspace 之前以 `env_not_ready` 快速失败：

```bash
uv run ecc doctor                  # 在项目目录内执行（PDK 探针需要）
uv run ecc doctor --project gcd --plain
```

### PDK 路径

`ecc pdk set-root <path>` 把已就绪的 ics55 PDK 接入项目（写入 `ecc.toml` 的 `[pdk] root`，自动展开为绝对路径；内容不完整只提示不阻断）。`ecc pdk show` 报告生效的 root、命中的解析来源（ecc.toml / `CHIPCOMPILER_ICS55_PDK_ROOT` / `ICS55_PDK_ROOT` / 仓库默认）以及内容校验；`ecc pdk unset` 清除该覆盖：

```bash
uv run ecc pdk set-root ~/pdk/icsprout55-pdk
uv run ecc pdk show
```

### Flow Preset 覆盖

`ecc run --preset <name>` 单次覆盖 `[flow] preset`，不改 `ecc.toml`。合法名从 `chipcompiler/rtl2gds/builder.py` 自动发现（`rtl2gds | syn_sta | synthesis_lec`）；`rtl2gds` preset 是完整的综合到 Harden 链（15 步，Synthesis 后紧跟一次综合级 LEC；Harden 产出 GDS + 抽象 LEF + 时序 LIB）：

```bash
uv run ecc run --project gcd --preset rtl2gds
```

### 报告

`ecc report qor` 按 GUI 项目看板相同的方式给 workspace 打分（每指标对固定 fail 阈值计分、维度求均值、加权总分——缺失维度不做权重重归一化）；`ecc report checklist` 渲染签核清单状态；`ecc report summary` 写出与 GUI 一致的文本设计总结。三者默认写入 `<workspace>/signoff/`，接受 `-o` 以及常规的 `--project` 和可选的受管 `--workspace NAME` 选择器：

```bash
uv run ecc report qor --project gcd
uv run ecc report checklist --project gcd --workspace default
uv run ecc report summary --project gcd
```

### 签核

流程完成后，审阅并导出签核包：

```bash
uv run ecc signoff inspect --project gcd       # 就绪度审阅（blocked 也返回 0）
uv run ecc signoff export -o gcd.tar.gz --project gcd [--include-debug]
```

`inspect`/`export` 会先刷新步骤分析（与 GUI 一致）。它们使用选定项目及其受管 `--workspace NAME`；只有一个活跃 workspace 时自动选中。

项目配置是 CLI 的输入面：

```toml
[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/gcd.v"]
# 非 RTL 范围可按需声明入口输入：
# netlist = "inputs/gcd.v"
# golden_netlist = "inputs/gcd-golden.v"
# def = "inputs/gcd.def"
# sdc = "constraints/gcd.sdc"
# spef = "inputs/gcd.spef"
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "/path/to/ics55"

[flow]
preset = "rtl2gds" # rtl2gds | syn_sta | synthesis_lec
```

filelist 模式下把 `design.rtl` 设为单个 filelist 路径，如 `rtl = ["rtl/filelist.f"]`。多 RTL 源应列在 filelist 里，而不是写多个 `design.rtl` 条目。

## 运行时解析

### Yosys

`chipcompiler/tools/yosys/utility.py` 的解析优先级：

1. 经 `CHIPCOMPILER_OSS_CAD_DIR` 的捆绑运行时；
2. 系统 PATH 中的 `yosys`。

运行时处理：

- `get_yosys_command()` 做无副作用探测；
- `get_yosys_runtime()` 返回供子进程使用的 `(command, env)`；
- `check_slang_plugin()` 执行预检 `yosys -p "plugin -i slang"`。

找不到 Yosys 时，用 ECC 安装脚本的 `--with-toolchain` 安装受管工具链（见 [README](../README.cn.md#安装)）。安装脚本的 wrapper 会导出 `CHIPCOMPILER_OSS_CAD_DIR` 与 `CHIPCOMPILER_ICS55_PDK_ROOT`。指向已有的 OSS CAD Suite：

```bash
export CHIPCOMPILER_OSS_CAD_DIR=/path/to/oss-cad-suite
```

### Sizer

Sizer 集成依赖外部 [`ecc-sizer`](https://github.com/openecos-projects/ecc-sizer) 仓库单独构建。在 ECC 仓库之外克隆：

```bash
git clone --recursive https://github.com/openecos-projects/ecc-sizer /path/to/ecc-sizer
cd /path/to/ecc-sizer
git submodule update --init --recursive
```

用 Sizer 自己的开发环境构建：

```bash
nix develop
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target Sizer -j "$(nproc)"
```

可执行文件预期位于：

```text
/path/to/ecc-sizer/build/src/Sizer
```

ECC 开发时，在跑流程或测试前把可执行文件目录加入 PATH：

```bash
export PATH=/path/to/ecc-sizer/build/src:$PATH
which Sizer
```

命令名在 Linux 上大小写敏感。当前 ECC 的探测逻辑先找 `Sizer`，再从该二进制向上查找含 `src/sizer_os.tcl` 的 Sizer runtime root。如果可执行文件来自不在 Sizer 检出树内的 wrapper，还需设置：

```bash
export CHIPCOMPILER_ECC_SIZER_ROOT=/path/to/ecc-sizer
```

ICS55 GCD 工具集成测试：

```bash
nix develop
export PATH=/path/to/ecc-sizer/build/src:$PATH
export CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/ics55-pdk
.venv/bin/python -m pytest test/integration/test_rtl2gds_flow.py::test_ics55_gcd -q -s
```

### PDK

`chipcompiler/data/pdk.py` 中 `get_pdk("ics55")` 的解析优先级：

1. 显式的 `pdk_root` 参数；
2. `CHIPCOMPILER_ICS55_PDK_ROOT` 环境变量；
3. 旧的 `ICS55_PDK_ROOT` 环境变量；
4. 默认：ecc 检出目录旁的 `../pdk/icsprout55-pdk`（ecos-studio 工作区布局）。

后端支持 `POST /api/workspace/set_pdk_root` 设置运行时路径。workspace 创建时会把解析出的 root 持久化到 `home/params.toml` 的 `pdk_root`。

示例：

```bash
CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/pdk uv run ecc
```

## 常见工作流

### 调试流程步骤

1. 查看 `workspace_step.logs/` 的工具输出；
2. 检查 `workspace_step.config/` 的配置；
3. 核对 `workspace_step.input/` 的文件；
4. 用项目和受管 workspace 名原地复现或续跑失败：

```bash
project=/path/to/project
workspace=default

# 从首个未成功步骤续跑（不给选择器时的默认行为）。
.venv/bin/ecc run --project "$project" --workspace "$workspace"
.venv/bin/ecc run --project "$project" --workspace "$workspace" --resume

# 重跑持久化 flow 中包含式的 CTS 到 route 范围。
.venv/bin/ecc run --project "$project" --workspace "$workspace" --from CTS --to route

# 只跑一个步骤；已成功过则加 --force。
.venv/bin/ecc run --project "$project" --workspace "$workspace" --only place
.venv/bin/ecc run --project "$project" --workspace "$workspace" --only place --force
```

`--resume`、`--only` 与范围三者互斥，`--force` 只能与 `--only` 组合。`--workspace` 可与 `--project` 组合；新范围不能与 `--overwrite` 组合。步骤名使用规范的 flow 别名。

workspace 模式原地修改 workspace：每个被执行步骤的 `output/` 会被替换，其下游步骤标记为 `Unstart`，后续 resume 会重跑它们。重跑步骤会从 `home/params.toml` 重新生成 `workspace/config/*.json`，因此请调整参数而不是手改生成的配置；需要保持不变的已报告 workspace 请自行留档。

Python 层调试可直接调同一 CLI 模块：

```bash
.venv/bin/python -m chipcompiler.cli.main run \
  --workspace "$workspace" \
  --only place \
  --force
```

### 修改流程步骤序列

1. 编辑 `EngineFlow.build_default_steps()` 或使用 `add_step()`；
2. 用 `flow.save()` 持久化到 `workspace.flow.json`；
3. 用 `flow.run_steps()` 运行；已成功步骤会跳过；
4. 用 `clear_states()` 重跑。

## 仓库约定

贡献者约定不在此重复：见 [../CLAUDE.md](../CLAUDE.md)（行为准则、测试放置、模块体积、避坑清单）与 [review-guidelines.md](review-guidelines.md)（评审标准）。

## 相关文档

- [examples/](examples/) - 示例项目与 CLI 用法
- [English version](development.md)
