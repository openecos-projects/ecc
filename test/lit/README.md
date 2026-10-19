# Lit suites (CI contracts)

This tree holds **CI-side** lit suites and libraries. Product readiness remains
`ecc signoff inspect/export` and ordinary CLI/RPC unit tests under `test/cli`
and `test/runtime`.

## Suites

| Suite | Path | Runner |
|-------|------|--------|
| Signoff CSV gates (library) | `csv_gates/` | used by designs repo / e2e via `nix run .#signoff-lit` |
| Project scenarios | `project/` | CLI `--project` + RPC stdio Synthesis smoke |

## Project scenarios (`project/`)

Two lit cases share one FileCheck contract (`checks/status_success.check`):

1. **CLI** — `ecc run --project … --from/--to Synthesis` then `ecc status --project`
2. **RPC** — `ecc rpc serve --stdio` lifecycle via `test/rpc_check.py`, then the same status check

Drivers live under `nix/scripts/`:

- `prepare_gcd_project.sh`
- `run_cli_project_scenario.sh`
- `run_rpc_project_scenario.sh`
- `ci_project_lit.sh` (CI entry; installs Nix if needed)

### Local / CI run

```bash
export CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/icsprout55-pdk
# OSS CAD / sizer env as for normal ecc run
bash nix/scripts/ci_project_lit.sh
# or:
nix run .#signoff-lit -- test/lit/project
```

Without `CHIPCOMPILER_ICS55_PDK_ROOT`, lit reports `UNSUPPORTED` (`REQUIRES: ics55-pdk`).

## Signoff CSV gates (`csv_gates/`)

See historical notes below. Gates against **real design workspaces** from the
PyInstaller e2e job; profiles/FileCheck files for packaged designs live in
[openecos-projects/ecc-ci-designs](https://github.com/openecos-projects/ecc-ci-designs).

```bash
ECC_FLOW_WORKSPACES=<workspaces> \
  nix run .#signoff-lit -- <ecc-ci-designs checkout>
```

Status: **v0 / trial** — CI contract, not product signoff truth.
