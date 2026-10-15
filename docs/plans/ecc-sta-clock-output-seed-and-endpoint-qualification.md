# ECC STA：修复 clk→Q 旧 AAT 下限与受约束端点资格

日期：2026-10-10。状态：P0–P5 已执行并验证；P6 全量 placement QoR 尚未启动。

## 1. 目标与范围

修复两个已经得到同 DEF 对照支持的问题：

1. 内部重新计算 clk→Q 时，输出 Q 的旧原生 STA AAT 被当作 startpoint seed，并通过
   `include_self=True` 保留下来，形成错误下限，影响时序值及该分支的梯度。
2. 图上的末端／timing-check 引脚被直接计入 WNS/TNS，未区分当前 SDC 下真正受约束的
   端点，导致无约束 latch D、QN、RN 产生虚假的负 slack。

第一项在 ECC-DreamPlace 的 clk→Q 计算边界修复；第二项的资格判定由 ECC-Tools 原生
约束与时钟状态负责，ECC-DreamPlace 消费显式元数据。两个问题分开实现、分开验证。

不增加用户参数或开关，不调整已选定的 placement/sizing 权重、smooth τ、padding、
density、overflow 策略及 RRR。此次不重写 LUT、RC、完整 latch time borrowing、hold
或 CPPR 算法；已有约束支持范围必须明确，不能把未支持的约束静默当作无约束。

## 2. 已确认的证据

诊断使用同一份最终合法化 DEF、配对网表、SDC、TT Liberty 与冻结运行环境，均为
STA-only；输入哈希保持一致。外部为 OpenSTA placement MET2 RC、ideal clocks，无 repair。

[完整诊断与代码定位](/nfs/share/home/zhaoxueyan/dataset_cx55_ecc_workspace/ecc-stage-d-latch-opensta-align-20261010.fx87leoj/diagnosis.md)
与 [精确指标](/nfs/share/home/zhaoxueyan/dataset_cx55_ecc_workspace/ecc-stage-d-latch-opensta-align-20261010.fx87leoj/diagnosis.json)。

| stage_d_ysyx_24080018，同最终 DEF | WNS / ns | TNS / ns |
| --- | ---: | ---: |
| 原内部 hard STA | -1.954489 | -581.656375 |
| 诊断：只清除旧 Q AAT | -1.554608 | -177.124203 |
| 诊断：清除旧 Q AAT，按双方共有的 1,523 个受约束端点统计 | -1.554608 | -163.068389 |
| 外部 OpenSTA placement RC + STA | -1.536122 | -160.544804 |

清除旧 AAT 解释原 gap 的 96.06%；端点一致后 WNS/TNS 差距分别为 1.20%/1.57%。
这些是隔离诊断指标，尚不是正式实现或重新优化 placement 的结果。

关键事实：

- 1,456 个 clk→Q 输出与 startpoint 列表重叠。`exu.i_bypass_waddr_4…/Q` 的旧 seed
  为 1362.552 ps，新 GN→Q rise LUT 结果为 731.695 ps，最终却保留旧 seed。
- 两个 latch、四项 rise/fall GN→Q 查询，在相同 OpenSTA slew/load 下，导出的原始
  LUT 与 `report_dcalc` 误差小于 0.0001 ps。LUT／边沿选择未发现该量级错误。
- 113 个额外内部端点为 38 D、38 QN、37 RN；OpenSTA 对所有引脚返回
  `slack_max=INF`，内部却累计 -14.055827 ns TNS。
- OpenSTA 对未连接已声明时钟的 register/latch clock pin，建立零 arrival 的 unclocked
  起点，再沿 clk→Q 传播；不会把旧 Q 报告作为新的 input-delay 下限。
- 原生 `TimingAnalyzer::getClockName()` 找不到真实时钟时会回退到首个已声明时钟；
  `getEndPointClockNames()` 也可能沿用回退。它们不能单独作为端点受约束的依据。

## 3. 修复一：clk→Q 输出状态由当前计算负责

### 3.1 行为契约

- 真实 PI 的 SDC input delay／input transition 继续作为传播起点。
- 对当前 level-0 clk→Q 弧覆盖的输出，AAT 来自当前 launch reference 与当前 LUT/RC
  查询结果。旧原生 Q AAT 只能用于诊断，不进入该输出的最大值候选。
