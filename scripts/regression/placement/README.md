# Placement regression

这个入口从已准备好的 benchmark batch 读取 case 清单，运行 placement，
再用同一份最终合法化 DEF 做 OpenROAD placement RC + STA 和 GR50 + STA。
默认最多 6 个 case 并发；每个 case 的 placement 线程数由 profile 决定。

在 ECC 仓库根目录使用 Python 3.11+。按 `docs/development.md` 准备 Nix/uv
环境后，用 `.venv/bin/python` 调用入口；本机的系统 `python3` 可能仍是 3.10。

## 准备与运行

本机已验证的 13-case 输入及 native runtime 来源如下。其他环境应替换这些路径。
`batch_dir` 必须是一个尚不存在的目录；每个参数组合使用独立目录。

```bash
source_batch=/nfs/share/home/zhaoxueyan/dataset_cx55_ecc_workspace/ecc-placement13-ordinary-fixed500-smooth2-rho02-alpha1-20261010.7hrsfmqo
runtime_batch=/nfs/share/home/zhaoxueyan/dataset_cx55_ecc_workspace/ecc-pr-publication-20261010.bizigyu_/prepare-smoke-final
batch_dir=/nfs/share/home/zhaoxueyan/dataset_cx55_ecc_workspace/ecc-placement-next-experiment
openroad_bin=/home/zhaoxueyan/code/OpenROAD/build/bin/openroad

.venv/bin/python -m scripts.regression.placement prepare \
  --source-batch "$source_batch" \
  --runtime-from "$runtime_batch" \
  --profile test/regression/ics55/placement_fixed500_smooth2.json \
  --openroad "$openroad_bin" \
  --batch "$batch_dir"

.venv/bin/python -m scripts.regression.placement run \
  --batch "$batch_dir" --jobs 6
```

长任务可以把 `run` 命令放在 tmux 中，并将 stdout/stderr 保存到 batch 的
`batch.log`。先测试一个 case 时，在 `prepare` 中加 `--cases BM64`，然后用
`run --jobs 1`。也支持 `--cases BM64 PPU` 这样的子集。

## 后续参数实验

复制并修改 `test/regression/ics55/placement_fixed500_smooth2.json`，再将新文件
传给 `--profile`。策略来自所选 JSON；报告和校验不会写死 sizing 轮数、
fixed 权重数值、GP 平衡比例、growth factor 或 hard/smooth 模式。
这份初始 preset 是 ordinary、direct_loss、S10B0、fixed 500/5/1/1、
GP ratio 0.2、smooth tau 2 ps、padding 200、density 0.4。

目前这个入口要求 `flow_kind=placement`、`timing_opt_enabled=1`，并使用
timing_opt 的 terminal 报告检查最终实体化和合法化。窗口没有触发时会记录
零个窗口；不能把 enabled 参数当作窗口已经执行的证据。

`prepare` 会复制指定来源的已验证 native runtime，核对 native 文件哈希，
并覆盖为当前 ECC 和 DreamPlace checkout 的 Python 源码。生成的 runner、
runtime、profile、DEF/netlist/SDC 和 LEF/Liberty 都保存到新 batch。
因此改 Python 后需要重新 prepare；涉及 native API 的改动应先构建并验证
对应的 runtime，再通过 `--runtime-from` 使用它。来源 runtime 需要包含
`runtime/python-nix` 和已验证的 `run_python.sh`。
当前 timing 导出要求 schema v2；上面的旧输入 batch 不能直接用作原生 runtime
来源。只有局部 Python 源码和外部 native 路径的诊断目录也不满足完整 runtime 契约。

输入 batch 需要 `cases_manifest.json` 和各 case 的 ECC project manifest。
准备时读取 project 最后登记 workspace 的 `home/engineering-snapshot.json`，
保留其基础参数，再应用本次 profile；不会重新执行 preplace。

## 状态、汇总与校验

```bash
.venv/bin/python -m scripts.regression.placement status --batch "$batch_dir"
.venv/bin/python -m scripts.regression.placement collect --batch "$batch_dir"
.venv/bin/python -m scripts.regression.placement verify --batch "$batch_dir"
```

- `status`：逐 case 的状态、所在阶段和最近日志中的迭代号。
- `collect`：生成 `results.md`、`results.csv`、`results.json`；未完成指标留空。
- `verify`：独立校验输入/runtime/PDK/profile/runner 哈希、实际生效参数、传播设置、窗口权重、
  GP 系数恢复、合法化、TRACKS/GCELLGRID、外部评测的 terminal marker 和退出码。
- `run`：每个 case 在独立目录启动进程，失败后记录具体阶段并继续其他 case；
  启动前校验冻结文件，全部成功后自动执行 `verify`。流程或最终校验失败，
  `batch.exit` 都会非零。

外部 evaluator 使用本套 ICS55 TT Liberty、ideal clocks、4 个线程。
Placement RC 固定 MET2；GR 使用 MET2–MET5、容量调整 0.5、50 次拥塞迭代，
跳过时钟 net 和超过 100 个终端的 net。两个 evaluator 都不执行 repair，
并检查实例、坐标和连接关系没有被改变。它们的 Tcl 文件也会被冻结并核对哈希。

主要代码入口：`prepare.py` 管输入/runtime/项目准备，`run_case.py` 管单 case
流程，`runner.py` 管并发，`external.py` 和两份 Tcl 管外部评测，
`artifacts.py`/`verify.py` 管证据校验，`reports.py` 管表格和状态。
