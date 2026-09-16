# ECC Agent Runtime（`agent/`）

`agent/` 是 ECC 的 **Flow Agent 运行时**：在 `chipcompiler` 标准 runtime 之上构建的
受控、可审计的流程代理执行层。它通过内部 server composition 注册到唯一的
`ecc rpc serve` JSON-RPC 入口，供 ECOS Studio 的 GUI 前端与 `ecos_agent`
受控优化后端驱动。产品中只发布 `ecc` 可执行文件，不再提供独立的 Agent sidecar。

它只做确定性的执行与证据记录：**决策不在这里**。`agent/` 不包含任何 LLM
代码，不解析自由文本指令，也不直接执行 shell 命令；流程决策由上层
`ecos_agent`（见 ECOS Studio 仓库）完成，每个动作以显式 schema 的 RPC 方法
抵达本层，经参数校验与允许列表检查后执行，并留下可复核的产物与回执。

## 职责总览

- **Agent 流程适配**：为 Agent 场景定制流程引擎行为（DRC 阶段注入、观察者
  事件流、渲染门控、内存监控、无头运行下的绘图抑制）。
- **隔离候选执行**：为参数候选创建隔离 workspace，配置固化（materialize）、
  上游输入绑定、独立 worker 进程重跑与断点续跑（resume），产出 hash 绑定的
  配置/检查点回执。
- **参数运行时观测**：对五个受控 DREAMPlace 参数与两个受控 Floorplan 参数
  进行运行时观测，生成 hash 绑定的参数应用回执，供上层做效果归因。
- **基础数据提取（foundation data）**：从已有 workspace 的 LEF/DEF/STA/DRC/
  布线证据中提取带表结构契约的可审计数据表，供离线分析与建模使用。
- **全角 STA 并行**：以隔离的原生进程并行执行全角 STA，并提供调度基准测试。

## 设计原则

1. **受控执行**：每个 RPC 方法都有 frozen dataclass 请求模型与显式校验；
   客户端按方法允许列表访问；写入 workspace 的路径一律校验不得越界。
2. **可审计**：候选配置、输入绑定、Floorplan 模式覆盖、参数回执均以
   canonical JSON + SHA-256 摘要落盘，配置与检查点回执必须配对一致
   （candidate contract），否则拒绝执行。
3. **可复现**：候选 workspace 从父 workspace 克隆，重跑集合、输入绑定与
   配置覆盖全部持久化，resume 复用原候选记录且不改变历史语义。
4. **进程隔离**：DREAMPlace 与 sizer 存在进程全局状态（配置单例、原生日志
   重定向），同进程并发候选会互相覆写；候选的阶段循环在独立 worker 进程
   中执行，全角 STA 同样使用隔离原生进程。
5. **不反向依赖**：`agent/` 依赖 `chipcompiler` 的公开 runtime 接口并继承
   扩展，不修改其行为；除观测回执的结构化输入外，不依赖 `ecos_agent`。
6. **不改变普通 Flow**：普通 `workspace.*` 与 `flow.*` 继续使用通用 Workspace
   Runtime API 和 Engine Flow；只有 Candidate Execution 在自己的 operation
   边界内构造 Candidate Flow。

## 代码结构

```text
agent/
├── server.py            # AgentRuntimeServer：在通用 RuntimeServer 上组合 Candidate 方法
├── methods.py           # Agent RPC 方法表（RuntimeMethodSpec 声明）
├── requests.py          # RPC 请求模型（frozen dataclass + 校验）
├── workspace_api.py     # FlowAgentRuntimeApi：Candidate RPC 处理层
├── engine.py            # AgentEngineFlow：流程引擎覆盖（观察者、渲染门控、监控）
├── tools.py             # Agent 侧步骤执行适配（固化重放、模式覆盖、STA 分发）
├── plot.py              # 无头运行下抑制显示绘图的绘图适配
├── runtime_env.py       # sizer 运行时预检与隔离加载环境
├── floorplan_mode.py    # 隔离候选的 Floorplan 模式（die_util/die_size）覆盖
├── candidate_clone.py   # 候选 workspace 克隆的忽略规则
├── candidate_worker.py  # 隔离 worker 进程中执行候选阶段循环
├── candidate_resume.py  # 失败候选在原 workspace 上的断点续跑
├── sta_parallel.py      # 全角 STA 并行调度（隔离原生进程）
├── sta_benchmark.py     # STA 调度基准测试（隔离副本上比较方案）
└── data/                # 候选与观测的数据模型、注册表和落盘产物
    ├── candidate_registry.py             # 受控 knob 与后端需求的静态注册表
    ├── candidate_capabilities.py         # 当前 workspace 的候选能力查询
    ├── candidate_materialization.py      # 可重放的配置固化与回执校验
    ├── candidate_input_binding.py        # 受控上游输入绑定（阶段间数据边）
    ├── candidate_contract.py             # 配置/检查点回执的配对一致性检查
    ├── candidate_artifacts.py            # canonical JSON、SHA-256、原子写盘工具
    ├── parameter_runtime_observer.py     # DREAMPlace 五参数运行时观测
    ├── floorplan_parameter_observer.py   # Floorplan 两参数运行时观测
    ├── parameter_application_receipt.py  # hash 绑定的参数应用回执生成
    ├── observed_callable.py              # 保持原属性的观测包装
    └── foundation/                       # workspace 证据提取子包
        ├── extractor.py                  # 提取流水线（profile: iccd_full_v1）
        ├── schema.py                     # ExtractionResult
        ├── parsers/                      # LEF/DEF/STA/DRC/布线日志等解析器
        ├── grid/                         # GCell 网格规范化
        ├── table_contract.py             # 数据表结构契约与写出
        └── writers.py                    # JSON/JSONL 写出
```