- 同一 Q 的多条有效 clk→Q 弧仍按 hard/smooth 模式聚合，不覆盖其中较差的有效弧。
- Q 的 launch/startpoint 身份及输出 net 的传播保留。不能直接从 `start_points` 删除 Q，
  因为当前 PI-net 传播路径也依赖该列表。
- 其他 level 的组合弧与 net 聚合保持现有多来源合并语义。
- 不新增 latch 名称匹配或针对某个 case 的判断；修复适用于共用 clk→Q 输出路径。

### 3.2 推荐实现

在 `TimingPropagation.calculate_clk2q_aat()` 的输出归约处，让当前 level-0 弧产生
Q 的新状态。这里的“替换”只针对本次弧覆盖的 destination，不能清空整个 pin 张量。

**实施前置条件：当前 smooth helper 不能直接切换 `include_self=False`。**
`smooth_scatter_max_tau()` 从全 `−inf` 张量开始分组；不包含 self 时，未被 index
触及的位置也返回 `−inf`。hard `torch.scatter_reduce` 则保留这些位置的 dest。
因此先在现有 helper 修正这项语义，再让 clk→Q 的 AAT／输出 slew 不包含旧状态：

| destination 情况 | `include_self=False` 的结果 |
| --- | --- |
| 没有被本次 index 触及 | 保留原 dest，包括其梯度路径 |
| 被有效候选覆盖 | 仅归约本次 src，旧 dest 不参与值或梯度 |
| 被触及但 src 全为 `−inf` | 保留该组不可达结果；不能回退到旧 dest |
| index 为空 | 原 dest 原样返回 |

例如 `dest=[7,99,42]`、`index=[1,1]`、`src=[2,3]`，hard 得到 `[7,3,42]`；
smooth 只将中间项改为 `τ·logsumexp([2,3]/τ)`。是否触及与是否有限必须分开判断。
修正同一个 canonical helper，并覆盖其 min 包装与现有调用者，不另写 clk→Q 专用
scatter。`include_self=True` 的多来源合并行为保持原契约。

AAT 与输出 slew 都明确由当前 clk→Q 查询负责；用测试确认去除旧 seed 后的结果，
避免 AAT 已刷新、输出 slew 仍保留旧值。诊断中清除 AAT 与同时清除 AAT/slew 的结果
相同，但正式实现仍需验证两者的状态归属。

旧原生 AAT／slew 元数据可以继续保留为参考；无需先修改 startpoint 导出格式，也不
同时在生产者和消费者重复清零。不要每次 forward 全量扫描名字、重建 DB 或增加
Python 逐弧循环。

### 3.3 必要测试

测试归属：`ecc-dreamplace/tests/ops/timing_propagation/`，使用已有 propagation fixture。

- 先在 `test_smooth_scatter_reduce.py` 覆盖未索引的有限值、重复 index、空 index、
  全不可达组及 dest/src 梯度；max/min 包装均验证，不能只测覆盖全部 destination 的例子。
- 旧 Q seed 高于、低于新 clk→Q 值，均得到当前弧的正确结果；PI input delay 不受影响。
- 多条弧进入同一 Q；rising/falling edge、non-unate、hard 与 smooth τ=2 ps。
- 在旧 seed 高于新延迟的场景，当前 LUT/size/load 分支梯度与有限差分相符，不能被
  旧常数截断。修改 load／cell timing 后的第二次 forward 必须使用新值。
- Q 输出 net 能继续到达后级 endpoint；多个合法传播来源没有遗漏。
- CPU 为必过；已有 CUDA 测试环境可用时核对 AAT、slew、梯度一致性。

## 4. 修复二：端点资格由真实约束状态决定

### 4.1 原生资格规则

保留图的候选端点与连接关系，增加 max-analysis 受约束资格。资格判断独立于当前
slack 的正负、当前 slew/load 数值，以及“当前是不是关键端点”。

| 候选类型 | 进入 max WNS/TNS 的条件 |
| --- | --- |
| 输出 port | 当前分析有实际生效的 output-delay／已支持的显式路径约束 |
| Setup 引脚 | 有有效 setup check，并有实际传播到 capture pin、来自 SDC 已声明时钟的时钟状态 |
| Recovery 引脚 | 有有效 recovery check 与真实 capture clock；保留现有独立 check-class 语义 |
| 无 fanout 的内部 Q/QN 或其他图末端 | 不能仅因是图末端就成为受约束端点；需存在实际 timing constraint |
| 未连接已声明 capture clock 的 latch D/RN | 保留图与诊断数据，当前 max timing 指标不计入 |
| Removal/hold/width 等其他 check | 保留现有分析域；不能错误混入 setup/max 标量目标，也不能整体删掉 async checks |

