# 收敛、PPA 优化与批量实验

适用：用户要求跑通、达到签核或优化。先读 [QoR/签核](qor-signoff.md) 和相关 [参数](config-floorplan.md)，不把低分当作自动搜索授权。

## 1. 定义目标和预算

记录 design/top/RTL/SDC/PDK/工具版本、固定验收 corner、目标频率、宏、功耗活动假设与面积/外形限制。区别：

- 收敛：硬门/交付通过，在既定规格下获得完整证据。
- 优化：在可行候选中改善用户指定原始 PPA 或 QoR。
- 规格探索：频率、RTL 架构、corner、约束变更，是单独实验，不与固定规格候选混比。

确认主目标和硬约束：例如最小 die_area 且所有 setup/hold >=0；最小 signoff total power 且面积不增超过容差；最大裕量且面积有上限。用户只说 PPA 且权重决定 winner 时询问；不能默认固定字典序。

预算包括候选数、总时间、单次 timeout、CPU/内存/磁盘、并发/许可证和允许的规格/RTL改动。没有具体预算时先说明保守有限试验计划，依据一次 baseline 成本设上限；不运行无界 grid search，也不把未给预算当成可无限消耗机器。

台账写在非受管 experiments/ 等用户授权位置。字段至少：ID、workspace/path、输入/约束/PDK/工具版本、preset/range、创建 override、本地修改、环境/seed/thread、假设、from_step、实际状态、WS/TNS/NVP/corners、DRC/LVS/LEC/Harden、area/utilization、power/source、QoR/gates/evidence、runtime/peak memory、结论/停止原因。

## 2. 建立可信 baseline

1. 保留用户现有结果；可用已知 baseline，但先检查证据新鲜度和配置。
2. 在未占用 workspace 完成请求范围并采集 status、step、inspect、checklist、summary、qor。
3. 验证所有主目标指标真的存在、单位/阶段一致。无 power 不能宣称三目标 PPA 均优化。
4. baseline 若 BLOCKED，先根因收敛，不能拿不可行高分作为 winner。
5. 记录硬门与所有告警，确定可比性和实际成本后再选择最少的试验。

`syn_sta` 只综合，可筛 RTL/综合面积和估计功耗，不筛最终多 corner STA/DRC。partial placement/routing 可观察拥塞，但入围/最终候选须相同完整 flow；不能把早期 proxy 改善直接汇报为最终 PPA 改善。

## 3. 按根因选旋钮

下表是干预假设，不是因果保证；每项先 param show 确认支持和 invalidation 边界。一次先改一个根因组，再用完整下游验证副作用。

| 证据/症状 | 先核对 | 可试方向 | 必查副作用 |
|---|---|---|---|
| 综合面积异常/大量 latch/blackbox | top、defines、位宽、资源模型、映射库 | 修复授权 RTL/输入，或受支持综合策略独立实验 | 功能/LEC，最终 footprint 和 timing |
| die/core 太大、实际利用率低 | die_util/die_size、margin、tap/PDN/宏占位 | 小步提高 core_util 或调整 aspect；固定外形按规则改尺寸 | legal placement、pin access、routing DRC、setup/hold |
| floorplan 容量不足/宏通道拥挤 | 标准单元+宏有效面积、halo、PDN/IO/rows | 降 core_util、改 aspect/margin、合法宏布局 | 面积、长线、时序；不削弱 tap/PDN 规则 |
| placement overflow 高/不收敛 | 密度与容量关系、宏堵塞、迭代/log、网格 | target_density/overflow、padding、routability、必要算法参数 | HPWL/GRWL、最终 routing 与成本 |
| placement congestion 热点 | EGR/RUDY/GPUGR 来源、macro/pin density、层范围 | 改布局/宏通道、密度、routability/inflation | 面积/线长、CPU/GPU能力、DRC/STA |
| CTS skew/深度不平衡/hold 风险 | clock/SDC、buffers、sink load、MIN 库 | 支持的 skew/fanout/transition/buffer/layer | setup 与 hold、clock power/area、完整角落 |
| setup WS<0 | worst corner/路径类型、SDC/period、网表/SPEF、clock/data 路径 | Sizer 是否成功；布局线长/拥塞；CTS 或合法层范围 | hold、面积、功耗、LEC；不得降低规格 |
| hold WS<0 | fast/MIN corner、路径和 uncertainty，Sizer hold pass | CTS/结构平衡、有效 hold 修复流程、布局/路由假设 | setup 与所有 corner；不靠降低频率掩盖 hold |
| routing 不收敛/局部 DRC | 错误类型、阻塞、pin access、层/PDN资源 | 有效 layer span，或回到布局增加空间/改善通道 | 线长/vias/RC/power、最终 DRC/LVS |
| 最终 DRC 非零 | rule 分类、位置/层、宏边界/filler/电源 | 依据规则改上游布局、halo、filler 或合法层 | 不能跳检查、改计数；LVS/STA/LEC |
| LVS 非零 | DEF/网表配对、实例/电源脚、filler/tap、宏模型 | 修正确认的输入或上游连接错误 | 不靠密度随机搜索“碰运气” |
| LEC unproven | 两侧网表/hash、模型/Liberty、顶层、证明报告 | 修复逻辑变化/模型/工具兼容；保留失败证据 | 不能以物理 clean 替代等价性 |
| RCX/STA corner 缺失 | 库、温度/RC命名、SPEF完整性、解析错误 | 修复数据/工具，再 RCX→STA→power/Harden | 不删 signoff corners、不能用典型值补最差值 |
| 功耗超预算 | 来源/单位/活动、dynamic/leakage、clock 占比 | 授权综合策略、受支持 CTS/布局优化；RTL架构另开任务 | 所有时序/面积/逻辑硬约束 |
| 大裕量 OPPORTUNITY | 真实路径覆盖、规格/uncertainty 和 corner | 若用户目标允许，探索更低驱动/面积的受支持流程 | 没有公开 Sizer sizing 旋钮时报告限制，不手改脚本 |

