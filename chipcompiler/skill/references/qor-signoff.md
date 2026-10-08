# QoR、签核与证据

适用：分析结果、候选比较、签核与导出。调优决策见 [优化指南](optimization.md)。

## 1. 先刷新再判断

```bash
ecc status --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc report step --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc signoff inspect --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc report checklist --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc report summary --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc report qor --project "$PROJECT" --workspace "$WORKSPACE" --plain
```

report step 只读不刷新；section 可重复 feature/analysis/checklist。feature 是运行事实/数据库统计，analysis 是指标与 quality gate，checklist 是签核要求。缺 section 写 unavailable，不当 0。

summary/checklist/qor 写文本报告，允许未完成 flow；written 表示报告生成，不表示芯片通过。inspect/export 刷新已完成步骤分析；inspect blocked 仍可 rc=0。严格只读任务不执行这组写/刷新操作。

QoR 报告 `home/qor_report.json` 为 schema_version 3、scoring_engine qor-v3；Studio 消费同一评分，不自行复算。只读深入检查时核对 flow_steps 快照与当前状态，失效/重跑后旧文件不可用；先用 report qor 重采，产物缺失则重跑真正产生证据的步骤，不造报告。

## 2. 七条 QoR 可行性门禁

| 门禁 | 当前判定 |
|---|---|
| GATE_DRC | 最终 drc_count == 0 |
| GATE_LVS | 最终 lvs_count == 0 |
| GATE_SETUP_SLACK | 最差 setup signed WS >= 0 ns |
| GATE_HOLD_SLACK | 最差 hold signed WS >= 0 ns |
| GATE_SETUP_NVP | setup violation_count == 0 |
| GATE_HOLD_NVP | hold violation_count == 0 |
| GATE_HARDEN_ARTIFACTS | GDS/LEF/LIB missing_count == 0 |

任意 failed → PHYSICAL_FAIL → 总分 0/FAIL；步骤未成功 → NOT_VERIFIED；成功但证据缺失/损坏 → UNKNOWN；后两者总分 null/NOT_RATED。不能把 UNKNOWN 当 FAIL，也不能把未验证当 PASS。

RCX 不单独列为七门之一，但 SPEF 缺失会影响证据和实际交付要求。LEC 不是七门之一，但可在 checklist/export 阻断；七门 PASS 不等于所有签核要求满足。中间 routing DR 违规/placement overflow 是诊断特征，不直接等于最终 PHYSICAL_FAIL。

### signed WS 与传统 WNS

ECC 的 sta_setup_wns/sta_hold_wns 虽含 wns 字样，携带有符号最差裕量 WS。传统 WNS=min(0,WS)。报告中同时保留正裕量、负 WNS、TNS、NVP、worst_corner；不能把 +2 ns 写成“有 2 ns 违例”，也不能将传统 WNS=0 解释为所有候选有相同裕量。

最终 STA 查看所有请求 Liberty×RC×温度组合，而非只看 typical。setup 四类报告 in2out/in2reg/reg2out/reg2reg 需完整；hold 文件在当前 export 契约中可能可选，但缺 hold 会使 QoR 门禁未知/证据降级。明确区分“当前包可导出”和“全部 setup/hold 已验证”。

## 3. 五维评分的正确用途

以下阈值是当前工程启发式，不是可任意改的用户参数或物理定律。用引擎输出判断，不复制评分程序替代 ECC。

| 维度 | 含义/阈值 | 防误读 |
|---|---|---|
| Timing Q_T | 周期 T=1000/f；guardband 0.05T，失败尺度 0.20T；WS=0 得 50，正裕量至 guardband 得 100 | WS>0.20T 为 OPPORTUNITY，不自动授权降低规格/缩驱动 |
| Interconnect Q_I | 相对 HPWL 的膨胀成本，<=1.25 理想，>=1.75 成本项归 0，再乘拥塞惩罚 | 不是绝对 wirelength；网络人口不兼容不能比较 place→route 比值 |
| Area Q_A | 实际布局 core utilization；0.45–0.70 满分，低于 0.45 或高于 0.70 降分，至 0.85 为 0 | 得分不等于绝对 die/core 面积最小，规划密度不是此指标 |
| Power Q_P | 显式功耗预算下 clamp((budget-total)/budget,0,1)×100 | 无预算为 null；功耗较低不自动等于 Q_P 可评分 |
| Robustness Q_R | CTS buffer-depth imbalance 与多 corner slack spread/周期，缺项重归一 | 风险代理，不等于 hold、IR/EM 或硅后鲁棒性证明 |

Timing 状态：负 WS FAIL，0–0.05T WATCH，0.05T–0.20T PASS，更高 OPPORTUNITY。其他维度通常 >=80 PASS、60–80 WATCH、<60 FAIL。