复用现有 SDC constraint、`TimingPoint::get_clock_state_map()` 和实际 timing-check
关联关系。不得使用 `getClockName()` 的默认时钟回退来证明资格，也不得用
“RAT 是有限值”、引脚名后缀、是否 latch 或外部端点名单代替约束判断。

对已支持的多时钟与例外约束，资格需反映实际生效的 check；未解析的约束应给出
明确诊断，不能宣称这类路径已对齐。本次不为通过测试扩展新的 SDC 功能。

### 4.2 数据契约与消费者

使用现有 timing schema，升级到 **v2**。固定以下最小字段，避免实施时各消费者
自行定义 mask。N 为 `len(end_points)`，C/T 分别为实际导出的两张 check 表行数；
第二维固定为 **[rise, fall]，表示被检查的数据端边沿**，不是 capture clock 边沿。

| 新字段 | 形状／Python tensor 类型 | 对齐对象 |
| --- | --- | --- |
| `endpoints_max_valid` | N×2，bool | `end_points` 的实际行顺序 |
| `endpoints_max_reason` | N×2，int32 | 同一 endpoint／数据边沿的资格或排除原因 |
| `endpoints_constraint_max_valid` | C×2，bool | `endpoints_constraint_arcs` 的实际导出行 |
| `endpoints_constraint_max_reason` | C×2，int32 | 同一 constraint check／数据边沿的原因 |
| `endpoints_timing_check_max_valid` | T×2，bool | `endpoints_timing_check_arcs` 的实际导出行 |
| `endpoints_timing_check_max_reason` | T×2，int32 | 同一 timing check／数据边沿的原因 |

原生 snapshot 使用定长边沿对和 reason enum；`py_imp` 按现有 list 接口转换，
consumer 只转换类型／索引。reason 定义与含义由原生 owner 维护：有效、缺少输出
约束、无真实 capture clock 状态、check 不生效、不属于 max 分析、无约束图末端。
“已知无约束”与“约束语义不支持／资格无法确定”必须区分；后者给明确诊断并阻止
该分析被标为已对齐，不能静默按无约束处理。无有效行的数组仍保持 `(0,2)` 契约。

两张原始弧表目前均为 **8 列**，末列为 `library_arc_id`。其中 constraint 表首列
是 clock-local 索引，timing-check 表首列是 design pin ID；不得混用，也不得把
资格追加成改写既有列语义。原生资格随实际 append/skip 同步导出，不复制 timing graph。

消费者统一遵循：

1. 在 setup RAT／recovery worklist 构造时先排除无效 check/边沿，再归约有效 RAT；
   只在最终 WNS/TNS 上 mask，仍可能让无效 check 污染有效端点的 RAT 与梯度。
2. endpoint 某边沿的资格来自该边沿有效 max check 或生效的输出约束。每个端点
   取有效边沿／check 中最差 slack，TNS 每个引脚只计一次；同一引脚有 setup/recovery
   不能重复累加。无效边沿不能进入 `min(rise_slack, fall_slack)`。
3. WNS/TNS、组合 timing loss、smooth 目标、critical endpoint pruning、Pin2Pin
   路径选择及报告共用资格。hard/smooth 只改变聚合方式；cap/slew 保持物理检查覆盖。
4. 全部无约束时，计数为 0、状态明确，timing 标量与梯度有限且为 0；不得对空集合
   求 min，也不得通过 `0×inf` 制造零梯度。原始候选端点与 check 仍可诊断。
5. sizing 后 native rebuild、buffer materialization、full refresh 和 standalone S50
   terminal STA 都重新导出并校验资格；不得复用旧 pin ID 对齐的 mask。

初次加载与 refresh 共用 schema／字段校验，检查版本、形状、类型、索引域和行身份。
旧 native wheel／新 Python 混用必须明确报错，不提供全 true fallback。refresh
校验通过后才发布新的 `raw_db.pydb`／generation，避免半更新状态。其他 backend
保留其现有约束来源；共享 helper 改变需跑已有 bridge 测试，不重构所有 backend。

