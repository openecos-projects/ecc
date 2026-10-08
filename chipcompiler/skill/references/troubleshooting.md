# 故障诊断与安全恢复

先用 `status` 找首个失败/非成功步骤，再 `log STEP` 和 `report step STEP`；下游失败常是上游缺产物，不以最后报错作为根因。必要时 `config STEP` 核对实际输入/库/路径。命令带显式 project/workspace/plain，帮助/版本除外。

## 1. 错误码决策表

| 错误/状态 | 安全处理 |
|---|---|
| ecc: command not found | 核对 wrapper/PATH/真实安装，别重装全部环境 |
| env_not_ready | doctor 获取缺组件与 remediation；修好后 fresh/resume |
| pdk.root is required | pdk set-root 或授权环境变量；show fallback 不替代显式配置 |
| run_exists | 目录不是有效 workspace；优先新名，不自动 rm/overwrite |
| overwrite_refused | ECC 安全保护；人工检查，不能强删绕过 |
| invalid_workspace | 单段 ID 或绝对目录，核对保护路径/父目录/加载性 |
| workspace_required | 显式指定报错列出的正确 ID |
| workspace_not_declared | 先合法 import 或 fresh，不手加 manifest |
| legacy 项目迁移提示 | migrate 看计划，批准后迁移，不自己移动 runs/ |
| selector_requires_workspace | 目标还未建，先 fresh；resume/only 不创建实验 |
| selector_conflict | 只保留一种选择器，核对新 range 的互斥条件 |
| flow_range_requires_pair | from/to 成对，新 range 入口输入完整 |
| force_requires_only | force 只用于 only，不是通用绕过 |
| unsupported_preset | 从实际 supported presets 选，不猜名称 |
| unknown_project_field | key 不在公开 project 字段表；如 flow.skip_steps，报告能力缺口，不直接改 TOML |
| unknown_step | 既有 workspace 照抄持久化名，含空格时引用 |
| step_input_missing | project 注册正确入口文件，匹配阶段/库；run 无 --def/--netlist |
| step_unavailable | 修环境/创建失败根因，改用 fresh 或授权重建，不改状态 |
| flow_mismatch | 目标与 ledger 分叉，保留原实验，fresh 或明确批准重建 |
| set_requires_fresh_run | 已有实验用 workspace param，新实验才 set |
| workspace_param_refresh_failed | key 需审核，所属步骤需存在；失败后核对未被部分改变 |
| workspace_param_requires_managed_workspace | 导入/声明合法 workspace；不改内部 params |
| param_requires_ecc_toml | project 无可写声明入口；按项目实际模式补齐/选择 scope，不造内部文件 |
| derived_configs_modified | 只读审查 diff；用 param/macro 表达，确认丢弃才 refresh --force |
| unsupported_schema_version | 工具/数据版本不兼容，选匹配版本；不改 schema_version 欺骗加载 |
| config_layer_diverged | 比较 project/manifest/workspace 实际来源；警告非自动失败，不手改基线 |
| checklist_unavailable | 非严格只读请求可 inspect 刷新，再 checklist；未跑验证需真正执行 |
| signoff_incomplete | inspect 查具体 requirements/risks，修根因；不绕 export gate |
| QoR NOT_RATED | 区分未跑、证据坏、陈旧、hold缺失、无可评维度，修真实来源 |

## 2. 环境/工具症状

### Yosys/slang/Liberty

doctor 的 yosys/slang 检查为第一依据；旧工具可报 yosys slang frontend check failed。单独 `help read_slang` 需查看命令退出码和输出，不能“没出现 No such command”就当通过（可能二进制根本没运行）。

DFFLIBMAP 的 TCL uncaught exception 可源自非交互 shell 落到系统旧 Yosys。记录 wrapper 环境、ecc version、二进制解析、Liberty 及 synthesis log，使用已授权的 OSS CAD Suite wrapper 恢复；不要改综合网表/工具脚本掩盖崩溃。

### Tcl init.tcl 精确版本冲突

仅当日志明确报 Tcl version/init.tcl 不匹配时，检查继承的 TCL_LIBRARY/TK_LIBRARY 与系统 libtcl 实际版本。可在本任务子命令局部尝试：

```bash
env -u TCL_LIBRARY -u TK_LIBRARY ecc doctor --project "$PROJECT" --plain
```

只有确认环境污染且修复必要时，对对应 run 使用同样局部环境并记录。不要全局 unset、复制 Tcl runtime、修改 /usr 或假设所有 EDA 失败都是 Tcl 问题；用户指定 Tcl 库时先解释影响。

### DreamPlace/GPUGR

区分 CUDA 扩展/设备不可用、CPU backend 不支持非零 rrr_iters、内存不足、数据解析、算法不收敛。按 schema 选择真实可用 backend；CPU fallback 是运行策略变化，要记录而非宣称性能相同。OOM 先减并发/线程或满足内存，不盲目放宽质量门。

### Sizer

核对 binary + runtime root/src/sizer_os.tcl、setup/MIN Liberty、SDC、输入 DEF/网表和 hold pass 暂存输出。setup 成功而 hold/合法化失败时整个 timing optimization 不算成功。不能绕过去声称已完成 setup/hold 收敛；修依赖后重跑完整该步。

### STA/RCX/power

核对请求 corner×温度对应 SPEF/Liberty、报告四种路径类型、真正采用的 SDC、未约束端点和解析错误。没有 hold 不能写 hold=0。power_report 不存在与测得 total=0 不同；回退 synthesis 只能标 estimate。

### 宏/物理/LEC

macro show 检查 placements/file_placements/diverged，全部硬宏、真实实例、合法朝向/坐标；修独立输入再 macro import，不改生成 Tcl。DRC/LVS/LEC 分别是规则/连接/逻辑问题，不统一归因为密度；LEC 保留参考/待证网表 hash、失败报告和未证明语义。

## 3. 诊断能力边界

默认 CLI 读证据；无法暴露细节时只读检查 CLI 指出的日志、配置、原始 report 或分析 JSON，并说明能力缺口。不通过内部 API 运行工具，不修改证据，不直接 re-run 生成脚本以绕过状态管理。

记录退出码、原命令、版本、项目/workspace、首个失败点、关键日志、根因假设、最小修复和恢复范围。相同根因已重复且没有新证据时停止盲重试，汇报缺工具/不兼容/资源/接口限制。保持失败实验以供复现，不自动清理。
