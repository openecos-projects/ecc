# 安装、来源与能力边界

此参考同时用于维护与安装检查；正常芯片操作不要求本仓库存在。

## 1. 可安装结构

源入口为 ECC 仓库的 `chipcompiler/skill/SKILL.md`。安装脚本一起安装入口、references/ 和 agents/openai.yaml，不能只复制入口；不需要 ECOS Studio 父仓库。

从 ECC 仓库根目录运行：

```bash
bash chipcompiler/skill/install-ecc-skill.sh
```

默认目标为 `$HOME/.agents/skills/ecc-cli`。已有同名目录会拒绝；审查后显式替换：

```bash
bash chipcompiler/skill/install-ecc-skill.sh --replace
```

替换前将完整旧目录保存为同级 tar.gz 备份并打印路径，归档成功才替换目录；备份不是可发现的 skill 目录，避免加载两个同名版本。自定义安装目标用于本地验证或已确认的旧版 Codex 搜索位置：

```bash
bash chipcompiler/skill/install-ecc-skill.sh /absolute/skills/ecc-cli
```

部分现有部署把 skills 放在 `$CODEX_HOME/skills` 或 `$HOME/.codex/skills`；先核对该 Codex 实例实际搜索位置，不假定 CODEX_HOME 自动改变当前默认路径。避免多个搜索根中安装不同内容但同名 ecc-cli；先审查旧副本，再按实例要求更新。脚本不自动修改它们。

```text
ecc-cli/
├── SKILL.md
├── agents/openai.yaml
└── references/
    ├── environment-project.md
    ├── run-workspaces.md
    ├── config-floorplan.md
    ├── qor-signoff.md
    ├── optimization.md
    ├── troubleshooting.md
    └── installation-sources.md
```

新开 Codex 会话/按实例要求刷新发现，使用 `$ecc-cli` 请求“先检查指定 project 的环境、配置与 workspace，不运行 flow”。应能加载参考并通过真实 ecc --help/CLI 工作，不应要求 Studio checkout、未配置 MCP、私有 RPC 或 Python 包导入。skill 不自动安装 ECC/PDK。

Codex 官方 skill 结构/搜索位置参考为 `https://developers.openai.com/codex/skills/`；版本变化时重新核对。安装结构验证只证明文件/frontmatter/引用正确，不证明已完成真实芯片设计或物理调优。

## 2. 文档覆盖表

基于 `chipcompiler/docs/` 全部 10 份文档（5 对中英文），不是把完整手册复制进 prompt。源 checkout 的 ECC commit 为 `4264418faad0c5f53f3f66329094492adb53fcb1`，文档自述基线为 v0.1.0-alpha.12；安装后的工具可能不同。

| 源文档（相对 ECC 仓库根） | 采纳能力/专题 |
|---|---|
| chipcompiler/docs/ecc-user-guide.cn.md | 全公开命令、plain、作用域、selector、import/refresh、report/signoff |
| chipcompiler/docs/ecc-user-guide.en.md | 对照步骤词表、入口/外部路径、reconcile、CLI 契约 |
| chipcompiler/docs/ecc-config-ref.cn.md | 参数来源/单位/映射、全部物理阶段、SDC/Sizer/RCX/STA |
| chipcompiler/docs/ecc-config-ref.en.md | 对照模板与有效默认、GPUGR、角落/配置受保护路径 |
| chipcompiler/docs/ecc-tutorial.cn.md | 环境部署、RTL/SDC 建项、完整链路、复跑/签核/宏、FAQ |
| chipcompiler/docs/ecc-tutorial.en.md | 对照新范围入口、refresh/preflight、实测示例边界 |
| chipcompiler/docs/ecc-qor-ref.cn.md | V3五维/七门/证据、profile、指标目录、诊断/JSON语义 |
| chipcompiler/docs/ecc-qor-ref.en.md | 对照 missing/UNKNOWN/compatibility、评分迁移与限制 |
| chipcompiler/docs/floorplan-flow.cn.md | 三阶段规划、宏交接、恢复边界 |
| chipcompiler/docs/floorplan-flow.en.md | 对照 Tcl格式/单位、auto/manual、无 GUI暂停协议 |

安装后不要求这些源路径存在。CLI 带 `ecc doc ug/config/tutorial --lang cn|en --plain`；没有在这组文档中承诺 `ecc doc qor/floorplan` 主题，不虚构。此 skill 的专题保存操作决策；需要未收录精确字段时先查当前 CLI/bundled docs，仍无依据则说明未知。

## 3. 已知差异和未暴露能力

- **LEC skip 策略**：文档通过 flow.skip_steps=[] 启用综合级 LEC，默认跳过；project set 的公开字段列表未包含此 key。不能虚构 `ecc project set flow.skip_steps '[]'`，也不用 sed 修改。若现有项目已启用，正常运行并核对 proof；用户要求启用但版本无接口时说明需要工具维护者/用户预配置，任务不能谎报完成。
- **LEC engine/顺序**：配置参考保留 Yosys、LVS→postRouteLec→DRC 的旧描述；user guide/tutorial 与当前 builder 为 LVS→DRC→postRouteLec，且 engine 可随配置/版本变化。从实际 ledger、tool、log、证明结果读取，不按目录后缀推断引擎。不私改 flow.lec_engine。
- **QoR profile/预算**：qor_profile/qor_power_budget_w 文档可由内部 params.toml 编辑，但当前不在审核 CLI 表。遵守 CLI-only，报告不能自动配置。用户目标可在独立台账做原始 PPA 排名，不能冒充 ECC profile 已改变。
- **QoR 干预名**：例如 route.dr_search_depth 未在当前 route schema 暴露；parameter_knob 是建议，不是接口保证。
- **DreamPlace 原始覆盖**：文档提 params.dreamplace，但 CLI 使用审核 place.*；未暴露字段不写 TOML 绕过。
- **归档/clone/promote/cancel**：不假定有公开命令。归档文档的手改 manifest 不执行；promote 用 param/macro逐项、fresh复验；cancel仅管理自己确认的进程，不调用私有 RPC。
- **hold 可选**：export 可选报告与 QoR mandatory hold gate 不同；可导出但 QoR未知是可解释结果，不制造缺失指标。
- **syn_sta 名称**：当前只有综合，不是综合+最终STA；性能筛选必须标阶段。
- **真实流片边界**：IR/EM、CDC/DFT、完整功能验证、代工厂签核、封装/芯片级集成不由这些文档的 CLI 自动保证，超出需求时单独定义工具与验收。

版本升级时重新采集 help、param schema、flow 和报告契约。新增公开接口后才替换能力缺口，不把修改版本号当成验证。