### 4.3 必要测试

原生规则／导出测试归属 ECC-Tools；Python 消费／目标测试归属 ECC-DreamPlace。

- 无时钟 latch、声明且实际连接时钟的 latch、普通 clocked FF；两个 latch 的物理
  类型相同、仅 SDC/clock connectivity 不同，资格必须不同。
- 未使用 QN、未约束输出 port、约束输出 port；无约束端点保留在诊断但不产生 TNS。
- 有效 setup/recovery 与无效 check 混合；保留受约束 recovery，不按 RN 一刀切排除。
- 只有 rise 或 fall 受约束、同 pin 多 check、全部端点无约束；验证逐端点计数、
  最差有效 slack 与目标梯度，不能以静态字段存在测试代替行为验证。
- 多时钟 fixture 证明不会把未绑定 capture pin 错配到第一个已声明时钟。
- 较差但无约束端点的存在不改变目标或梯度；有效端点变差则必须影响目标。
- 重排 pin ID、刷新 native DB、空有效端点集及 schema 不匹配的边界验证。

## 5. 代码归属与改动控制

| 位置 | 责任 |
| --- | --- |
| ECC-DreamPlace `ops/timing_propagation/timing_propagation.py` | 修正现有 scatter 语义与 clk→Q 归约；接入统一资格，避免引入额外业务分支 |
| ECC-Tools `iSTA/source/module/timing_analyzer/` | 约束资格的原生语义；优先增加专门的小模块，不扩张 1,913 行的 TimingAnalyzer.cpp |
| ECC-Tools `iSTA/interface/TimingExportAdapter.hpp/.cpp` | 导出资格及 schema；保留候选端点与诊断元数据 |
| ECC-Tools `src/interface/python/py_imp/idb_to_imp_db/PyPlaceDB.h` | 声明与候选端点／check 列表对应的资格、原因及 schema 字段 |
| ECC-Tools `src/interface/python/py_imp/idb_to_imp_db/PyPlaceDBTiming.cpp` | 在端点／check 的实际导出循环内同步填充资格，保持 pin ID、行顺序与数组长度一致 |
| ECC-Tools `src/interface/python/py_imp/py_register_imp.cpp` | 将新增字段注册到 Python `PyPlaceDB`，原生 Python 边界必改 |
| ECC-DreamPlace `macroPlaceDB.py`、`BasicPlace.py`、`PlaceObj.py` 的现有接入位置 | 仅传递必要元数据；不在大文件中重复实现资格规则 |
| ECC-DreamPlace timing propagation 下的小 helper | mask/check worklist 的集中消费；报告、目标、pruning 与路径选择共用 |
| ECC-DreamPlace `ops/placeio_ecc/` 初次加载边界与 `refresh.py` | 共用 v2 校验；替换 refresh 中写死 schema=1 的判断，校验后发布新 DB |
| ECC-Tools `test/`、ECC-DreamPlace `tests/ops/timing_propagation/` | 原生规则与共享传播行为测试 |
| ECC-Tools `test/native_scenarios.py` | 更新两处 schema=1 的 refresh 假设；两次连续 sizing/rebuild 后逐项核验资格与身份 |
| Parent `scripts/regression/placement/` | 复用现有报告／外部评估与冻结输入；仅必要时添加 STA-only 验证入口 |

遵循 `docs/review-guidelines.md`：不新增散落特判，不复制同一 mask 规则，不增长已有
巨型模块来容纳新业务。保留现有 dirty changes；提交时只暂存本计划所属实现与测试。

### 5.1 `py_imp` 的明确改动与接口验收

上述三个 `py_imp` 文件都是第二项修复的必改位置。原生资格计算完成后，必须通过
此处进入实际加载的 Python 对象，不能只修改 `TimingSnapshot` 或在 DreamPlace
按名字重新推断资格。

- `PyPlaceDB.h`：声明第 4.2 节六个字段，端点与 check 都包含边沿资格及原因。
  mask 对齐的是 `end_points`／实际导出的 check 行，而非全量 `pin_names`。
- `PyPlaceDBTiming.cpp`：在导出每个候选端点或 check 的同一位置追加对应资格，正确
  处理缺失 pin、跳过的弧和 clock-local 索引。保留现有弧行的列语义；不能用不对齐的
  原始 snapshot 顺序直接填充 mask。schema 与字段必须一起更新。
