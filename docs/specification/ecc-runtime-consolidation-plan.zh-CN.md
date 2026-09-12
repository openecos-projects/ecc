# ECC Runtime Consolidation v1

状态：已确认，准备实施

本文是 ECC 与 ECOS Studio 的联合实施方案。目标是删除
`ecos-studio-runtime`/`ecos-ecc-runtime-adapter` 的独立实现，同时保留
ECOS Studio 的全部能力，包括 Workspace Snapshot、Project Comparison、QoR、
Signoff、Layout/Floorplan 编辑、取消、恢复和后台执行。

## 1. 最终边界

```text
ECC Engine       领域事务、配置、Flow 执行、Revision、Engineering Snapshot
ECC Runtime      ECC 内部 JSON-RPC、Session、Operation、Ledger、事件、取消、恢复
ECC CLI          CLI 解析、输出和只读查询；写操作调用 ECC Engine
Electron         产品策略、权限、路径授权、进程监督、Snapshot 读取和展示
```

- 只发布一个 `ecc` 可执行文件。普通 CLI 与隐藏的 `ecc rpc serve` 使用同一
  可执行文件、同一 Python 环境和同一 ECC 版本。
- ECC Runtime 是 ECC 的私有 Studio 集成接口，不承诺第三方协议兼容性。
- 每个有执行或编辑工作的 Workspace 使用独立 Runtime 进程和故障域。
- Workspace 无活动 Operation、Layout Edit 或 finalization 工作后，Electron
  释放该 Workspace Runtime；Workspace 无关请求使用一个应用生命周期内的懒加载
  Control Runtime，但它仍是同一 `ecc` 进程模型中的路由细节。
- Electron Agent、Quick Start 和后台产品命令必须走
  `Electron Product Command -> ECC Runtime -> ECC Engine`，不能直接导入 ECC
  或绕过 Runtime 调用 Engine。

## 2. Snapshot 决策

### Engineering Snapshot

`home/engineering-snapshot.json` 是 Studio 的 committed engineering read
model，不是 CLI 查询 API。

- ECC 是唯一生成者和写入者。
- Workspace 创建、结构更新、配置更新、rerun preparation、保存 Layout 和每个
  Flow Step Commit 都按统一 Revision 提交 Snapshot。
- 文件保持现有 schema v2 和文件名；`engineering-snapshot.stale.json` 继续表示
  单个 stale predecessor。
- Flow 状态、Snapshot 和 commit metadata 必须以 Atomic Engineering Commit
  一起暂存、验证并原子替换；任何失败都保留前一组 committed 文件且不发
  `workspace.committed`。
- Electron 直接读取并校验 Snapshot（路径、大小、JSON、schema、Workspace ID、
  Revision、section 和 Artifact 指纹），Runtime Event 只作为失效提示。
- Snapshot 缺失、损坏或不支持时不回退到旧文件、不自动转换、不在查询时物化；旧
  Workspace 使用显式 `ecc workspace refresh`、重新创建或已有 `--overwrite` 流程。

### Execution Snapshot

`workspace.snapshot` 是 Runtime 的运行态视图，由 live Session、Active
Operation 和有界 Operation Ledger 重建；它不替代 Engineering Snapshot。

- Ledger 始终保留 Active Operation 和最近 256 个 terminal Operation。
- 更早记录及其 command-id 去重结果可以删除，不提供用户历史记录功能。
- 进程重启后无法确认的非终态 Operation 统一恢复为 `interrupted`。
- Event 可以重复、延迟或丢失；序列缺口或重启后必须重新查询 Execution Snapshot
  和 Engineering Snapshot。

## 3. 一致性、锁和 Revision

- Workspace Revision 是唯一单调序列：创建为 1，配置/结构更新、rerun preparation、
  Layout 保存和每个 Step Commit 各推进一次。
- Runtime 与 CLI 使用同一个 Workspace Ownership Lock（Workspace 同级的
  `<workspace>.lock`）。Runtime fail-fast 返回 `workspace_busy`；同一 Runtime
  已有冲突 Operation 返回 `operation_conflict`。CLI 保持现有阻塞等待行为。
- 同时触及 Project Manifest 和 Workspace 的 API 固定锁顺序：
  `Project Manifest Lock -> Workspace Ownership Lock`。
- Workspace-only 只取得 Workspace Lock；Manifest-only 只取得 Manifest Lock。
- Runtime `workspace.open` 是短暂的 Open Transaction：校验 Snapshot、Bindings、
  Ledger 和恢复状态后释放锁。Operation 或 Layout Edit 才持有长生命周期锁。
- Layout Edit 从 `layout.edit.begin` 持锁到 save/discard/close/process loss；save
  先提交 Revision 与 Snapshot，再释放锁；进程丢失不发布未提交编辑。
