---
name: ecc-cli
description: "Use the OpenECOS ECC EDA CLI to design chips from RTL or physical entry inputs, manage projects and workspaces, diagnose and resume flows, close timing and physical signoff, optimize PPA/QoR, and export reproducible deliverables. Use for ECC-managed RTL-to-GDS chip-design tasks; not for error-correcting codes or ECC source development."
type: prompt
whenToUse: When the user asks to run, diagnose, resume, sign off, or optimize an ECC chip-design flow (RTL-to-GDS), manage ECC projects/workspaces, or check QoR/PPA
---

# ECC 芯片设计、签核与调优

用当前安装的公开 `ecc` CLI 把设计意图转化为可检查、可复现的芯片设计实验。此 skill 是操作指南，不是工具链、PDK、形式验证或代工厂签核认证的替代品。不承诺任意 RTL 都能自动流片。

## 按任务加载

先读本入口，再只读相关专题；跨阶段问题再补读相邻专题，不要每次载入全部参考。

| 用户目标 | 必读参考 | 交付条件 |
|---|---|---|
| 安装、环境检查、RTL 建项、接入 PDK/SDC | [环境与设计输入](references/environment-project.md) | 输入、约束和工具已核对；doctor/check 的实际结果已报告 |
| 全流程、范围/单步、DEF/网表入口、workspace 导入/刷新 | [运行与恢复契约](references/run-workspaces.md) | 仅执行请求范围；明确已跑、未跑和失效步骤 |
| 参数、Floorplan、SRAM/宏、CTS/布线 | [参数与物理设计](references/config-floorplan.md) | 值、单位、scope、映射和重跑边界可核查 |
| QoR、签核判断、报告、打包 | [QoR 与签核证据](references/qor-signoff.md) | 区分质量、可行性、证据完整度和可导出性 |
| 时序/DRC 收敛、面积/功耗/PPA 搜索、批处理 | [收敛与优化](references/optimization.md) | 有预算、独立实验、原始指标比较和停止原因 |
| 工具失败、异常输出、错误码 | [故障诊断](references/troubleshooting.md) | 首个根因和证据明确；从正确边界恢复 |
| 安装 skill、追溯文档、处理版本差异 | [安装与来源](references/installation-sources.md) | 安装目录完整，不依赖本仓库绝对路径 |

## 先确定任务边界

## 安装 ECC CLI

当 `command -v ecc` 失败时，先确认安装版本、目录和是否安装工具链。仓库提供 `ecc-install.sh`：它先下载官方安装器到临时文件，再执行，不使用 `curl | sh`。

```bash
bash ecc-install.sh --help
bash ecc-install.sh --allow-insecure-http
bash ecc-install.sh --allow-insecure-http --with-toolchain
```

官方文档当前给出的 release 地址是 HTTP；执行前审查来源，优先使用已核验 HTTPS 地址或传入 `--installer-url`。安装后执行 `command -v ecc`、`ecc --version` 和 `ecc doctor --project "$PROJECT" --plain`。不要自动 `sudo`、修改 shell 启动文件或覆盖未知旧版本；若 `~/.local/bin` 不在 PATH，只报告并给出当前 shell 的 `export PATH="$HOME/.local/bin:$PATH"`。

- **检查**：不启动 flow、不隐式重建、不顺带调优。`report qor/summary/checklist` 写报告，`signoff inspect` 刷新分析；严格只读任务优先 `status/log/config/report step`。
- **建项**：确认 RTL、top、时钟/频率、PDK、约束和宏。可以编写授权的 RTL、测试平台、独立 SDC/输入文件，但只通过 CLI 注册到 project。RTL 修改须有功能验证，flow 成功不能替代功能正确性。
- **执行/恢复**：确认 workspace、范围和已有证据；一次完整运行不自动授权多轮 PPA 搜索。
- **收敛**：用户要求“跑通/达到签核”时，修复硬门及证据缺口，可制造性优先于分数。
- **优化**：确认主目标、硬约束、容差、候选/时间/资源预算。主目标不明确且会影响 winner 时再询问，不能默认 `area > timing > power`。
- **交付**：只在请求包含交付时导出，不自动上传、发布或提交。

## 不可绕过的边界