- `py_register_imp.cpp`：注册新字段，并验证新 `ecc_py` 构建后 Python 能读到真实值。
  缺失注册、长度错位或旧 `.so` 的情况必须由 focused native/import 测试检出。
- 新增原生导出测试：确认有效／无效端点的逐项身份、mask、原因和 check 关联一致；
  native rebuild 后重新核验，不仅检查属性存在。initial import、两次 sizing refresh
  与 buffer materialization 后的接口均纳入生命周期验收；复用已有 mutation fixture。

第一项的旧 seed 来源也在 `PyPlaceDBTiming.cpp` 的 startpoint 导出循环：当前将
Q 的原生 `max_rise_aat_ps/max_fall_aat_ps` 放入 `inrdelays/infdelays`。P1 必须覆盖
这条真实导出链的回归测试，明确原生报告值与 clk→Q runtime 边界条件的区别。
按第 3 节选择消费者归约作为修复位置，避免在 `py_imp` 和 Python 同时增加重复
清零规则；如执行时决定改由生产者负责 seed 语义，先同步修改这一归属决定。

使用现有文件实现这三处改动通常不需要修改 `py_imp/CMakeLists.txt`；只有新增编译
单元时才调整构建清单。新的原生约束算法仍归属 iSTA owner，`py_imp` 负责数据转换。

## 6. 执行顺序与验收门槛

**修复资格阶段为 P0–P5；P6 是后续 QoR 实验，不作为“两个 bug 已修复”的前提。**
没有 P3 的正式运行证据，不能仅凭 fixture 或诊断结果声明修复完成。

| 阶段 | 工作 | 验收 |
| --- | --- | --- |
| P0 | 记录三个仓库 HEAD/dirty、冻结诊断输入与运行时身份，补最小失败 fixture | 复现旧 Q 下限、无约束 endpoint 假 TNS，以及 smooth 不保留未索引 dest 的问题 |
| P1 | 先修正 scatter 契约，再单独修复 clk→Q；forward/gradient 与真实导出链测试 | 同 DEF hard STA 接近诊断 -1.554608/-177.124203；PI、多弧、空 index 与连续 forward 正确 |
| P2 | 原生资格、v2 六字段、pybind、共享 consumer 和 initial/refresh 校验 | 本 case 由内部语义识别 1,523 个有效 max endpoint；113 个无约束 latch endpoint 保留诊断；row/edge 资格一致 |
| P3 | Nix 环境构建并同步安装，验证实际 native/Python import，再做本 case 真实 STA-only | 正式代码无需 monkeypatch、无外部名单输入，WNS/TNS 与同 DEF OpenSTA placement RC 差距均 ≤3% |
| P4 | 冻结 13 份最终 DEF，旧／新 hard STA-only 与同输入外部 placement RC 对照 | 全部完成；逐项 gap、端点身份／数量和原因落表，符合第 6.1 节的回归判据 |
| P5 | stage_d_ysyx_24080018 与 BM64 做 placement/S10 canary | timing 修正进入目标/梯度，窗口与终端 rebuild 正确；geometry 合法、输出可重载，外部 RC/STA 可完成 |
| P6 | 复用当前固定参数，6 并发重跑 13-case placement 与外部 placement RC/GR50 | 形成新旧 QoR 对照，说明修复后的优化效果，不预设所有 case 获益 |

P1 与 P2 各自保留独立 diff/验证证据，便于定位性能或指标变化。P3 不能用旧 `.so`
配新 Python 的 smoke 代替；通过后才进行后续阶段。

构建遵循本仓库流程：有 Nix 时先进入 `nix develop`，再运行
`uv sync --no-build-isolation-package ecc-dreamplace --no-build-isolation-package ecc-tools-bin --verbose`。
记录实际加载的 Python、DreamPlace、ecc_py/native .so 路径与哈希，验证两个组件的
schema 一致。真实 native 实验使用已验证的复制并修正 ELF/RPATH 的 `python-nix`
launcher；不直接用 Nix `ld-linux` 包装 UV/Conda Python。构建／launcher 失配时先
修复运行环境，不把导入成功或旧 `.so` 的 smoke 当作源码资格证据。

### 6.1 数值与回归判据