- Bindings 只保存为机器本地绝对路径，不能写入 Descriptor/Manifest、推进 Revision
  或单独生成 Snapshot。

## 4. CLI 合同

### 写路径

下列 CLI 写操作全部改为直接调用 ECC Engine 的事务和提交路径：

- Workspace 创建、Project 管理的 create/update 和 `ecc workspace refresh`；
- `ecc param set/unset --workspace`；
- rerun preparation、Layout 保存和 Flow 执行；
- `ecc run --overwrite`。

CLI 继续负责参数优先级、命令名称、阻塞锁、`--overwrite` 临时备份、输出记录和
错误退出码。CLI 不调用 ECC Runtime，也不保留自己的 Snapshot/参数回滚实现。
Project Manifest 与 Workspace 的联合更新使用现有 ECC API staging、Manifest 原子
更新和失败回滚，不引入 two-phase commit。

CLI 解析 `--resume`、`--from`、`--to`、`--only`、`--force` 和 preset，解析为规范化
有序 `step_ids` 后传给 Engine `ExecutionPlan`。Engine 负责依赖验证、执行、提交和
Revision；Engine 不认识 CLI flag 名称。

Engine `ExecutionResult` 至少提供 `succeeded`、最终状态、可选 `step_id`、按执行顺序
排列的 `executed_steps` 和可选 `failed_step`。CLI 只把它映射为现有
`StepRunResult`/`CommandResult`，不重新扫描 `flow.json` 推断结果。

没有显式 rerun selector 且目标已经完成时，Engine 返回成功 no-op：不创建 Operation、
不写 Workspace、不推进 Revision、不刷新 Engineering Snapshot。显式 `--force`、
`--from`、`--only` 等仍然是 mutation。

### 读路径

第一阶段保留现有查询输出和实现边界：

- `status` 直接读取 `home/flow.json`；
- `report step` 直接读取 Flow 和声明的 Step artifacts；
- `signoff inspect` 保留现有 Signoff 查询结果；
- `report qor/checklist/summary` 保留现有报告构建和写入默认或显式的
  `signoff/` 报告文件。

这些命令都不能创建或刷新 Engineering Snapshot。需要加载 Workspace 对象的报告和
Signoff 查询必须使用 `load_workspace(read_only=True)`，不能触发迁移、事务恢复、
配置文件名重写或 Workspace 日志写入；报告目标文件是唯一有意写入。

## 5. ECC 实施步骤

### Phase 0：基线与冻结

1. 固定 ECC git commit、Studio gitlink、当前磁盘文件 schema 和现有 CLI/RPC 测试。
2. 建立跨组件 fixture：ECC 创建的 Workspace、Studio 创建的 Workspace、已有
   Snapshot、Snapshot-less Workspace、无效 Snapshot、revision 冲突和 lock 占用。
3. 记录现有 `ecos/runtime-adapter` 的模块、测试、依赖、启动脚本和打包资源清单。

### Phase 1：ECC ownership migration（保持线协议兼容）

1. 将 `ecos/runtime-adapter/ecos_runtime_adapter/*.py` 直接移动到 ECC 的
   `chipcompiler/runtime/`，按现有模块拆分重写 import；测试移动到 `test/runtime/`。
2. 把 `jsonrpcserver>=5.0.9,<6` 移入 ECC `pyproject.toml`，删除 Adapter
   requirements、wrapper、重复 package、重复测试和独立 Adapter binary。
3. 保留 JSON-RPC method、字段、错误码、事件和内部旧 aliases，确保旧 Studio 与
   新 ECC 的 parity；普通 CLI help 隐藏 `rpc`。
4. 在 Engine 中实现统一 Workspace Ownership Lock、Manifest->Workspace 锁顺序、
   Atomic Engineering Commit、统一 Revision 和 Stable Domain Error 映射。
5. 让 Engine 的 create/update/configuration/rerun/layout/execute 共享同一提交路径；
   Flow Step Commit 必须先完成 Flow + Snapshot，再通知 Runtime。
6. 将所有 CLI Workspace 写操作接入 Engine；保留只读命令输出和报告文件输出。
7. 将 report/Signoff 的 Workspace hydration 改为 `read_only=True`，补充无副作用断言。
8. 为 `ExecutionPlan`、`ExecutionResult`、no-op、`workspace_busy`、
   `operation_conflict`、revision conflict、overwrite rollback 和 Snapshot failure
   补齐 Engine/CLI/runtime 测试。
9. 运行 ECC Ruff、全量 Python tests、PyInstaller 和 framed-stdio Runtime smoke。

### Phase 1.5：Studio 切换与跨仓库验证

