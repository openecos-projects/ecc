# Signoff CSV gates (v0 / trial)

**Status: trial / v0.** Fixture lit + helpers under `test/lit/` (not product
`ecc signoff`). Do not call this the formal signoff check layer until the
[graduation bar](#graduation-bar) is met.

| Piece | Path |
|-------|------|
| Gate helpers | `test/lit/csv_gates/` |
| Entrypoints | `nix/scripts/export_signoff_csv.*`, `nix/scripts/signoff_lit.sh` |
| Fixture builder | `nix/scripts/materialize_signoff_workspace.sh` (jq) |
| This suite | `cases/`, `profiles/`, `lit.cfg.py` |

## Who is the source of truth

| Question | Answer |
|----------|--------|
| Harden package ready / blocked / exportable? | **`ecc signoff`** (product) |
| Did this commit’s workspace satisfy the CI profile? | **CSV gates** (CI contract) |

Layered, not dual truth: product readiness stays on `ecc signoff`;
`signoff.yml` FileCheck is a **CI contract** over exported metrics/checklist
rows. Projection (`metrics.check.txt`) is a **CI view only** — not a storage
format. Dashboards should consume **CSV tables + `run_manifest.json`** (compare
externally, e.g. csvkit); ecc does not ship run-vs-run diff APIs.

## Graduation bar

All six must hold before dropping the trial / v0 label:

1. **Failures are owned** — gate red blocks merge/release; the team agrees those reds are correct.
2. **Schema is stable** — profile `version`, CSV columns, `run_manifest.schema_version` follow the compat policy below.
3. **Coverage is enough** — positives + negatives; path to multi-design / multi-profile.
4. **Default path runs** — PR CI stably runs **fixture** lit; packaged/PDK paths stay separate jobs.
5. **Product semantics aligned** — table above stays true.
6. **Someone consumes outputs** — release check, dashboard, or baseline compare.

## Schema compat policy

| Artifact | Policy |
|----------|--------|
| Profile YAML `version` | Only `1` today; new major keeps v1 loadable or documents a hard break here. |
| CSV columns | Additive OK within a major; rename/remove → bump profile `version`. |
| `run_manifest.json` | Additive OK; remove/rename → bump `MANIFEST_SCHEMA_VERSION`. |
| Projection text | **Not** a compatibility surface. |

## How to run

```bash
# unit (gate/spec) — NOTE: remove it next version (lit owns the contract)
uv run pytest test/test_signoff_csv_export.py -q

# lit — same path as CI (needs Nix on PATH, then nixpkgs lit + LLVM 23 FileCheck)
export ECC_REPO_ROOT=$PWD
export PYTHON=$PWD/.venv/bin/python
bash nix/scripts/signoff_lit_nix.sh

# or: nix flake app (lit + FileCheck wrappers)
nix run .#signoff-lit

# or inplace when lit + FileCheck are already on PATH
export LIT=lit FILECHECK=FileCheck
bash nix/scripts/signoff_lit.sh
```

Default PR CI: `DeterminateSystems/nix-installer-action` (`init: none`, no sudo)
on manylinux → `nix/scripts/signoff_lit_nix.sh` (fixture lit only, no ics55 rtl2gds).
No Nix store cache action (optional; not required for lit). Optional packaged path:
`ECC_TEST_WORKSPACE` + `REQUIRES: packaged-workspace`.

Packaged rtl2gds driver (optional, not default PR CI): `nix/scripts/run_design.sh`
(`nix run .#run-design`), default `--design ics55-gcd`; more IP presets land
here when fixtures exist (`--ecc-toml` / `--rtl` for ad-hoc designs).

## Environment

| Variable | Role |
|----------|------|
| `ECC_REPO_ROOT` | Repo root (PYTHONPATH + script defaults) |
| `PYTHON` | Interpreter for export (else `.venv/bin/python`) |
| `ECC_EXPORT_SIGNOFF_CSV` / `ECC_MATERIALIZE_READY` | Override script paths |
| `ECC_SIGNOFF_CSV_SPEC` | Override profile YAML |
| `ECC_SIGNOFF_RUN_ID` | Stable run id in manifest |
| `ECC_TEST_WORKSPACE` | Enables packaged-workspace feature |
| `FILECHECK` / `LIT` | `FileCheck` (llvmPackages_23.libllvm) / `lit` (nixpkgs) |
| `NIXPKGS_REF` | nixpkgs flake ref for CI lit shell (pinned LLVM 23) |

## Profile schema (`version: 1`)

See `profiles/signoff.yml`.
