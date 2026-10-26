# Lit suites (CI contracts)

CI-side lit libraries for signoff CSV gates. Product signoff assessment stays in
`chipcompiler.engine` (checklist / readiness / package), not CLI scenario suites.

## Signoff CSV gates (`csv_gates/`)

Reads a real flow workspace, projects CSV + FileCheck text, evaluates profile
gates, writes `run_manifest.json`. Entry: `nix/scripts/export-signoff-csv.sh`.

Default tables: **qor_metrics + checklist**. Projection may emit a `readiness:`
line via `classify_signoff_readiness` (same engine classifier).

Profiles / FileCheck for packaged designs live in
[openecos-projects/ecc-ci-designs](https://github.com/openecos-projects/ecc-ci-designs).

```bash
uv run pytest test/test_signoff_csv_export.py test/engine/test_signoff_readiness.py -q

ECC_FLOW_WORKSPACES=<workspaces> \
  nix run .#signoff-lit -- <ecc-ci-designs checkout>
```

Status: **v0 / trial** — CI contract, not product signoff truth.
