# Signoff testing and CI

**signoff** is not a test framework. It is **readiness inspection + package export**:
confirm the design meets the delivery contract, then produce a traceable evidence archive.

Product CLI: `ecc signoff inspect` / `ecc signoff export`.

## Layers

| Layer | Role | How |
|-------|------|-----|
| Product | Ready / attention / blocked; export only when not blocked | `ecc signoff` |
| White-box | Collector, checklist predicates, export edges | pytest (below) |
| Black-box | Optional packaged smoke (local/manual) | `ci-run-ics55-gcd` + signoff CSV sh |
| Display | Human/dashboard dumps | `ecc report` — not a second gate |

Hard CI failure follows the product: **only `signoff export` is non-zero when blocked**
(`signoff_incomplete`). `inspect` stays advisory (exit 0) so artifacts can still record
the review.

Out of scope for this plan: `ecc test` CLI, new lit suites, performance as a blocked
gate, changing `report` command ownership.

## Decision vocabulary

Product rollup:

| Status | Meaning | Export |
|--------|---------|--------|
| `ready` | No blocking items | Allowed |
| `attention` | Optional / warning only | Allowed |
| `blocked` | Required evidence or gates failed | Rejected |

Item-level states include `pass` / `failed` / `unavailable` (and optional `warning`).
Interpretive labels used in docs/tests map as:

| Label | Typical signoff meaning |
|-------|-------------------------|
| PASS | Rollup `ready`; item `pass` |
| WARN | Rollup `attention`; optional miss / warning |
| MISS | Missing required evidence → often `blocked` |
| ERROR | Failed gate / proof → often `blocked` |

MISS vs ERROR are explanations; the product gate remains **blocked or not**.

## White-box pytest (keep)

| File | Covers |
|------|--------|
| [`test/test_signoff_package.py`](../test/test_signoff_package.py) | Collection, required members, LEC proven/stale, path escape |
| [`test/tools/ecc/test_signoff_checklist.py`](../test/tools/ecc/test_signoff_checklist.py) | Quality gates, file presence states |
| [`test/runtime/test_signoff_export.py`](../test/runtime/test_signoff_export.py) | `inspect` / `export` runtime API |

These stay on the default unit path. Do not migrate them to CLI.

## Black-box CI

Default PR CI matches **main**: build the PyInstaller bundle only
(`build-pyinstaller`). It does **not** run real ics55 rtl2gds or signoff export.

Signoff contract stays on **white-box pytest** (fixture workspaces). Optional local /
manual packaged smoke (not required for green CI):

```text
build ECC_BIN
→ nix run .#ci-run-ics55-gcd          # golden input: ics55 × gcd
→ ECC_BIN signoff inspect --plain
→ nix run .#ci-export-signoff-csv
→ ECC_BIN signoff export …
→ nix run .#ci-check-signoff-csv
```

CSV shell entrypoints (clear ops only; Python impl under the hood for JSON tabularize):

| Script | Role |
|--------|------|
| [`.github/scripts/export_signoff_csv.sh`](../.github/scripts/export_signoff_csv.sh) | Export tables + projection |
| [`.github/scripts/check_signoff_csv.sh`](../.github/scripts/check_signoff_csv.sh) | Consume/verify with FileCheck |
| [`.github/scripts/_export_signoff_csv.py`](../.github/scripts/_export_signoff_csv.py) | Impl for export (not CI entry) |

- **Package shape first**: export tree + `manifest.json` / `summary.json` + checklist groups;
  white-box tests own the contract.
- **Then parameters**: single golden project via [`.github/scripts/ci_run_ics55_gcd.py`](../.github/scripts/ci_run_ics55_gcd.py);
  overrides only through existing `--set` / `ecc param` / `[flow]`.
- **Performance later**: optional outer `time` / monitors; never blocked by signoff.

Nix ([`nix/signoff-tools.nix`](../nix/signoff-tools.nix)) wraps the shell scripts and pins `filecheck`.


### Local smoke (optional)

```bash
export ECC_BIN=/path/to/dist/ecc-packaged/ecc
nix run .#ci-run-ics55-gcd -- --ecc "$ECC_BIN" --project-dir … --pdk-root …
"$ECC_BIN" signoff inspect --project … --workspace default --plain
nix run .#ci-export-signoff-csv -- --workspace …/default --out-dir …
"$ECC_BIN" signoff export --project … --workspace default -o signoff.tar.gz --plain
nix run .#ci-check-signoff-csv -- \
  --input …/reports/metrics.check.txt \
  --check test/support/csv_profiles/ics55_gcd.check
```

## Related product docs

See [development.md](development.md) (“Extending signoff” / Signoff section) for CLI and
engine layout.