互连：I_place=GRWL/HPWL，I_route=RWL/GRWL，I_total=RWL/HPWL。分母 0/缺失时 UNKNOWN，禁止补 epsilon。CTS 插 buffers 或数量未知且无 net-level mapping 时 place→route INCOMPATIBLE；当前 Q_I 降级按同阶段 I_place 评分，不拼接出伪比值。

拥塞 severity=max(RUDY_max/1, EGR_max/20, EGR_total/100)，>=1 可把 Q_I 压到 0；这是策略惩罚，不表示最终 DRC 必然失败。工具版本换了 proxy 来源/人口时不可混比。

## 4. 总分、profile 与证据

只有 feasibility PASS 且有可评估维度才给加权总分；null 维度从分母排除。GREEN>=90、YELLOW>=75、ORANGE>=60、RED<60；FAIL/NOT_RATED 是另一层状态。

| profile | Timing | Interconnect | Area | Power | Robustness |
|---|---|---|---|---|---|
| balanced | .30 | .25 | .15 | .15 | .15 |
| timing_critical | .45 | .20 | .10 | .10 | .15 |
| low_power | .20 | .15 | .15 | .35 | .15 |
| area_optimized | .20 | .25 | .35 | .10 | .10 |

当前文档的 qor_profile/qor_power_budget_w 尚无审核 CLI 参数；不手改 home/params.toml。可以解释已有报告 profile 或以用户预算在非受管台账计算独立功耗比例，但标注“外部比较，非 ECC QoR 配置”。不声称已开启 low_power；具体缺口见 [来源说明](installation-sources.md)。

证据指数 I_E=100×integrity×coverage×consistency；HIGH>=90、MODERATE>=70、LIMITED>=50，否则 INSUFFICIENT。检查解析/selector 健康、STA 与 RCX 期望/缺失 corner、同群体关系 RWL>=HPWL、WS>=0 与 NVP=0 一致性、via>0 时 wirelength>0。域不适用不制造满分；只有 setup 无 hold 时 HIGH 可能降 MODERATE。

diagnoses 是观测分类，interventions 是需验证的假设。优先 Tier 1 硬门、Tier 2 质量瓶颈、Tier 3 机会。文案的 parameter_knob 不等于 CLI 实现，如 route.dr_search_depth 在当前 route schema 未暴露，禁止猜名直接设置。

## 5. 原始 PPA 与单位

- area：最终 die_area/core_area 通常 µm²；mm²=µm²/1e6。synthesis_cell_area 是 cell-area 代理，不能替代 core/die footprint。
- timing：固定相同约束、corner、路径范围和单位 ns；同时比较 WS/TNS/NVP。估算 Fmax 与用户目标频率区别报告，不用某个 Fmax 代替多时钟验收。
- power：powerAnalysis iPW 优先，来源 power_summary.json/power.rpt；缺时可回退 post-synthesis estimate。报告 source_kind=signoff/synthesis、活动假设与 corner，不能把综合估计称提取后功耗。µW→W 除 1e6；预算单位 W。
- route：HPWL/GRWL/RWL/vias 带阶段、网络人口兼容性和工具版本。clock insertion 后线长增长不能直接归咎于布局退化。
- cost：完整 flow runtime、峰值内存与阶段成本；线程/设备不同须标注，不能只比 run 命令 wall time。

## 6. signoff inspect/export

检查七组 initial/config/harden/final_design/sta/spef/reports 和 risk 细节；不是 QoR 七门的同一分组。attention 常来自无宏空位置文件、成功 LEC 不存在的 failed dump 等可选项，不能为消除告警制造文件。

阻断可能是必需文件缺失、最终 DRC/LVS、setup gate、LEC unproven、分析刷新失败或产物不一致。每个 blocker 写出 requirement、证据路径和修复边界。不能编辑 checklist/分析强制通过。

```bash
ecc signoff inspect --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc signoff export --project "$PROJECT" --workspace "$WORKSPACE" -o /absolute/deliverables/chip-signoff.tar.gz --plain
```

export 自带门禁并原子落盘；signoff_incomplete 不应产生残档。先确认导出目录/文件冲突和用户授权，不覆盖已有交付。include-debug 只在用户需要且已考虑体积/敏感源码时用。

成功后核对返回路径和文件、可只读 `tar -tzf` 查看清单而不解包到未知目录。包包含 manifest/summary、initial/config/harden、synthesis、final/design/timing/reports；文件数不是固定验收条件。记录包校验和、workspace 和工具/输入版本。只说 ECC 当前检查下可交付，不说已通过代工厂流片认证。
