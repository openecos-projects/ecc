# Signoff CSV gates

`csv_gates/` is the CI-side signoff gate library: it reads a real flow
workspace (`home/flow.json`, `home/checklist.json`, `*/analysis/qor_*.json`),
projects it to CSV tables plus a FileCheck-friendly text projection, evaluates
the gates declared in a profile YAML, and writes a `run_manifest.json`.

Entry point: `nix/scripts/export_signoff_csv.sh --workspace WS --out-dir DIR
--spec SPEC` (thin wrapper over `csv_gates.cli`).

Status: **v0 / trial** — this is a CI contract, not product signoff truth.
Product readiness is `ecc signoff inspect/export`.

## Where it runs

The gates run against **real design workspaces** produced by the
PyInstaller-bundle e2e flow (`e2e-packaged-flow` CI job). The lit suite,
the gate profile (`profiles/signoff.yml`), and the FileCheck gate files live
in [openecos-projects/ecc-ci-designs](https://github.com/openecos-projects/ecc-ci-designs);
this repo keeps only the library and the runner scripts.

## Local run

```bash
uv run pytest test/test_signoff_csv_export.py -q   # unit coverage incl. negative gates

ECC_FLOW_WORKSPACES=<workspaces> \
  bash nix/scripts/signoff_lit_nix.sh <ecc-ci-designs checkout>
```

## Profile schema (`version: 1`)

See `profiles/signoff.yml` in the designs repository. CSV columns are additive
within a major version; `run_manifest.json` changes bump
`MANIFEST_SCHEMA_VERSION`.