- 固定 DEF、配对网表、SDC、Liberty/corner、placement MET2 RC、ideal-clock 模式；
  external 禁用 repair。记录输入哈希、聚合模式、单位和完成状态，禁止混用 GR RC。
- 本 case 的 hard WNS/TNS 各满足 `|internal−external| ≤ max(3%×|external|, δ)`；
  δ_WNS=0.01 ns、δ_TNS=0.1 ns，是本次验收的绝对误差下限。当前目标 case 的幅值
  较大，实际仍由 3% 门槛决定；接近零同时报告绝对差，不靠百分比夸大变化。
- P4 为每 case 建立相同 frozen DEF 上的旧 hard 基线。已处于上述容差内的指标，
  修复后仍需在容差内；原本超差的指标，不允许其绝对误差新增超过对应容差而没有
  逐 endpoint/check 的解释。剩余偏差列入清单，不能把 13 case 一概宣称为 3% 对齐。
- 有效端点数量相同不足以证明资格一致；核验端点身份、数据边沿和生效 check。
  1,523/113 是目标 case 的诊断预期，不是代码中的常量或筛选规则。
- hard 数值对齐与 smooth τ=2 ps 的目标／梯度行为分别验收。float64 非并列点的
  有限差分使用 `rtol=1e-3, atol=1e-6`；hard 并列点只核验合法子梯度，不强求唯一梯度。
  原始 ps 单位下核验，再转 ns 报告；多弧 LSE 的自然差异不计作 hard 报告错误。
- P5 不要求优化后的 TNS 必然更好。要求真实窗口与最终 STA 链完成，且两个 canary
  输入／输出 geometry 契约通过；若失败先定位修复影响，不启动 P6 掩盖问题。
- 在同 CPU 线程数、同 hard/smooth 模式下记录 warmed forward 的耗时和峰值内存；
  发生明显退化时先定位。资格只在导出／refresh 时构造，forward 不增加按名字搜索、
  Python 逐 pin/check 循环或重复 native STA。

13-case 冻结输入／原配置来自：
`/nfs/share/home/zhaoxueyan/dataset_cx55_ecc_workspace/ecc-placement13-ordinary-fixed500-smooth2-rho02-alpha1-20261010.7hrsfmqo/`。
P6 保留原 `random_center_init_flag=1`、seed=3000、S10B0、ordinary、growth=1、固定
sizing 500/5/1/1 且 α=1、smooth τ=2 ps、GP ratio=0.2、padding=200、density=0.4。
hard STA 为对齐口径，smooth 目标单独标明，不能把两者混写成同一指标。

## 7. 完成定义与交付

- 两项正式实现通过各自 focused tests，实际安装环境、native rebuild 与 schema 已核验。
- 本 case 的 3% 对齐来自内部资格与正式代码，而非手动删除端点／外部名单。
- 原始候选端点、受约束端点、排除原因、check 类型、聚合模式及计量单位有可复核报告。
- P0–P5 通过后可声明两个 bug 修复并完成规定回归；各阶段状态分别记录，不能将
  未完成的 P4/P5 写成已交付。P6 完成后才报告完整 13-case placement QoR。
- STA 报告修正与重新 placement 的 QoR 分开记录，不把口径修正称为布局优化收益。
- 修复交付：独立的两项源码／测试 diff、构建身份、目标 case 正式证据、13-case
  STA 对照、两 case canary 与剩余偏差。QoR 实验另交付 13-case placement／外部对照。
- 执行本计划本身不包含推送、PR 更新、合并或 route/signoff 实验；这些按后续具体指令处理。

当前 checklist：

- [x] 两项问题的同 DEF 诊断、OpenSTA 对照与证据落盘。
- [x] 修复计划落盘。
- [x] P0 最小失败 fixture 与执行基线。
- [x] P1 clk→Q 正式修复。
- [x] P2 原生端点资格与消费者。
- [x] P3 构建／安装／单 case 正式资格。
- [x] P4 13-case STA-only 回归；eth_top 的额外变化有逐端点 OpenSTA 证据。
- [x] P5 placement/S10 canary。
- [ ] P6 13-case placement QoR 回归。

## 8. 本次审查评分与未决风险

评分评价实施计划的完整性，属于工程判断，不代表实现进度或 QoR 通过率。

