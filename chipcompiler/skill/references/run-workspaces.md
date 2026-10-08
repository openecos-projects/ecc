# Flow、workspace 与恢复契约

适用：创建/续跑、范围/单步、导入和刷新。工具根因见 [故障诊断](troubleshooting.md)。

## 1. preset 和步骤名

| preset | 当前语义 | 用途 |
|---|---|---|
| `rtl2gds` | 18 个规范步骤位置，ledger 按 skip 策略删减 | 完整物理设计和最终交付 |
| `syn_sta` | 只有 Synthesis，不执行最终 STA | 综合/早期估计，不能称 routed signoff |
| `synthesis_lec` | 综合与 LEC，需实际启用 lec | 等价性实验，不产物理签核包 |

`run --preset` 不写回 project；长期意图用 `project set flow.preset`。默认跳过综合级 lec，不声称已验证。skip/engine 的 CLI 能力缺口见 [来源说明](installation-sources.md)。

链路采用当前 user guide/tutorial 和 flow builder；配置参考存在旧的 postRouteLec 位置/工具描述。执行以目标安装和持久化 ledger 为准。

| 展示/report token | 既有 workspace 选择器持久化名 | 核心证据 |
|---|---|---|
| synthesis | `Synthesis` | mapped/golden 网表、面积/count、综合检查 |
| lec | `lec` | proven/失败/跳过的区别 |
| pre_floorplan | `preFloorplan` | 初始 die/core/rows |
| macro_placement | `macroPlacement` | 宏位置交接与摆放 |
| post_floorplan | `postFloorplan` | IO/tap/endcap/PDN 与 DEF/网表 |
| placement | `place` | HPWL/GRWL、overflow、拥塞 |
| cts | `CTS` | buffers/depth/skew、网表/DEF |
| legalization | `legalization` | 合法性、重叠/边界 |
| timing_optimization | `Timing optimization` | Sizer setup/hold 与内部合法化 |
| routing | `route` | wirelength/vias、布线结果 |
| filler | `filler` | filler 后产物 |
| lvs | `lvs` | layout/netlist 一致性 |
| drc | `drc` | 最终规则违规数/分类 |
| postroutelec | `postRouteLec` | 物理变换后逻辑等价性 |
| rcx | `RCX` | SPEF corner 集合 |
| sta | `sta` | 多 corner setup/hold/TNS/NVP |
| poweranalysis | `powerAnalysis` | 提取后 iPW 功耗 |
| harden | `Harden` | GDS/abstract LEF/timing LIB/PNG |

空格名称引用：`--from 'Timing optimization'`。log/report step 可用展示名；既有 workspace 的 `--from/--to/--only` 用精确持久化名。仅新建范围两端成对时可用小写别名。unknown_step 按输出 available steps 修正；`Floorplan` 是共享配置，不是可执行单步。

## 2. project/workspace 分工

Project ecc.toml 保存长期意图，project.json 是工具维护的登记。Workspace 捕获输入/参数/工具配置/flow/状态/产物；project 变化不更新旧快照。project 级参数/宏用于 fresh，workspace 级修改失效相关后缀。

多个活跃 workspace 必须显式选择；只有一个也固定 ID，避免新增实验后误操作。baseline、candidate、final 不同名；原地修改 baseline 会失去对照。

### 外部路径、导入、迁移

单段名称对应 `<project>/<id>`；外部路径须为完整绝对目录，代表最后一级目录。父目录须存在，新路径通常以 basename 登记 ID。相对 a/b、`.`、`..`、受保护路径或重复 ID/path 不适用。

```bash
ecc run --project "$PROJECT" --workspace /absolute/runs/chip/candidate-001 --preset rtl2gds --plain
ecc workspace import archive-001 --path /absolute/runs/chip/archive-001 --project "$PROJECT" --plain
ecc status --project "$PROJECT" --workspace archive-001 --plain
```

import 只登记，不移动、不运行、不改导入内容；先审查结构/版本兼容。legacy runs/ 用 `ecc migrate --project "$PROJECT" --plain` 看计划，明确批准后执行，不默认 --yes。不手改 manifest 归档。

