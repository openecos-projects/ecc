# ECC Candidate 执行库

`agent/` 提供确定性的候选 Flow 执行和证据生成能力，供离线优化工具复用。它是
Python 库，不是网络或 stdio 服务，也不再提供 ECC RPC 入口。

本包负责候选 Workspace 克隆、输入绑定、参数固化、失败候选续跑、foundation
数据提取和原生进程隔离。决策仍由上层 ECOS Agent 完成；本层只校验受限输入并
生成可审计产物。

边界如下：

- `operations.py` 仅协调候选执行，不承担 GUI Flow 生命周期。普通 GUI Flow 使用
  ECC CLI 进程目录和 Workspace `flow.json`。
- `runtime_support.py` 只保留候选 worker 需要的少量 Engine 适配，不包含 transport。
- `workspace_api.py` 是优化调用方使用的库 facade，不再挂载 method registry/server。
- DREAMPlace、sizer 和日志重定向具有进程全局状态，因此候选原生步骤仍在隔离
  worker 中运行。
- 执行前继续校验 Workspace 路径、固化配置、回执和摘要。

测试命令：

```bash
uv run pytest agent/test
```