### 密度和 padding 不能互换

floorplan.core_util 决定 die_util 模式的尺寸；place.target_density 决定给定区域内布局行为；实际 core_utilization 是插入 CTS/tap/filler 等之后的测量，三者不是同一值。降低 target_density 不必然扩大 die，减小 cell_padding_x 可能减拥挤也可能增加 pin-access DRC。没有全设计适用的 0.55/0.65 或固定 seed 配方。

### 诊断到证据

每轮记录“观测→假设→改动→重跑范围→验收”。使用 report step 检查阶段变化，再用最终 gates 确认。改善 overflow、RUDY 或 HPWL 只是支持假设，不等于证明 setup、hold 或 DRC 已改善。

## 4. 候选管理与搜索

独立候选推荐 fresh workspace：

```bash
ecc run --project "$PROJECT" --workspace cand-density-001 --preset rtl2gds --set place.target_density=0.55 --plain
```

前提是该名称未占用、值经 schema 审查、假设符合 baseline。project 参数保持冻结；改变它会污染随后所有 fresh。seed/设备/线程固定作为控制变量，只有显式研究随机/资源因素时才改变。

对同一候选局部迭代可以 workspace param，但用台账区分每个版本，改之前保存原始指标/日志路径。不得把修改过的 workspace 仍称原候选。CLI 没有 clone/promote 时不要复制受管目录拼实验；需要复用中间阶段，用匹配入口与新 range。

先粗粒度识别可行区，再小步缩范围；单变量或明确同根因小组优先于同时改十个参数。实验失效/出现相同根因时停止重复，缺能力/资源时报告，不升级成源码修改。

允许停止：预算耗尽、连续试验无有效改善、可靠可行域已找到且满足目标、剩余瓶颈不在公开 CLI 能力内、数据不可比、工具/资源外部阻塞。停止时区分最佳已验证、未完成、不可行和需额外授权候选，不称“全局最优”。

## 5. 排名和 winner

1. 按用户验收要求排除 hard gate 失败、证据不完整或约束改变的候选。可导出但 hold 未验证时，不入“全部时序已签核”的 winner 集。
2. 固定输入/PDK/约束/corners/工具/测量阶段，比较原始面积、WS/TNS/NVP、power/source 及资源成本。
3. 按目标做 Pareto 淘汰；对非支配集合用用户权重/字典序与测量容差选择。目标相等时优先改动少、可复现的方案。
4. 同时解释 QoR dimensions/gates/evidence；总分不覆盖原始 PPA，profile 不同不能裸比总分。
5. 计算改善百分比时标出 baseline、分子分母和单位。接近 0/缺失时不给无意义百分比；负 slack 不能靠常规“百分比更优”隐去仍失败。

## 6. 提升与 fresh 完整复验

收集 winner 的创建 set、本地 overrides、project snapshot、macro placements、环境变量和输入变化。`param diff --workspace` 只显示本地 baseline 差异，不是所有胜出参数；`config` 无 STEP 仍是 project 配置，不能拿它独自提升。

```bash
ecc param diff --project "$PROJECT" --workspace "$WINNER" --plain
ecc param show place.target_density --project "$PROJECT" --workspace "$WINNER" --plain
ecc macro show --project "$PROJECT" --workspace "$WINNER" --plain
```

先取得修改 project 默认的授权。只对实际胜出且 CLI 可设置项逐项 project param/macro 设置，保存旧值以便回退。参数例子：

```bash
ecc param set place.target_density 0.55 --project "$PROJECT" --plain
ecc check --project "$PROJECT" --plain
ecc run --project "$PROJECT" --workspace final-best-001 --preset rtl2gds --plain
```

最后名称未占用，输入/PDK/SDC/环境与 winner 一致；不是覆写 winner。复验完整 flow、inspect/checklist/summary/qor、所有主目标与门禁。超容差回退/诊断，不拿局部重跑结果作最终复验。未授权提升 project 时，可用完整 winner 参数显式 set 建 fresh final，报告“仅候选复验，未更新项目默认”。

无原子 promote 命令时逐项操作可能中途失败，报告完成/未完成项并通过 CLI 恢复旧值，不手工复制 home/params.toml/config。只有 fresh final 符合目标和交付范围才导出。

## 7. 多 design 批处理

每个 design 独立 project/workspace/台账/预算，不共享可变配置。预检清单标 top/clock/PDK/规模和输入是否就绪；默认串行。并发限制按实际许可证、RAM/CPU/磁盘，不能把示例 70% 内存阈值当 ECC 固有规则。

每个完成/失败立即更新结果。停止时只管理本任务进程，并确认子进程退出。汇总 design 总数、ECC可导出/QoR门禁PASS/BLOCKED/flow failed/未跑，附根因分组与最好已验证候选；不要把“命令返回 0”计为签核成功。
