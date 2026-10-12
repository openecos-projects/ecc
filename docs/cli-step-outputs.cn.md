# 查询单步输出

使用已有命令显式查询 Engineering Snapshot 登记的 DEF 和 Verilog 输出：

```bash
ecc report step place --workspace <workspace> --section outputs
ecc report step sta --workspace <workspace> --section outputs --json
```

默认报告仍只显示 feature、analysis、checklist，保持既有行为。
`outputs` 不执行工具、不迁移 snapshot、不刷新工作区，也不扫描目录。
索引缺失或损坏时返回 unavailable，不生成新的索引。

- `exists`、`bytes`：查询时检查工作区内部文件，不信任缓存的 exists。
- `availability`：available、missing 或 outside_workspace。外部引用不访问文件系统。
- `validity`：未成功的 step 为 not_current；成功也只标记 unknown，文件存在和
  step 成功不足以证明 hash、corner 或输入一致性。
- 本版本仅查询 snapshot 已登记的 DEF/Verilog，不承诺完整 GDS、日志或报告清单。

`report qor --json` 当前仍返回报告生成摘要，且会生成报告文件；它不是只读的完整
metrics API。不要把该输出当作完整 QoR schema。
