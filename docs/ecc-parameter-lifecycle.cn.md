# ECC 参数生命周期

本文面向 ECC 维护者和集成方，是描述 workspace 行为的语义契约。本文
说明参数值如何从声明流向运行中的步骤，以及沿途有哪些机制保护持久化
状态。本文不是用户命令参考；命令和文件字段请参阅
[CLI 配置参考](../chipcompiler/docs/ecc-config-ref.cn.md) 和
[CLI 用户指南](../chipcompiler/docs/ecc-user-guide.cn.md)。

## 优先级矩阵

**新建（fresh）** workspace 时（`ecc run`、`ecc workspace refresh`），
每个 key 按以下优先级取最高层生效：

| 层 | 来源 | 生效范围 |
| --- | --- | --- |
| 1 | `ecc run --set key=value`（可重复） | 仅新建 run |
| 2 | `ecc.toml` `[params.*]` | 仅新建 run |
| 3 | `project.json` `base_design.parameters` 与选中 workspace 条目的 `parameter_patch` 合并（manifest 基础层） | manifest 工程 |
| 4 | schema 默认值（`chipcompiler/data/config_params/`、legacy 注册表模板） | 始终 |

manifest 基础层是"地板"而不是"覆盖"：`ecc.toml` 与 `--set` 的值叠加在
它之上，因此已声明的 base 值只输给更高层、只赢过 schema 默认。

**已有（existing）** workspace 复用其持久化的 `home/params.toml`，
不再重新解析上述矩阵：

- `--set` 直接被拒（`set_requires_fresh_run`）；
- `ecc.toml` `[params]` 被忽略，并给出 `params_ignored_on_existing_run`
  警告，仅对 `ecc.toml` 值与 workspace 当前值不同的参数披露
  `ecc param set --workspace` 修复命令；
- 修改应走 `ecc param set/unset --workspace NAME`：它编辑
  `home/params.toml` 并刷新派生的 `config/*.json`。

`skip_steps` 遵循同一收敛方向：显式的 `ecc.toml` `[flow] skip_steps`
（含空列表 `[]`）优先于 `project.json` workspace 条目，后者优先于代码
默认 `("lec",)`；两个面声明的策略不一致时，`ecc run`/`ecc check`
发出 `skip_steps_shadowed` 警告并指明获胜来源。

## 生效时机

- **新建 run / refresh**：参数在创建时固化进 workspace——写入
  `home/params.toml`，并由此（连同 PDK）派生 `config/*.json`。
  此后 CLI 不在派生路径之外重写这些配置。
- **已有 run**：持久化的 `home/params.toml` 是权威。直接重跑默认保留
  用户参数（`flow.run` / `prepare_workspace_for_rerun(preserve_user_inputs=True)`）：
  被重跑的步骤按当前参数重新生成配置输入，下游步骤标记为未开始。
- **GUI 运行**：`workspace.open` 本身不做配置刷新。派生配置在两条时机刷新：通过 GUI 保存参数时（`workspace.step_configuration.update` / `workspace.configuration.update`），以及运行前 flow 中存在 stale 步骤时。因此同一 `home/params.toml` 下 GUI 会话与 CLI 会话收敛到同一套 `config/*.json`。

## CLI 与 GUI 差异

| 关注点 | CLI（`ecc`） | GUI（ECOS Studio） |
| --- | --- | --- |
| spec-mode workspace 的参数意图 | `home/params.toml` | `engineering-snapshot.json` 的 `workspaceSpec` |
| 快照版本号 | 显式 `--workspace` 运行路径不感知 | `workspaceRevision` 乐观并发 |
| 漂移检测 | `params.toml` 新于快照时给出 `workspace_spec_drift` 警告 | 快照校验（Studio 侧） |
| 覆盖手工编辑的 `config/*.json` | `ecc workspace refresh` 以 `derived_configs_modified` 拒绝（列出文件），除非 `--force` | 派生刷新会记录 hash 清单（`home/config-derived-manifest.json`） |
| manifest 状态写回失败 | `manifest_write_back_failed` 错误记录并附修复命令；run 结果不受影响 | n/a |

漂移与 refresh 防护刻意做成单向绊线，而非双向同步：触发时优先使用
`ecc param set --workspace`（或改 `ecc.toml` 后 refresh），而不是手工
编辑生成文件。

## schema 版本化

workspace 文件带有显式 schema 版本，来自更新版本的文件会响亮报错，
而不是被静默解析：

| 文件 | 字段 | 当前版本 | 说明 |
| --- | --- | --- | --- |
| `home/params.toml` | `schema_version` | 1 | 缺省 = 版本 0（前版本化时代）；版本 0 仍走 legacy `parameters.json` 迁移 |
| `home/flow.json` | `schema_version` | 1 | 缺省 = 版本 0；写入处盖章，reconcile 拒绝更高版本 |
| `home/engineering-snapshot.json` | `schemaVersion` | 2（生产）、3（预备） | 与 GUI 共享；v2→v3 是显式只写迁移通道 |

注册表位于 `chipcompiler/data/schema_migrations.py`：
`{文件类型: {目标版本: 迁移函数}}`，在 workspace 打开时按版本升序依次
应用。`params.toml` 或 `flow.json` 声明的版本高于支持范围时抛出
`unsupported_schema_version`，错误信息带文件路径与版本号——绝不静默解析。
`engineering-snapshot.json` 不符合支持的形态时则抛出
`EngineeringSnapshotError`（`invalid Engineering Snapshot: <路径>`），
不含版本号；v2 与 v3 均原生加载，v2→v3 迁移仅登记供发现——它是显式
只写通道，加载链不会自动应用。

## Engineering Snapshot 载荷边界

`home/engineering-snapshot.json` 是有界索引，不是完整 EDA 报告的容器。
`build_workspace_analysis()` 会保留所有已声明分析文件的 artifact 元数据，
但只有同时满足以下边界时才内联 JSON 正文：

| 边界 | 上限 | 超限行为 |
| --- | ---: | --- |
| 单个 analysis 或 LEC JSON 正文 | 256 KiB | `status: oversized`、`data: null`，保留 artifact 引用 |
| 所有内联 analysis 正文累计 | 2 MiB | 后续正文使用 `ANALYSIS_INLINE_BUDGET_EXCEEDED` |
| Signoff checklist 正文 | 1 MiB | checklist 与 signoff 投影变为 unavailable |
| 序列化后的 Engineering Snapshot | 16 MiB | 写入以 `EngineeringSnapshotError` 失败；原子写保证旧文件不变 |

不可用分析文件的契约为
`{artifactId, status: "oversized", reasonCode, data: null}`。Studio 必须接受
该状态，同时继续暴露 `flow` 和快照中其余有效分区。测试必须覆盖单文件
上限、累计 analysis 预算、最终写入上限和 Studio 校验。不得为了容纳报告
而提高 Studio 读取上限；完整报告应保持为 artifact，其正文不进入快照。

STA corner 明细的发现不依赖聚合文件 `sta_timing_issues.json` 的正文。即使
聚合 analysis 正文超限，ECC 仍会按确定性顺序索引最多 32 组
`feature/<process>/<rc>/qor_summary.json` 和 `timing_paths.json`，并将它们
记录为可校验 artifact。Studio 通过 artifact ID 按需读取并校验用户选中的
单个 corner；真实文件引用和报告正文不会进入 renderer 可见的快照投影。