## 3. 运行选择器矩阵

以下片段都追加 `--project "$PROJECT" --plain`，名称换成真实值。

| 目标 | 片段 | 行为 |
|---|---|---|
| 新完整实验 | `run --workspace fresh --preset rtl2gds` | 捕获输入、预检、登记、运行 |
| 新候选 | `run --workspace fresh --set KEY=VALUE` | 创建时覆盖，记录 provenance |
| 恢复 | `run --workspace existing --resume` | 从首个非成功步继续 |
| 单步 | `run --workspace existing --only place` | 已成功时 no-op |
| 强制单步 | `run --workspace existing --only place --force` | 替换该步并失效下游 |
| 后缀 | `run --workspace existing --from CTS` | 从 CTS 向后重跑 |
| 范围 | `run --workspace existing --from CTS --to route` | 两端包含，下游仍待恢复 |
| 新范围 | `run --workspace fresh --from placement --to routing` | 两端配对，入口输入就绪 |
| 授权重建运行 | `run --workspace existing --overwrite` | 丢弃 workspace 后运行 |
| 授权重建不运行 | `workspace refresh existing` | 替换输入/配置/状态/产物 |

互斥/限制：resume、only、范围不能混用；to 不能单用；force 只属于 only；新范围不能搭配 preset/resume/only/force/overwrite；已有 workspace 不接受 set，改用 workspace param 或新候选。

裸 run 对全部成功且匹配的 flow 通常 no-op，失败/中断恢复。但 reconcile 可能将短前缀扩展到当前 project 目标，分叉报 flow_mismatch。因此 `syn_sta` workspace 再裸跑不保证只综合，不能用 preset 安全替换已有实验。检查 no_op/executed_steps 和实际 ledger。

重跑替换被选步骤输出并使下游待执行；残存下游文件是陈旧证据。局部范围后 partial 不等于完整恢复。签核结论须恢复后缀并重新采证。

## 4. 新范围入口需求

| 起点 | 必需声明 |
|---|---|
| Synthesis | design.rtl |
| lec / postRouteLec | design.netlist + design.golden_netlist |
| preFloorplan | design.netlist |
| macroPlacement / postFloorplan / place / CTS / legalization / Timing optimization / route / filler / lvs / drc / RCX / Harden | design.def + design.netlist |
| sta | design.def + design.netlist + design.spef |

SDC 若声明须有效；默认生成约束未必符合原输入。powerAnalysis 独立入口需求在这组文档未完整列明，查实际 CLI，不猜。

复用 postFloorplan 成对产物：

```bash
ecc project show design.def --project "$PROJECT" --plain
ecc project show design.netlist --project "$PROJECT" --plain
ecc project set design.def /absolute/baseline/postFloorplan_ecc/output/chip_postFloorplan.def.gz --project "$PROJECT" --plain
ecc project set design.netlist /absolute/baseline/postFloorplan_ecc/output/chip_postFloorplan.v.gz --project "$PROJECT" --plain
ecc run --project "$PROJECT" --workspace place-route-001 --from placement --to routing --plain
```

先保存旧声明，创建后 CLI 恢复旧值；原先未声明才 unset。run 没有 --def/--netlist，不传虚构参数。范围不含完整验证，不与 full-flow baseline 混比最终签核/PPA。

## 5. refresh 和中断恢复

输入/top/PDK/flow 结构变化需要 fresh 或授权 refresh；普通参数微调用 workspace scope。refresh 比对 config-derived-manifest.json，手改 JSON/Tcl 时报 derived_configs_modified 且不替换。旧 workspace 无派生清单时可能没有保护基线，无报错不代表无覆盖风险。

恢复前确认旧进程退出，workspace 不仍被有效任务占用。读 status/log/report step 定位首个非成功步；环境修复后 resume，输入改变则 fresh/refresh，工具产物不完整从该步重跑。没有步骤目录的 step_unavailable 不能靠 force 修好，修环境后新建。

区分 flow success/partial/failed/ongoing/unstart/missing/corrupt 与 step success/incomplete/unstart/ongoing/pending/invalid。不手改状态，不拿残存报告证明成功。
