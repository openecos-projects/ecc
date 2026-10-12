# Lit suites (CI contracts)

This tree holds **CI-side** lit suites and libraries. Product readiness remains
`ecc signoff inspect/export` and ordinary CLI/RPC unit tests under `test/cli`
and `test/runtime`.

## Suites

| Suite | Path | Runner |
|-------|------|--------|
| Signoff CSV gates (library) | `csv_gates/` | used by designs repo / e2e via `nix run .#signoff-lit` |
| Project scenarios | `project/` | CLI `--project` + RPC stdio Synthesis smoke |

Default CSV tables are **qor_metrics + checklist** only. `qor_summary` and
`flow_steps` remain available when a profile sets `tables:`. FileCheck
projection can be built from in-memory rows without extra CSV files.

Milestone (inputs → readiness PASS/WARN/MISS/ERROR + package archive, ICS55
fixture-first): item identities live in `chipcompiler.engine.signoff.catalog`.
Projection emits a `readiness:` line derived from checklist rows (no PDK).

## Project scenarios (`project/`)

Two lit cases share one FileCheck contract (`checks/status_success.check`):

1. **CLI** — `ecc run --project … --from/--to Synthesis` then `ecc status --project`
2. **RPC** — `ecc rpc serve --stdio` lifecycle via `test/rpc_check.py`, then the same status check

Drivers live under `nix/scripts/` (product scenarios, not PR-body glue):

- `prepare_gcd_project.sh`
- `run_project_scenario.sh --mode=cli|rpc` (shared prepare + status contract)
- `run_cli_project_scenario.sh` / `run_rpc_project_scenario.sh` (thin wrappers)
- `ci_project_lit.sh` (CI entry; installs Nix if needed; flake build-fail fallback only)

### Local / CI run

```bash
export CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/icsprout55-pdk
# OSS CAD / sizer env as for normal ecc run
bash nix/scripts/ci_project_lit.sh
# or:
nix run .#signoff-lit -- test/lit/project
```

Without `CHIPCOMPILER_ICS55_PDK_ROOT`, lit reports `UNSUPPORTED` (`REQUIRES: ics55-pdk`).

Unit smoke (no PDK):

```bash
uv run pytest test/test_signoff_csv_export.py test/engine/test_signoff_readiness.py -q
```

## Signoff CSV gates (`csv_gates/`)

See historical notes below. Gates against **real design workspaces** from the
PyInstaller e2e job; profiles/FileCheck files for packaged designs live in
[openecos-projects/ecc-ci-designs](https://github.com/openecos-projects/ecc-ci-designs).

```bash
ECC_FLOW_WORKSPACES=<workspaces> \
  nix run .#signoff-lit -- <ecc-ci-designs checkout>
```

Status: **v0 / trial** — CI contract, not product signoff truth.