1. 先合并并发布 ECC Phase 1，再更新 Studio ECC gitlink。
2. Electron 启动命令切换为 pinned `ecc rpc serve --stdio --persistent-db`，删除
   Adapter binary staging、resource assertions 和独立 requirements 安装。
3. 保留现有 Workspace Runtime/Control Runtime 路由、事件、取消、恢复、Layout 编辑
   和 Project Snapshot reader；只替换后端进程来源。
4. 验证 ECC 生成 Workspace 可被 Studio 打开，Studio 生成 Workspace 可继续被 CLI
   执行；验证 Project Comparison 直接读取持久化 Snapshot。
5. 运行 Studio frozen install、typecheck、lint/format、Electron/Renderer tests、
   build、desktop smoke 和 parent packaging build。

### Phase 2：协议清理（必须完成）

Phase 2 只有在 Phase 1 parity、打包和跨组件 smoke 全部通过后开始，不能无限期保留
兼容分支：

1. 强制 Control Runtime 和每个 Workspace Runtime 在任何业务命令前完成 `rpc.hello`。
2. 使用 private protocol v2，返回 `protocolVersion`、ECC package version 和明确
   capabilities；缺失或不匹配在任何写操作前返回 `runtime_incompatible`。
3. 删除过渡性的 `workspace.engineering_snapshot` RPC，统一为 Electron 直接读取
   `home/engineering-snapshot.json`。
4. 删除 `adapterVersion`、`runtime.adapter.v1`、Adapter-named capability、旧 DTO、
   旧字段 aliases 和兼容错误映射。
5. 删除 `ecos-ecc-runtime-adapter` 名称、wrapper、资源断言和所有重复实现；CI 以
   grep/contract test 阻止旧名称回归。
6. 保留一个 Snapshot validator、一个 Runtime capability vocabulary、一个 private
   protocol version 和一个 canonical read path；ECC 与 Studio 作为一个 pinned update
   发布。

## 6. 失败与恢复语义

- Snapshot 提交失败：返回 `engineering_snapshot_commit_failed`，保留前一 Snapshot，
  Flow Operation 失败，不发送 committed event。
- Snapshot 缺失/损坏/版本不支持：查询返回稳定的 unavailable/invalid reason，不回退
  为 `unstart`，不自动写文件；显式 refresh、run 或 overwrite 才能修复。
- Runtime 无法确认进程被终止时：Ledger 恢复为 `interrupted`，不能伪装成
  `cancelled` 或 succeeded。
- 普通 cancel 只在 Flow Step 边界生效；运行中的 EDA 工具继续完成当前 Step。
- Force Quit 才会硬终止 Runtime，最多进行 3 秒清理，然后依靠 Ledger 恢复。
- 已有 `--overwrite` 的临时备份只用于失败恢复；成功后删除，不形成用户历史归档。

## 7. 验收与合并门禁

必须同时满足：

- ECC：Ruff、全量 Python suite、Engine/Runtime/CLI 聚焦测试、PyInstaller、framed
  stdio smoke（hello、create/open、Execution Snapshot、Flow、cancel、recovery）。
- Studio：frozen install、typecheck、lint/format、Electron/Renderer tests、build、
  desktop smoke、parent packaging build。
- 跨组件：ECC->Studio Workspace、Studio->CLI Workspace、overwrite rollback、
  Snapshot missing/invalid、revision conflict、Workspace Busy、background run、
  Force Quit recovery、Layout Edit lock lifetime、报告输出兼容。
- 打包产物：只包含一个 `ecc` executable，不包含 Adapter binary、wrapper 或第二套
  Python requirements。
- 只读门禁：status/report/signoff 查询不迁移、不恢复、不追加 Workspace 日志；报告
  命令只写其声明的报告目标。
- 事件门禁：事件重复、延迟、丢失和序列缺口都能通过重新查询 Snapshot 恢复，正确性不
  依赖 Renderer ACK。

## 8. 不在本方案内

- 不做旧 Workspace 或旧 Snapshot schema 的隐式迁移和 raw-file fallback。
- 不保留第二个 Adapter forwarding package、symlink 或独立 runtime binary。
- 不把 CLI 只读命令整体迁移为 Snapshot reader；后续若统一 read model，另立变更。
- 不实现用户可见的 Operation 历史、无限 Ledger、Snapshot 历史时间旅行或通用 Artifact
  浏览器。
- 不重做 Studio UI、QoR 算法、Signoff 判定、Project Manifest 领域归属或 ECC-FE。

## 9. 决策记录

本方案对应 Studio 架构 ADR-0033（ECC owns the private Studio runtime）以及 ECC
Headless Engine 既有 glossary。旧的 Studio-only Headless Engine Contract 文档只保留
作历史记录，不能覆盖本文确认的 CLI 共用 Engine、Snapshot 边界和 Phase 2 清理要求。