分层关系：`ecc rpc serve` → `stdio_server.main()` 组合 `AgentRuntimeServer`
（方法分发、错误码映射）→ `methods`/`requests`（schema）→ `workspace_api`
（Agent RPC 处理器）→ `engine`/`tools`/`candidate_*`（执行基础设施）→
`data/*`（注册表、固化与回执落盘）。

## RPC 方法面

`AgentRuntimeServer` 继承基础 runtime 的全部方法（workspace 生命周期、配置
读写、`flow.run`/`flow.run_step`、operation 状态与取消、快照等，完整清单见
`chipcompiler/runtime/methods.py` 与 `docs/rpc-guide.md`），并在能力协商
（`rpc.hello`）中追加声明以下方法：

| 方法 | 作用 |
| --- | --- |
| `workspace.extract_foundation` | 从 workspace 证据提取 foundation 数据表 |
| `candidate.capabilities` | 查询当前 workspace 的候选能力（受控 knob、后端需求） |
| `candidate.rerun` | 原子克隆候选 workspace 并在隔离 worker 中重跑目标阶段 |
| `candidate.resume` | 在原候选 workspace 上断点续跑失败的候选 |

传输与分帧协议与基础 runtime 一致（`Content-Length` 分帧的 JSON-RPC 2.0），
详见 `docs/rpc-guide.md`。输入绑定、配置 materialization 和运行时预检保留为
`candidate.rerun` 的内部步骤，不作为独立 RPC 方法。

## 候选重跑生命周期

一次受控候选评估的公开调用序列：

1. **能力查询**：`candidate.capabilities` 返回目标阶段允许的受控 knob 集合
   与后端需求，上层只能在该集合内提参数。这是查询，不写第二份参数目录。
2. **原子重跑**：`candidate.rerun` 在 ECC 内部完成预检、源 workspace 快照、
   克隆、输入绑定、参数固化、Floorplan 模式覆盖，并在独立 worker 进程中按
   目标阶段重跑。事件经观察者流式回传，结果与状态摘要落盘。失败的准备步骤
   不会留下可执行的半成品 Candidate。
3. **续跑**：失败的候选可用 `candidate.resume` 在原 workspace 上继续，
   保留原候选记录与 Floorplan 模式，不改变历史语义。取消与恢复复用通用
   Operation 生命周期。

Floorplan 模式覆盖（`die_util`/`die_size`）只作用于隔离候选：随请求显式
给出、持久化到候选 workspace 的 `analysis/floorplan_mode.v1.json`，不影响
源 workspace 与普通 ECC 流程。

## 客户端与联合契约

本运行时有两个独立实现的客户端，遵守同一契约：

- **Electron 前端**（GUI 流程执行）：
  `ecos/gui/apps/desktop-electron/electron/services/eccRpc/`
- **Agent 后端**（受控自动优化）：
  `ecos/agent/src/ecos_agent/optimization/ecc/rpc_client.py`

传输、超时、错误恢复与可执行文件解析的共同契约见 ECOS Studio 仓库的
`ecos/agent/docs/ecc-agent-rpc.md`；修改本层的 RPC 表面或事件语义时，须
同步该文档与两侧客户端。生产路径应通过 Electron Product Command 调用
`ecc rpc serve`，而不是再启动第二个 Agent executable。

## 开发与测试

```bash
# 启动 stdio RPC 服务（Candidate 方法已组合进该入口）
uv run ecc rpc serve --stdio

# 运行本目录测试（与 chipcompiler 的 test/ 互相独立）
uv run pytest agent/test

# Lint 与格式
uv run ruff check agent/
uv run ruff format agent/
```

测试按被测模块就近放置于 `agent/test/`；foundation 提取器相关的基线数据
与其表格契约测试同样位于该目录。
