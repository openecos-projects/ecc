# 参数、Floorplan 与物理设计

适用：配置发现、宏布局、物理阶段调优。优化决策见 [收敛与优化](optimization.md)，执行边界见 [运行契约](run-workspaces.md)。

## 1. 四类配置来源

工具模板提供算法默认值；用户语义参数/审核 schema 提供覆盖；PDK 提供库、site、tap/endcap、buffers 和 corners；调度器每步重写输入/输出路径。共享 config/ 中同名文件会被后续步骤刷新，因此现在的 db_ecc.json 不保证代表早先步骤运行时的输入。

```bash
ecc param list --all --project "$PROJECT" --plain
ecc param list --step floorplan --project "$PROJECT" --plain
ecc param list --step placement --project "$PROJECT" --plain
ecc param show floorplan.core_util --project "$PROJECT" --plain
ecc config post_floorplan --project "$PROJECT" --workspace "$WORKSPACE" --plain
```

参数 show 要核对 type、default、source、range/choices、maps_to/config_target、所属步骤。config STEP 常只列实际配置文件路径，不保证输出全部内容；需进一步诊断时可只读该路径，说明未通过 CLI 暴露的细节，不改文件。

不带 STEP 的 config 是 project 视图，即使传 workspace 也不应把它当成完整 workspace 有效配置。核对有效值应组合 workspace param show、创建时 override provenance、step config 和报告。

## 2. 参数作用域与优先级

| 操作 | 持久化/生效 | 恢复含义 |
|---|---|---|
| project `param set` | ecc.toml；后续 fresh/授权 refresh | unset 删除 project 覆盖，重新解析默认/来源 |
| 创建 `run --set KEY=VALUE` | 只覆盖新 workspace，记录 cli-param-overrides.json | 不改变 project；不要丢失创建 override |
| workspace `param set` | home/params.toml；立即派生配置并失效相关后缀 | unset 恢复首次本地修改前 baseline，不一定是模板默认 |

创建优先级：CLI set > project params > 模板默认；PDK 和 step 调度仍管理资源/路径。随后 workspace local override 是该实验有效修改；同 key 以最后实际生效值为准。

```bash
ecc param set place.target_density 0.55 --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc param show place.target_density --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc param diff --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc run --project "$PROJECT" --workspace "$WORKSPACE" --plain
```

本地设置输出 from_step/invalidated_steps；检查真实边界，不硬编码所有 param 都从一个步骤开始。schema 所属步骤必须存在于该 ledger，PDK 路径不支持局部设。diff 是本地修改相对 baseline，不保证包含创建时所有 set，winner 提升不能只抄 diff。

数组/对象用引用的 JSON 字面量，整体替换，不按猜测局部 merge：

```bash
ecc param set floorplan.core_margin '[2, 2]' --project "$PROJECT" --plain
ecc param set cts.routing_layer '[4, 5]' --project "$PROJECT" --plain
```

带 `-` 的嵌套 key（如 route.RT.-thread_number）本身是完整 key；用 schema 规定的字符串/数字类型，不按 JSON 外观自行推断。

## 3. 可执行旋钮地图

下列 key 在文档/当前 schema 中有依据，每次仍需发现。未列出的算法字段不是禁止使用，但须 schema 支持和证据驱动。

