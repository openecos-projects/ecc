# ECC CLI：比较运行快照

## 范围与用法

```bash
ecc compare run --baseline before.json --current after.json
ecc compare run --baseline before.json --current after.json --plain
ecc compare run --baseline before.json --current after.json --json
```

两参数均为必需的、未压缩的 Engineering Snapshot JSON 文件路径，支持相对路径和
`~`。不接受 run ID、workspace 名称或目录，不需要 `--project` / `--workspace`。
现有 `ecc run` 执行入口不变。

当前 snapshot 是 workspace 的已提交投影，不是历史运行数据库。运行前后必须分别
保存一份快照；CLI 不自动记录历史，不重建旧结果，也不读取 artifact 内容。

```bash
mkdir -p comparisons
cp /path/to/workspace/home/engineering-snapshot.json comparisons/before.json
ecc param set place.target_density 0.30 --workspace /path/to/workspace
ecc run --workspace /path/to/workspace --resume
cp /path/to/workspace/home/engineering-snapshot.json comparisons/after.json
ecc compare run --baseline comparisons/before.json --current comparisons/after.json --json
```

保存 before 时先确保 workspace 已停止运行；after 建议在流程完成后保存。仅重跑单步
可能使后续步骤失效，从而缺少最终 QoR；这时返回 unknown/unavailable 是正确结果。

## JSON 契约

复用 ECC 公共输出契约，顶层是记录数组，首条记录为：

```json
[
  {
    "record": "run_comparison",
    "status": "success",
    "schema_version": 1,
    "baseline": {
      "workspace_id": "workspace-gcd",
      "workspace_revision": 1,
      "schema_version": 4,
      "source": "before.json"
    },
    "current": {
      "workspace_id": "workspace-gcd",
      "workspace_revision": 2,
      "schema_version": 4,
      "source": "after.json"
    },
    "summary": {
      "overall": "improved",
      "scope": "numeric_metrics_and_qor_score_only",
      "counts": {"improved": 1, "regressed": 0, "unchanged": 0, "unknown": 0}
    }
  }
]
```

示例省略了以下完整结果字段：

| 字段 | 含义 |
| --- | --- |
| `compatibility` | 保存的上下文元数据是否可比，以及不可比原因 |
| `steps` | 以 name/tool 对齐的前后 flow 记录，包含状态和已保存的 runtime 等字段 |
| `metrics` | 以 id/scope/corner/analysis_group 对齐，含前后值、单位、delta、trend、reasons |
| `qor` | 已保存的 score、各维度数值比较，以及 feasibility/evidence/power 等字段变更 |
| `parameter_changes` | 顶层参数的 added/removed/changed；保留 null 与缺失的区别 |
| `configuration_changes` | 已保存的 workspaceSpec/workspaceBindings 变更，不代表完整版本锁 |
| `signoff` / `checklist` | 前后已保存的原始投影与 change，不实时生成签核报告 |
| `artifacts` | 按相对 reference 对齐的索引变更，忽略路径身份 artifactId 的差异 |
| `warnings` | 内容未验证、总体数值趋势不等于签核结论等限制 |

文本默认显示摘要和 metric 趋势；`--json` 提供完整结构。`--plain` 使用公共 key=value
格式，复杂字段遵循既有 plain 表示；自动化解析嵌套字段请用 `--json`。

## 比较与判定规则

- delta = current - baseline；缺失、非数值或布尔值不补零，delta 为 null。
- 单位优先读记录的 unit；现有记录未声明 unit 时复用 QoR metric registry 的单位。
  单位缺失、不一致或偏离规范单位时不计算 delta，不自动换算。
- 仅 registry 已定义方向的指标可判断 improved/regressed。未知指标、trend_only 和
  target_range 只提供可用的 delta，trend 为 unknown，不虚构阈值。
- flow 定义/顺序、design/inputs/PDK 元数据、约束参数或 corner context 等变化会
  禁用相关趋势判断。不同 workspace 可以展示差异，但首版不做跨 workspace 优劣判断。
- 优化参数变更会被列出，不会仅因 target_density 改变而禁用所有指标比较。
- QoR score 只有相同 schema/engine/profile 且两侧 available 才可判断；维度还要求
  featureIds 一致、不是 UNKNOWN。QoR 没有保存时明确 unavailable。
- summary 只汇总 metric 与 QoR score 趋势，不包含 flow/checklist/signoff 的质量判断。
  有未知项或没有可评估项时为 unknown；有改善和退化时为 mixed，否则为
  improved/regressed/unchanged。各项 counts 仍保留已识别的部分趋势。两侧都没有数值
  score 时，该项不参与汇总，不可用状态单独保留在 qor；summary 不代表完整 QoR。
- artifactId 是路径身份，不是内容 hash。所有 artifact 的 content_comparison 都是
  unknown；索引 unchanged 绝不意味着文件内容相同，也不重新读取当前文件伪造历史 hash。
- 保存的元数据一致不证明 RTL/PDK/SDC 内容一致；不作为 tapeout 判定或阈值 gate。

## 校验与错误矩阵

支持当前 runtime 已支持的 snapshot schema，不迁移输入。单文件上限使用现有
`ENGINEERING_SNAPSHOT_MAX_BYTES`（16 MiB）。保存文件读取复用 snapshot schema 和路径
校验，但不使用文件旁边的 workspace command metadata 重新绑定历史身份。

| 情况 | 结果 | 退出码 |
| --- | --- | --- |
| 完成比较，包括 regressed/mixed/unknown | `run_comparison`，status=success | 0 |
| 缺少参数或同时使用 --plain/--json | 公共 CLI 参数错误 | 2 |
| 缺失、不可读、非法 JSON、超限、压缩输入、非有限数或非法 schema | `snapshot_read_failed`，含 role/path/reason | 1 |
| 非法 metric/step 投影、重复比较键 | `snapshot_compare_failed`，含 reason | 1 |

同文件比较合法。有有效 metric 时得到 unchanged；完全无数据时不能声称质量未变，
summary 为 unknown。对两侧文件不加锁，不支持可靠比较正在写入的文件。

## 开发接口与测试点

```python
read_engineering_snapshot_file(path: str | Path) -> dict[str, Any]
compare_snapshots(baseline: dict, current: dict) -> dict
```

文件读取归 engine/snapshot 所有，纯比较归 engine/snapshot_compare 所有。CLI 使用
独立 typed input、command handler、shared create_app/execute_command 和渲染注册。
不加载 workspace、不执行 EngineFlow、不生成报告、不创建目录或锁。

测试覆盖：三种输出、输入大小/编码/schema/路径、重复键、正负数/零/缺失/布尔/非有限数、
单位与分析上下文、QoR profile、同文件、回归退出码、artifact 身份语义和只读性。

错误：以相同 artifactId 推断 GDS 内容相同；把缺失 WNS 当 0。
正确：内容比较标 unknown；缺失值保留 null 并给出 value_unavailable。