| 维度，每项 2 分 | 改进前 | 改进后 | 依据 |
| --- | ---: | ---: | --- |
| 根因与证据 | 1.8 | 1.8 | 同 DEF ablation、LUT 与 endpoint 对照充分；仍是诊断实现 |
| 传播／梯度契约 | 1.4 | 1.9 | 补齐 smooth 未触及 dest、空 index、不可达组和梯度归属 |
| 原生接口与生命周期 | 1.4 | 1.9 | 锁定 row×edge 六字段、8 列弧索引域、pybind 与连续 refresh |
| 验收与回归 | 1.6 | 1.8 | 明确 hard/smooth 分工、绝对容差、旧基线和身份级核验 |
| 范围与执行成本 | 1.8 | 1.8 | 复用现有 helper／fixture，修复资格与全量 QoR 分阶段交付 |
| **合计** | **8.0/10** | **9.2/10** | **可进入 P0–P2 实施；达到交付标准仍取决于正式运行证据** |

保留三项风险：原生已支持 SDC/多时钟资格是否能可靠读取；端点表与不同索引域的
check 表经过 rebuild 后能否始终对齐；去除旧 seed 后剩余 slew/load／latch 语义差异。
P0–P2 用最小 fixture 先确认前两项，P3/P4 量化第三项。出现不受支持的真实约束时，
记录具体限制并调整资格结论，不扩大成本去重写完整 latch 或 SDC 算法。

## 9. 执行结果

执行目录：
[修复证据与完整结果](/nfs/share/home/zhaoxueyan/dataset_cx55_ecc_workspace/ecc-sta-repair-20261010.fudweodt/results.md)。

- 正式 hard STA：目标 case 从 -1.954489/-581.656375 ns 改为
  -1.554608/-163.068375 ns，与同 DEF 外部 placement RC 的 WNS/TNS gap 为
  1.20%/1.57%。原生规则识别 1,523 个有效端点，保留 113 个排除端点的诊断。
- 传播／接口测试 114 passed；原生导出、两次连续 sizing refresh、buffer 插入后
  STA rebuild 的三项集成测试通过。独立 C++ 资格 fixture 通过。CPU 验证完成，
  当前 PyTorch 是 CPU 构建，未执行 CUDA parity。
- 13 个冻结 DEF 的旧／新 hard STA 全部完成，输入哈希相同；结果见
  [STA 对照表](/nfs/share/home/zhaoxueyan/dataset_cx55_ecc_workspace/ecc-sta-repair-20261010.fudweodt/sta13-comparison.md)。
- eth_top 的 1,043 个排除端点全部得到 OpenSTA `slack_max=INF`；旧版在这些端点
  累计 -40.960461 ns 假 TNS。移除后总 TNS 从 -294.602406 变为 -253.334250 ns，
  与外部 -334.193542 ns 的剩余 gap 扩大。此变化已经解释，不能宣称全批次均为 3% 对齐。
- 两 case 用原配置完成 placement/S10、终端 full refresh、合法化、外部 placement RC
  与新 DEF 重载 hard STA。外部 BM64 TNS 从 -492.144653 变为 -430.954712 ns
  （12.43%）；stage_d_ysyx_24080018 从 -160.544800 变为 -90.952515 ns（43.35%）。
  这是两个 canary 的结果，不代表完整 13-case placement QoR。
- 同 BM64 DEF、8 CPU 线程、2 次预热后 5 次 forward，中位耗时旧/新为
  0.248885/0.248590 s；该样本未观察到明显传播开销增加。

实现限定：schema-v2 的资格 reason 由原生 enum 定义，未能在 scalar endpoint/check
资格中表达的 max path exception／clock-group 约束明确报错，未扩展这类 SDC 功能。
构建已同步到 Python 3.11 native 环境，保留原 `uv.lock`；旧 schema wheel 混用会报错。
整理提交时补跑了配置／窗口／传播／接口的组合测试：317 passed，13 subtests
passed；ECC 参数与回归入口 43 passed。ECC-Tools 修复接到最新 PR 分支后重新
通过 Nix 构建并由 uv 安装，再运行原生导出、两次 sizing refresh 和 buffer refresh
三项集成测试，全部通过；C++ 资格 fixture 也通过。回归入口的 BM64 实际准备与
配置 preflight 完成，新的 schema-v2 runtime 来源见 regression README。
完整 13-case 新 placement／GR50 与远端 exact-head CI 仍需分别验证。