| key/类别 | 含义与单位 | 影响/风险 |
|---|---|---|
| design.frequency_mhz | MHz；周期 1000/f | 综合与自动 SDC；不能偷偷改规格，自定义 SDC 要独立一致性检查 |
| floorplan.core_util | 面积反推 core 的目标利用率 | die_util 模式；与后续实际利用率不同 |
| floorplan.core_margin | 二元整数列表，映射 core 边缘留白 | 留出 tap/PDN/IO；查实际映射与单位 |
| floorplan.aspect_ratio | core 宽高比 | 改通道与线长；须核对外形限制 |
| floorplan.die_builder.mode | die_util / die_size | 固定尺寸与利用率反推不能混淆 |
| floorplan.die_builder.die_size.width_micron / height_micron | 固定 die 宽高，µm | 仅 die_size 生效；查看实际面积确认 |
| place.target_density | 布局目标密度 | 不直接改变 die 面积；不能低于物理容量需求后期待奇迹 |
| place.target_overflow | 布局收敛停止阈值 | 降阈值或增迭代不保证解决布线拥塞 |
| place.cell_padding_x | 数据库单位 dbu | 不是 µm；扩大占位可能利 pin access 也可能不可放 |
| place.routability_opt | 0/1 拥塞驱动 | 影响布局，不等于详细布线签核 |
| place.global_right_padding | 兼容旧参数 | 当前不映射 DreamPlace JSON，不作为有效调优旋钮 |
| place.random_seed / deterministic_flag | 复现与探索 | 多 seed 搜索不是设计改进证明；记录 seed/线程/工具版本 |
| place.num_threads / gpu / gpu_id / dtype | 运行资源和数值精度 | 改设备/精度可能影响复现，不作为免费 PPA 旋钮 |
| cts.max_fanout | 整数 fanout 上限 | 同时影响 CTS 与 ECC 自动 SDC；需核对多阶段 invalidation |
| cts.skew_bound | ns | 更紧不一定改善所有 setup/hold，可能增加 buffers/power |
| cts.max_buf_tran / max_sink_tran / root_input_slew | ns | 时钟 transition，必须与工艺/约束一致 |
| cts.max_cap | pF | 负载约束，不是功耗预算 |
| cts.routing_layer / buffer_type | 层序号列表 / 单元列表 | 仅选 PDK 支持且可布局/可计时的单元 |
| route.bottom_layer / top_layer | MET 名称 | 影响路由、DB 与 Sizer；不得越过工艺/集成限制 |
| route.RT.-thread_number | schema 当前为字符串配置字段 | CPU/内存预算 |
| route.RT.-enable_timing | 当前 choices 为字符串 0/1 | 默认关闭；启用需确认实际工具/分析能力 |
| filler.-min_filler_width | site 数 | 影响填充，不靠漏填跳过 DRC |
| rcx.thread_num | 线程数 | RCX corner 集合由 PDK 决定，不是线程参数决定 |
| sta.signoff | corner 组合的 JSON 结构 | 改动影响验收范围，不能删 corner 伪装通过 |
| sta.max_paths | 报告路径数量 | 增大只增加观测，不修复时序 |

语义默认值与原始模板可能不同，如 place.target_density 语义值 0.2 而模板 0.8；选择实际解析值，不从模板推断用户实验。默认不是所有设计的推荐最优值。

## 4. 三阶段 Floorplan

| 阶段 | 配置/行为 | 检查点 |
|---|---|---|
| preFloorplan | 派生 floorplan_ecc_simple.json，auto 宏模式，建初始 die/core | rows/site、容量、初始 macro/IO 条件 |
| macroPlacement | DreamPlace 仅宏摆放，写 macro_location.tcl | 实例、坐标、方向、通道/halo |
| postFloorplan | 共享 floorplan_ecc.json 以 file 模式读 handoff | tracks、IO、tap/endcap、PDN、clock-net、DEF/网表 |

正常 run 连续执行，没有自动 GUI 暂停协议。要阶段检查，使用已有 workspace 的有界范围或新 range。改 floorplan 参数时以 CLI invalidation 为准重跑，不只改最后的 postFloorplan。

### 手工宏/SRAM

```bash
ecc macro show --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc macro set u_ram0 --x 120 --y 80 --orient MY --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc macro import /absolute/inputs/macro_location.tcl --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc macro show --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc run --project "$PROJECT" --workspace "$WORKSPACE" --plain
```

