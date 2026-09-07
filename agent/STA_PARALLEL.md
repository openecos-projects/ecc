# Controlled Candidate STA Parallelism

Only Agent candidate workspaces (`.agent/candidates/<id>`) use this scheduler.
Ordinary flows and Harden retain their existing execution path. No corners,
reports, timing constraints, power calculations, or metric aggregation rules
are removed. All implementation changes are owned by `ecc/agent`.

## Configuration

Set `ECOS_AGENT_STA_WORKERS` in the environment that launches the Agent/RPC:

- `1`: original serial runner, also the non-Linux default.
- `2`: Linux default, two independent corner processes.
- `4`: four independent corner processes, with higher memory consumption.

Other values fail validation. Parallel execution requires Linux. Restart an
already-running Agent/RPC after changing its launch environment.

Each corner uses a fresh spawned native process, an identical database snapshot,
and isolated temporary directories. The existing ECC runner still validates
inputs, enumerates all configured corners, aggregates metrics, and runs checks.
Artifacts are published only after all corner jobs succeed; normal failures
clear stale corner/aggregate outputs and reap remaining workers. Cancellation
is checked while jobs run. Linux parent-death signals kill workers if the RPC
parent is terminated without Python cleanup. Forced parent termination can
leave temporary directories; it does not guarantee filesystem cleanup.

Per-corner logs remain in `sta_ecc/log/sta-corner-<index>.log`. Agent STA memory
tracking includes descendants, retaining the existing increase-from-start
metric convention. The benchmark instead reports absolute sampled process-tree
RSS; shared resident pages may be counted more than once.

## GCD Measurement

Measured on 2026-09-07, Linux x86_64, AMD EPYC 9654 (384 logical CPUs), Python
3.11.14, installed `ecc=0.1.0a11`, `ecc-tools-bin=0.1.0a12`. Two runs per
configuration, serial/2/4 order repeated, on separate copies of one routed
gcd/ICS55 workspace. Cache state and machine load were not controlled.

| Workers | STA median (s) | STA speedup | Harden median (s) | Maximum sampled tree RSS (MiB) |
| --- | ---: | ---: | ---: | ---: |
| 1 | 157.62 | 1.00x | 11.96 | 1367.00 |
| 2 | 95.76 | 1.65x | 11.74 | 2883.39 |
| 4 | 54.58 | 2.89x | 11.87 | 5555.70 |

All six runs produced 13 timing summaries and 13 power summaries, with zero
missing configured corners. Per-corner timing/power JSON, aggregate STA/Harden
metrics, and checklist states matched the serial reference. Float comparison
uses absolute/relative tolerance `1e-9`; integer counts and key sets are exact.
Runtime and memory metrics are excluded from equivalence comparisons.

The source workspace inventory was unchanged. Raw results and individual run
logs are in `/tmp/ecos-sta-parallel-gcd-20260907-v2`; these temporary artifacts
are not committed. Reproduce from the ECC repository with a new output path:

```bash
./.venv/bin/python -m agent.sta_benchmark \
  --source /tmp/ecos-agent-gcd-7knob-20260906-v5/gcd-gap-4c403cfe-v12/baseline-1/workspace \
  --output /tmp/ecos-sta-parallel-gcd-reproduce \
  --workers 1 2 4 --repeats 2
```

The benchmark records source hashes, implementation hashes, package/runtime
metadata, per-run metrics and logs. The initial six-run measurement predates
automatic environment metadata and the parent-death guard; its environment is
recorded above. A further guarded 2-worker native STA/Harden run completed in
95.90/12.06 seconds and matched the serial metrics; evidence is under
`/tmp/ecos-sta-parallel-guard-20260907/.agent/candidates/guard-w2`.
External PDK/library contents are not included in the workspace
inventory. No seed is added and upstream placement/routing is not rerun.

## Acceptance Limits

This verifies STA/Harden numerical equivalence and scheduling speed, not a new
floorplan-to-Harden optimization episode, GUI/RPC end-to-end acceptance, or
signoff. The baseline has DRC=4. Both serial and parallel runs have the same
blocked `report.sta.timing_reports` checklist item: the checker expects
`timing_max.rpt`, while native output contains `timing_max_<path-type>.rpt`.
That existing report/checker mismatch is not changed or hidden here.

Packaged/frozen execution and release builds have not been validated. Corner
reduction and native Liberty/model reuse are intentionally not implemented.

Validation commands (from `ecc/`):

```bash
./.venv/bin/python -m pytest -q agent/test -p no:cacheprovider
./.venv/bin/python -m pytest -q test/tools/ecc -p no:cacheprovider
./.venv/bin/ruff check agent/sta_parallel.py agent/sta_benchmark.py agent/engine.py agent/tools.py agent/test/test_sta_parallel.py agent/test/test_sta_benchmark.py agent/test/test_tools.py
git diff --check
```

Results: 270 Agent tests and 119 ECC tool tests passed; Ruff and whitespace
checks passed. The Agent suite includes concurrent, unrelated floorplan tests
present in the working tree. Parent-termination tests exercise both SIGTERM
and SIGKILL, including actual worker death and reaping by an isolated subreaper.