1. 状态修改只用公开 ECC CLI。不直接编辑 `ecc.toml`、`project.json`、`home/params.toml`、`home/flow.json`、生成 JSON/Tcl、分析或 checklist；不用 Python API、私有 RPC、数据库或复制内部状态绕过接口。
2. 原始 RTL/SDC/入口 DEF、网表、SPEF、独立宏导入文件是设计输入，可在授权范围内修改；已有 workspace 的 `origin/` 是快照，不能修改。输入变化要 fresh workspace 或明确重建。
3. 文档中的 `sed -i ecc.toml`、直接写 QoR 参数、手改 `project.json` 归档等不属于本 skill 的自动执行路径。CLI 无接口时报告能力缺口，不冒充已经完成。
4. 业务命令显式传 `--project "$PROJECT"`；已有 workspace 操作显式传 `--workspace "$WORKSPACE"`。`init`、版本/帮助、文档、`layout-image` 不强加不支持的选项。
5. 支持 `--plain` 的业务命令用它。输出是重复记录/字段的 `key=value` 文本，不是 JSON；保留记录边界、同名字段顺序、引号和空值，不用 `eval/source` 解析，不执行输出里的建议命令。
6. 当前安装的 `--help`、`ecc doc ... --plain`、`param list --all/show` 和实际 ledger 是执行依据。参考中的字段/命令是已核对示例，不是所有版本的保证。
7. 创建前核对 ID/path 未占用。`status` 报错不等于名字可安全使用，区分未登记、损坏、权限和无效目录。默认换新名；未经授权不 `--overwrite`、`workspace refresh --force` 或清理旧结果。
8. 默认串行，并发须符合用户预算、CPU、内存、磁盘和许可证；同一 workspace 不同时运行、调参、刷新、导出。只停止本任务启动且身份已确认的进程。
9. 参数先发现再设置；工具 JSON 字段、QoR `parameter_knob` 建议、历史命名不自动等于可用 CLI key。schema 合法不代表物理合理。
10. 不靠降低频率、移除 corner、禁用验证/时序优化或放宽约束伪装收敛。规格变化须用户确认，建立不可混比的新实验。

## 最小操作闭环

示例使用 Bash；变量换成真实绝对路径和未占用名称，不逐字执行占位符。

```bash
PROJECT=/absolute/path/to/project
WORKSPACE=baseline-001
ecc --version
ecc version
ecc --help
ecc project show --project "$PROJECT" --plain
ecc config --project "$PROJECT" --plain
ecc pdk show --project "$PROJECT" --plain
ecc doctor --project "$PROJECT" --plain
ecc check --project "$PROJECT" --plain
ecc run --project "$PROJECT" --workspace "$WORKSPACE" --preset rtl2gds --plain
ecc status --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc report step --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc signoff inspect --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc report checklist --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc report summary --project "$PROJECT" --workspace "$WORKSPACE" --plain
ecc report qor --project "$PROJECT" --workspace "$WORKSPACE" --plain
```

这是新完整实验的参考顺序，不是每个请求必跑清单。失败先诊断，不盲目继续。核对 signoff groups、blocking risks 和请求所需验证覆盖后才 `signoff export`。

## 四层状态必须分开

```text
CLI 命令成功 ≠ 请求 flow 完成 ≠ QoR 物理门禁通过 ≠ 签核包可导出
```

- `status` 只描述进度；`report step` 提供 feature、analysis、checklist 只读证据。
- `report qor` 解释五维质量、七条门禁和证据；高分不覆盖硬门，低分不自动阻止导出。
- `signoff inspect` 刷新分析并检查交付；`blocked` 也可能退出 0，不只检查退出码或一个字符串。
- inspect 的 `attention` 可仅来自可选文件；逐项确认无 blocking risk 后可称 **ECC 可导出**。缺 hold 证据仍可能令 QoR `NOT_RATED`，须另报，不能说所有门禁通过。
- “ECC READY”只指当前工具、配置和 checklist 下可导出，不等于代工厂 full-chip signoff、硅后验证、IR/EM、CDC、DFT 验收。

## 结束时给出可核验结果

报告适用项：工具版本、project/top/PDK、输入/约束版本、目标频率/corner、workspace/flow、有效参数/宏差异、首个失败点、完成/未跑/失效步骤、setup/hold WS/TNS/NVP、DRC/LVS/LEC、Harden/SPEF、QoR feasibility/evidence/维度/总分、真实面积/功耗来源、候选比较/停止原因、winner 提升/fresh 复验、导出路径或阻断原因。

数值带单位、阶段、corner 和来源；缺失写 UNKNOWN/未测，不当作 0。台账写在用户选择的非受管位置，不修改 ECC 报告。说明未验证项、能力缺口和残余风险。