这些示例是不同操作选择，不要在 set 后无目的 import 整表覆盖。坐标 µm；方向 R0/R90/R180/R270/MX/MY/MX90/MY90；实例真实存在，并符合宏 LEF 对称性/朝向与 die/core 边界。非空手工列表须覆盖全部硬宏，检查重叠、halo、pin access、通道和 PDN 连接。

import 解析独立输入 Tcl，整表替换；空文件清空；畸形语句整体拒绝。不要在 shell/Tcl 执行未经信任文件。合法交接形如：

```tcl
placeInstance u_ram0 120 80 MY
setInstancePlacementStatus -status fixed -name u_ram0
```

旧四列文本不是有效交接。无宏设计空文件合法。macro.placements 非空时 macroPlacement 保留 load/save 但跳过 DreamPlace；postFloorplan 提交 fixed 位置。本地修改立即派生 Tcl，并从 macroPlacement 失效；show 的 file_placements/diverged 用来核对一致性。只删最后一项才恢复自动；不能删除一个宏留下不完整手工列表。

不手改受管 macro_location.tcl，也不靠设置 macro_placer.mode/file_path 绕过宏接口。老拼写 macro_localtion.tcl 可由 ECC 打开时迁移，不自行 rename 内部文件。

### 物理约束

tap/endcap/site、well_tap.distance_micron、boundary_tap.rule_micron、IO 层、PDN rail/stripe/connect_layers 可能是可审字段，但工艺规则不是优化建议。改 pitch/width 会影响路由资源且有电源完整性风险；DRC clean 不证明 IR/EM 通过。用户未提供 power-grid 验收要求时记录未验证，不自动削弱 PDN。

## 5. DreamPlace 深层配置

macro/placement/legalization 共享 dreamplace_ecc.json，调度器控制输入/结果路径和阶段 flag。默认 timing-aware placement 关闭；不能只开 timing flag 就宣称时序驱动能力生效。

查 `param list --step placement`：global_place_stages 数组控制迭代、learning_rate/decay、wirelength/optimizer；num_bins_x/y 与 auto_adjust_bins 控制密度网格；density_weight/gamma/noise/initialization 是算法假设，一次只改有因果假设的一组。

GPUGR：auto 在设备和扩展支持时用 CUDA，否则 cpu_pr_mt；CPU pattern backend 要求 area_adjust_rrr_iters=0；线程来自 num_threads。默认继承 workspace bottom/top layer。文档还提到 params.dreamplace 原始覆盖，但本 skill 只使用当前 CLI 暴露的 place.* schema，不直接写 TOML。GPUGR/RUDY/EGR 输出是布局预测，不能称最终 DRC 或 routing wirelength。

避免自动设置详细布局 external command、未经信任的 executable 路径或数值 inf；只有当前 CLI 接受且任务需要时才用，并记录可复现/子进程风险。

## 6. Sizer、RCX/STA 与无专属参数步骤

Sizer 无独立审核调参 schema。setup 使用 PDK setup Liberty；存在 MIN 组时可做 FF hold_only，再内部 DreamPlace 合法化。生成 env/cmd 文件、暂存 DEF/网表不能手改。FF hold pass 使用 placement parasitics，不等于 MIN/RCbest 最终 SPEF 签核；成功后仍须 route/RCX/多 corner STA。

RCX 按 PDK 产生 `<design>_<RCcorner>_<temperature>C.spef`。STA liberty 由 PDK 派生，不提供局部任意覆盖；sta.signoff 可配置结构但不授权删验收 corners。当前 ICS55 示例有 13 个分析组合，实际数量按版本和请求检查，不硬编码。

LEC、postRouteLec、DRC、LVS、Harden 没有可用专属调参 schema（以当前 list 为准）；DRC JSON 为空，规则来自 tech LEF。不要虚构 drc.ignore_errors、lvs.skip、harden.force 或 Sizer 私有旋钮。综合可观察 `YOSYS_SYNTH_STRATEGY`（文档示例 DELAY/AREA/BALANCE），需核对当前 runtime 支持并记录环境；不把它说成公开 ecc param。
