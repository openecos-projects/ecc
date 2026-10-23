# ECC Sweep 参考手册（参数网格实验）

本手册记录 `ecc sweep` 与 `ecc explore` 两个命令组：在隔离项目副本上进行的确定性
参数网格实验、证据优先的结果记录，以及显式的 promote 选定步骤。命令基础同样见
[CLI 用户指南 §11.5](ecc-user-guide.cn.md)；本文给出计划与结果 schema、执行模型和
排序规则的完整契约。

实现位于
[chipcompiler/cli/commands/experiments.py](https://github.com/openecos-projects/ecc/blob/main/chipcompiler/cli/commands/experiments.py)
与
[chipcompiler/cli/experiments/operations.py](https://github.com/openecos-projects/ecc/blob/main/chipcompiler/cli/experiments/operations.py)。

## 1. 模型

一个 **sweep** 是 `<project>/experiments/<name>/` 下的具名实验：

- **create** 冻结计划：给定参数取值列表的笛卡尔积，每个组合一个候选，顺序确定；
- **run** 逐个执行候选，每个候选在各自隔离的项目副本中进行，并记录终态证据；
- **compare / rank** 是对已记录结果的只读视图；
- **promote** 显式记录获胜候选；不会自动提升或应用任何参数。

当前版本以确定性和证据留存为主，暂不提供自动优化、分布式调度、多 SDC sweep
或自动替换 baseline workspace。

## 2. 快速上手

```bash
ecc sweep create --project /path/to/project --name density \
  --param place.target_density=0.60,0.65 \
  --param cts.max_fanout=16,32
ecc sweep run   --project /path/to/project --name density
ecc sweep compare --project /path/to/project --name density
ecc explore rank   --project /path/to/project --name density
ecc explore promote --project /path/to/project --name density --candidate candidate_0002
```

## 3. 磁盘布局

```
<project>/experiments/<name>/
├── sweep.json                  # 冻结的计划（§5）
├── results.json                # 每个候选的记录证据（§7）
├── pareto.json                 # 由 Pareto promote 写入（§4.9）
├── winner.json                 # 仅在显式选择后写入（§4.8–4.9）
└── candidates/
    └── candidate_0001/
        └── project/            # 该候选的隔离项目副本
            └── candidate_0001/ # 副本内该候选的 workspace
```

`sweep list` 恰好枚举含有 `sweep.json` 的 `experiments/*/` 目录。sweep 写入的内容
都在 `experiments/` 之下；项目 manifest、`ecc.toml` 和任何 baseline workspace 都
不会被修改。

## 4. 命令

所有命令接受 `--project DIR`（缺省：从当前目录发现项目）。`sweep create`、`sweep
list`、`sweep show`、`sweep run`、`sweep verify` 以及 `explore rank`/`promote`
输出 JSON；`sweep compare` 默认输出表格，加 `--json` 输出 JSON；`explore export`
输出所选格式，除非提供 `--output`。`sweep show` 为 CLI 兼容性接受 `--json`，但始终
输出 JSON。用法或校验错误退出码为 `2`，消息走 stderr。

### 4.1 sweep create

```bash
ecc sweep create --name NAME --param KEY=V1[,V2,...] [--param KEY=... ...] [--project DIR]
```

冻结计划。`--param` 可重复，每条形如 `KEY=VALUE[,VALUE...]` 且至少一个取值。
KEY 即已审核的 `ecc param` 键，取值在执行时原样传给 `ecc run --set`，因此适用同一
套校验（非法取值会失败在该候选的 run，而不是 create）。已存在的名字、畸形的
`--param`、空参数集都退出 `2`。

输出的计划 JSON 与之后 `sweep show` 打印的内容一致。

### 4.2 sweep list

```bash
ecc sweep list [--project DIR]
```

输出已有 sweep 名称的 JSON 数组（`["density"]` 或 `[]`）。

### 4.3 sweep show

```bash
ecc sweep show --name NAME [--project DIR]
```

打印存储的 `sweep.json`（缩进、按 key 排序）。未知名字退出 `2`。

### 4.4 sweep run

```bash
ecc sweep run --name NAME [--max-candidates N] [--project DIR]
```

执行计划（见 §6）并打印记录的 `results.json`。`--max-candidates N`（N ≥ 1）把
执行限制为计划顺序的前 N 个候选——适合对大网格先做一轮冒烟。命令可续跑：只要候选
已有 `passed`、`blocked`、`failed` 或 `unknown` 状态的结果记录且 workspace 目录
存在，就直接复用记录，不重跑 flow，也不重新采集证据；中断的 `run` 从停止处继续。

### 4.5 sweep compare

```bash
ecc sweep compare --name NAME [--json] [--project DIR]
```

默认每个候选一行，按 §8 的排序规则输出：

```
candidate | flow | steps | checklist | violations | qor | exit | parameters
----------|------|-------|-----------|-------------|-----|------|-----------
```

- `flow` 是记录的总体状态（`passed / blocked / failed / unknown`）；
- `steps` 与 `checklist` 用分号连接各步骤的 `name=status`（未记录任何步骤时显示
  `-`）；
- `violations` 与 `qor` 是采集到的证据值（缺失时为 `unknown`）；
- `exit` 是该候选 `ecc run` 的退出码；
- `parameters` 是逗号连接的 `KEY=VALUE` 列表。

`--json` 以 JSON 数组输出同一矩阵，行对象的键为 `candidate`、`parameters`、
`flow`、`steps`、`checklist`、`violations`、`qor`、`exit_code`。结果为空时只打印
表头（退出码 0）。

### 4.6 explore rank

```bash
ecc explore rank --name NAME [--project DIR]
```

以 JSON 输出记录的结果行，按 §8 规则排序（passed 优先，QoR 降序）。它是
`sweep compare` 的机器可读对应物，不做任何重新评估：直接使用记录的状态与分数。

### 4.7 explore export

```bash
ecc explore export --name NAME [--format json|csv|markdown] [--output PATH] [--project DIR]
```

导出与 `sweep compare` 相同的排序矩阵。默认格式为 `json`；`csv` 与 `markdown`
使用 §4.5 所示的固定列。未提供 `--output` 时把格式化内容写到 stdout；提供
`--output` 时把内容写入该文件，并在 stdout 输出一行 JSON 状态，包含 `status`、
`format` 和解析后的输出路径。不支持的格式属于用法错误（退出码 `2`）。

### 4.8 explore promote：候选模式

```bash
ecc explore promote --name NAME --candidate CANDIDATE_ID [--project DIR]
```

写入 `winner.json` —— `{"schema_version": 1, "candidate": "<id>", "selected_at": <unix
时间>}` —— 前置校验候选存在**且**记录状态为 `passed`。其他情况（未知 id、尚未
运行、failed/blocked）退出 `2` 且不写任何内容。promote 只是记录不是动作：把获胜
参数应用到真实项目是显式的后续操作（`ecc param set` / `ecc run --set`），promote
不会改动项目 manifest 或 baseline workspace。

候选模式只检查 `results.json` 中该候选是否有匹配记录、且记录状态是否为
`passed`。它不会重新读取当前 flow、checklist、signoff 报告、metric 证据或
engineering snapshot，因此旧的 passed 缓存仍可能被 promote。

### 4.9 explore promote：Pareto 模式

```bash
ecc explore promote --name NAME --pareto \
  --objective ID:UNIT:minimize|maximize [--objective ...] \
  [--candidate CANDIDATE_ID | --weights W1[,W2,...]] [--project DIR]
```

Pareto 模式接受 1–3 个互不相同的目标。每个 `ID` 必须属于 ECC metric registry（或为
`qor_score`），且 unit 和 direction 必须与 registry 一致。校验目标与选择参数后，命令
会在返回空前沿退出之前写入 `pareto.json`。命令不会信任缓存状态，而是按当前提交的证据
重新校验每个候选：

- candidate workspace 必须与 sweep 绑定一致，并位于项目目录内；
- 当前提交参数必须等于冻结的候选参数；
- 当前完整 flow、checklist 和 signoff 证据必须为 `passed`，checker 违例数为 0；
- 每个目标都必须从经核验的 metric 证据中得到唯一且无歧义的当前值，检查期间
  engineering snapshot 不得发生变化。

任一项不满足的候选会连同原因列入 `excluded`。报告包含 `front`、`ranking`、
`objectives`、`excluded`、`safe_to_apply: false` 和选择记录。

不提供 `--candidate` 或 `--weights` 时，Pareto 模式只导出前沿：写入 `pareto.json`，
不写 `winner.json`，前沿非空时退出 `0`。显式 `--candidate` 必须是已核验前沿的成员；
`--weights` 要求每个目标对应一个有限非负权重且权重和为正，并按最低归一化加权分数
选择，分数相同时按 candidate ID 确定性决胜。任一种有效显式选择都会同时写入
`winner.json` 和 `pareto.json`。若未做显式选择且核验后的前沿为空，命令仍写入
`pareto.json`，并退出 `7`；无效的显式候选或权重会在写文件前退出 `2`。

## 5. 计划契约（`sweep.json`）

| 字段 | 类型 | 含义 |
|---|---|---|
| `schema_version` | int | 当前为 `1` |
| `name` | str | sweep 名（即 `experiments/<name>/` 目录） |
| `parameters` | object | `KEY` → 有序取值列表，与 `create` 输入一致 |
| `candidates` | array | 每个网格点一条 `{id, parameters}` |
| `created_at` | int | Unix 创建时间 |
| `plan_fingerprint` | str | 对除 `created_at` 外全部字段的规范 JSON 计算 SHA-256 |

候选 id 为 `candidate_0001`…，按网格顺序编号：参数 key 排序后，最后一个 key 的
取值变化最快（上例中 `cts.max_fanout=16 + place.target_density=0.60` 即
`candidate_0001`）。

`plan_fingerprint` 可在排除创建时间后比较两个计划是否一致：参数相同且候选顺序
相同 ⇒ 指纹相同。

## 6. 执行模型

对每个候选（按计划顺序，受 `--max-candidates` 约束）：

1. 若该候选的项目副本尚不存在，把项目复制到
   `experiments/<name>/candidates/<id>/project/`，排除 `experiments/`、`.git`、
   `*.lock` 和 `ws_*`。复制出的 `project.json` 被改写：`root_path` 指向副本，
   `workspaces` / `runtime_processes` 清空——副本以干净的单 workspace 项目启动。
2. 若该候选已有四种状态之一的结果记录且 workspace 目录存在，直接复用记录，不运行。
3. 否则以子进程运行候选：
   `ecc run --project <副本> --workspace <副本>/<candidate-id> --set KEY=VALUE …`，
   使用冻结的候选参数。
4. 采集终态证据并追加到 `results.json`（§7）。

候选之间不共享状态：每个网格点有独立的项目副本和 workspace，一个候选失败或
blocked 不会污染其他候选。删除候选目录即删除其隔离副本；删除整个
`experiments/<name>/` 目录即删除该 sweep。

## 7. 结果契约（`results.json`）

每个已执行候选一行：

| 字段 | 含义 |
|---|---|
| `id` / `workspace` | 候选 id 及其在副本内的 workspace 路径 |
| `parameters` | 冻结的候选参数映射 |
| `exit_code` | 该候选 `ecc run` 的退出码 |
| `status` | `passed / blocked / failed / unknown`（推导见下） |
| `step_statuses` | 来自持久化 flow 的 `[{name, status, checklist}]`，缺失时回落 `ecc status --json` |
| `qor_score` | workspace 报告 JSON 文件中第一个出现的 `qor_score` / `score` / `ppa_score`，否则 `null` |
| `violation_count` | 来自 `ecc signoff check --json`（`violation_count` / `violations` / `error_count`），否则 `unknown` |
| `signoff_exit_code` / `workspace_status_exit_code` | 两个证据探测的退出码 |

状态推导按优先级：

1. **blocked** —— 任一步骤状态或步骤 checklist 状态为 `blocked`；
2. **failed** —— run 退出码非 0，或 signoff 探测退出码既非 `0` 也非 `7`
   （`7` = 必需门禁无法评级，是证据而非失败）；
3. **passed** —— 记录到了步骤（或 `ecc status` 退出 0），且不满足上述两条；
4. **unknown** —— 完全没有步骤证据。

两个探测均为只读；`run` 绝不为了补齐证据而重跑 EDA。QoR 与违例值取 workspace
中已有内容。特别地，signoff 退出码 `7` 本身不会让候选变成非 passed；记录状态仍由
上面的步骤/状态规则决定。

## 8. 排序规则

`sweep compare` 与 `explore rank` 使用相同排序：

1. 按状态类别：`passed` = `success` → 0，`blocked` → 1，`failed` → 2，
   `unknown` → 3；
2. 同一类内按 `qor_score` 降序；缺失分数排在最后。

并列保持记录顺序。排序只是对已记录证据的视图，不是签核决策（分数含义见
[QoR 参考手册](ecc-qor-ref.cn.md)）。

## 9. 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功（包括 compare/rank 结果为空——未知或未运行的 sweep 名按空结果比较） |
| 2 | 用法或校验失败：未知 sweep 名、候选模式中的未知或非 passed 候选、无效的目标/权重/导出设置、重名（`create`）、畸形 `--param` |
| 6 | `sweep verify` 发现完整性错误 |
| 7 | Pareto 模式没有得到任何经核验的前沿成员 |

sweep 命令没有 `--plain`；JSON 即机器可读形式。结果共享所需的证据打包与完整性
校验属于另一命令组——见 [CLI 用户指南 §11.5](ecc-user-guide.cn.md) 的
`ecc reproducible`。

`sweep verify` 只检查存储的 plan fingerprint、结果成员是否唯一且属于计划、候选参数
是否完全一致、workspace 目录是否存在以及是否有缺失结果。它不重新校验步骤状态、QoR
数值、signoff、checklist 内容或结果字段类型。需要按当前完整流程证据重新校验时，请
使用 Pareto promote。

## 10. 与其他命令的关系

- `ecc param` / `ecc config` —— `--param` 扫掠的参数词汇表；见
  [配置参考](ecc-config-ref.cn.md)。
- `ecc report project` —— 已声明 workspace 的已存 QoR 矩阵；sweep 候选的
  workspace 位于隔离副本中，不属于项目 manifest。
- `ecc reproducible export` —— 把某个 workspace（含 sweep 获胜者）的证据打包为
  可校验的 tar.gz。
