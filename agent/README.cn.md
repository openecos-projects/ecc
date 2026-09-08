# `ecc-agent-rpc` 入口说明

`pyproject.toml` 中的如下声明会在安装 ECC 时生成独立可执行文件：

```toml
scripts.ecc-agent-rpc = "agent.rpc_server:main"
```

它是 ECOS Agent 专用的 ECC JSON-RPC 边车进程入口。桌面端或 Agent
运行时启动该进程，通过标准输入发送请求，并从标准输出读取结果；它不是
供交互式使用的 `ecc` CLI，也不替代通用的 `ecc rpc serve --stdio`。

## `main()` 做什么

入口实现位于 [`rpc_server.py`](rpc_server.py)。`main()` 保持很小，只完成
三个启动职责：

1. 调用 `multiprocessing.freeze_support()`，使打包后的 Windows 进程可以安全
   创建子进程；
2. 创建 `AgentRuntimeServer`，在通用 ECC runtime 方法之上注册 Agent 方法；
3. 将二进制 `stdin`/`stdout` 和该 server 交给
   `chipcompiler.runtime.stdio_server.run_stdio_server()`。

这样，入口不复制 transport、JSON-RPC 分发或业务执行逻辑。传输层统一处理
请求帧、响应串行写出、`runtime.event` 通知和 `rpc.shutdown`；Agent 行为由
`AgentRuntimeServer`、`FlowAgentRuntimeApi` 及其受控 workspace API 实现。

## 协议与能力

该进程使用带 `Content-Length` 头的 JSON-RPC 2.0 stdio 协议。标准输出只可写入
协议帧，诊断和工具输出应写入标准错误或 workspace 日志，避免破坏客户端解码。

`rpc.hello` 返回的 capabilities 包含通用 runtime 方法，以及 Agent 专用方法：

- `agent.runtime_preflight`：检查 Agent 候选执行所需运行时；
- `workspace.extract_foundation`：提取已完成 workspace 的 foundation 数据；
- `candidate.export_capabilities`、`candidate.bind_input`、
  `candidate.materialize`：查询或准备受控候选；
- `candidate.rerun`、`candidate.resume`：启动或恢复受控候选执行。

方法名、请求模型和处理函数的权威定义在 [`methods.py`](methods.py)。入口收到
请求后会将 camelCase 字段归一化为请求模型字段；无效字段或重复字段返回
`invalid_request`，不会转化为任意命令执行。

## 运行边界

`ecc-agent-rpc` 仅暴露已注册的 typed RPC 方法。它不接收自然语言计划、不选择
优化参数，也不执行调用方提供的任意 shell 命令。候选操作仍由 Agent runtime 的
参数校验、workspace 边界和执行回执约束。

启动 `AgentRuntimeServer` 时会调用 [`runtime_env.py`](runtime_env.py) 处理可选的
打包 Sizer 运行时路径；这只准备运行环境，不代表一次 physical-design flow 已
执行成功。实际客户端应先使用 `rpc.hello` 协商能力，并保留 operation 事件与
workspace 产物作为执行证据。

## 维护约定

- 新增 Agent RPC 方法时，同时更新 `methods.py` 的 `AGENT_RUNTIME_METHODS`、
  请求模型、workspace API 和对应测试；`rpc_server.py` 通常无需修改。
- 修改 stdio framing 或通用 runtime 行为时，应修改 `chipcompiler/runtime/` 并
  评估 `ecc rpc serve --stdio` 与 `ecc-agent-rpc` 两个入口。
- 直接调试可运行 `python -m agent.rpc_server`，但输入必须是合法的
  `Content-Length` JSON-RPC 帧；普通命令行参数不会被解析为 RPC 请求。
