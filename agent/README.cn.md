# Candidate Runtime 入口说明

ECC 发布 `ecc` 可执行文件，并附带 `ecc-agent-rpc` 兼容别名（同一二进制的
硬链接）。Candidate 方法通过内部 server composition 注册到统一的
`ecc rpc serve --stdio` 运行时；`ecc-agent-rpc` 也直接进入该运行时。

```toml
scripts.ecc = "chipcompiler.cli.main:main"
scripts.ecc-agent-rpc = "chipcompiler.runtime.stdio_server:main"
```

桌面端或离线研究客户端启动该进程，通过标准输入发送请求，并从标准输出
读取结果。这是通用 ECC JSON-RPC sidecar，也是 Candidate Execution 的唯一
产品入口。

## `ecc rpc serve` 做什么

`chipcompiler/cli/commands/rpc.py` 调用
[`stdio_server.main()`](../chipcompiler/runtime/stdio_server.py)。`main()`
保持很小，只完成启动职责：

1. 创建 `AgentRuntimeServer`，在通用 ECC runtime 方法之上注册 Candidate
   方法；普通 `workspace.*` 与 `flow.*` 仍使用通用 Workspace Runtime API；
2. 启动时准备可选的打包 Sizer 运行时路径；
3. 将二进制 `stdin`/`stdout` 和该 server 交给
   `chipcompiler.runtime.stdio_server.run_stdio_server()`。

这样，入口不复制 transport、JSON-RPC 分发或业务执行逻辑。传输层统一处理
请求帧、响应串行写出、`runtime.event` 通知和 `rpc.shutdown`；Candidate
行为由 `AgentRuntimeServer`、`FlowAgentRuntimeApi` 及其隔离执行实现。

## 协议与能力

该进程使用带 `Content-Length` 头的 JSON-RPC 2.0 stdio 协议。标准输出只可写入
协议帧，诊断和工具输出应写入标准错误或 workspace 日志，避免破坏客户端解码。

`rpc.hello` 返回的 capabilities 包含通用 runtime 方法，以及 Candidate 方法：

- `workspace.extract_foundation`：提取已完成 workspace 的 foundation 数据；
- `candidate.capabilities`：查询当前 workspace 的受控候选能力；
- `candidate.rerun`、`candidate.resume`：启动或恢复受控候选执行。

`agent.runtime_preflight`、`candidate.bind_input` 和 `candidate.materialize`
不是公开 RPC。预检、输入绑定和配置固化只作为 `candidate.rerun` 的内部步骤。

方法名、请求模型和处理函数的权威定义在 [`methods.py`](methods.py)。入口收到
请求后会将 camelCase 字段归一化为请求模型字段；无效字段或重复字段返回
`invalid_request`，不会转化为任意命令执行。

## 运行边界

`ecc rpc serve` 仅暴露已注册的 typed RPC 方法。它不接收自然语言计划、不选择
优化参数，也不执行调用方提供的任意 shell 命令。候选操作仍由 Agent runtime 的
参数校验、workspace 边界和执行回执约束。

启动 `AgentRuntimeServer` 时会调用 [`runtime_env.py`](runtime_env.py) 处理可选的
打包 Sizer 运行时路径；这只准备运行环境，不代表一次 physical-design flow 已
执行成功。实际客户端应先使用 `rpc.hello` 协商能力，并保留 operation 事件与
workspace 产物作为执行证据。

## 维护约定

- 新增 Candidate RPC 方法时，同时更新 `methods.py` 的 `AGENT_RUNTIME_METHODS`、
  请求模型、workspace API 和对应测试；`stdio_server.main()` 通常无需修改。
- 修改 stdio framing 或通用 runtime 行为时，应修改 `chipcompiler/runtime/`。
- 直接调试可运行 `uv run ecc rpc serve --stdio`，但输入必须是合法的
  `Content-Length` JSON-RPC 帧；普通命令行参数不会被解析为 RPC 请求。
