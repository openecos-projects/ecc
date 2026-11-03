# Standalone signoff product CSV

This directory is intentionally independent of `chipcompiler`, CLI command
handlers, engine code, and tool wrappers. It reads only the artifacts an ECC
workspace already produces:

- `home/params.toml`
- `home/flow.json`
- `<step>/analysis/qor_metrics.json`
- `<step>/analysis/qor_summary.json`
- `sta_ecc/feature/<corner>/<rc_corner>/qor_summary.json`
- `postRouteLec_<engine>/output/<design>_postRouteLec_result.json`
- `Harden_ecc/output/<design>_Harden.{gds,lef,lib}`
- the golden/gate netlists referenced by the selected LEC result

The collector is implemented in shell (`export.sh`) with `jq`; the
CI-only deterministic workspace fixture is `nix/scripts/signoff-csv-fixture.sh`
and is exposed as the `.#signoff-csv-fixture` flake package.

## Exported views

| Check | CSV | Gate |
| --- | --- | --- |
| `sta` | `sta.csv` | mandatory |
| `drc` | `drc.csv` | mandatory |
| `lec` | `lec.csv` | mandatory |
| `harden` | `harden.csv` | mandatory |
| `area` | `area.csv` | report |

## Scope and limitations

This is a collector skeleton, not a signoff gate:

- CI runs `nix/scripts/signoff-csv-fixture.sh` only; it does not run real EDA tools or real DRC/LVS/STA/LEC/Harden jobs.
- The STA check currently verifies row presence only; it does not enforce `WNS >= 0` or `TNS == 0`.
- The DRC check requires both `drc_count` presence and `qor.drc.clean == pass`.
- The Harden check currently verifies presence only; it does not enforce `harden_artifact_missing_count == 0`.
- Failure paths (`present=false`, DRC gate fail, LEC missing/stale/cross-engine, Harden missing artifact) are covered by `.github/scripts/signoff-csv-test.sh`; negative WNS/TNS and `harden_artifact_missing_count > 0` thresholds are still not enforced.
- LEC honors the flow ledger: an absent `postRouteLec` step is `skipped` (not required); a present non-`Success` step fails without reading stale residue. Engine selection is strict.
- The CI job writes the report to its GitHub Actions job summary and uploads the CSV products as the
  `ecc-signoff-csv` artifact. The summary includes area metrics, the DRC count, and setup/hold WNS/TNS,
  and links to the previous successful run for the same source branch when one exists. No PR comment token
  or follow-up notification workflow is required.

The `Signoff CSV collector` check is therefore not a substitute for reviewing the active PDK, rule deck, STA signoff criteria, or repository branch-protection required checks.

## Schema

### `sta.csv`

`kind,corner,rc_corner,metric,value,unit,source,present`

`kind` is `qor_metrics` or `corner_summary`. Step metrics use the canonical
STA QoR metric ids; corner rows use `setup_wns`, `setup_tns`, `setup_nvp`,
`setup_frequency_mhz`, `hold_wns`, `hold_tns`, and `hold_nvp`.

### `drc.csv`

`kind,metric,value,unit,gate,gate_state,source,present`

Currently exports `drc_count` and the `qor.drc.clean` gate state.

### `lec.csv`

`status,golden_verilog,golden_sha256,golden_size_bytes,gate_verilog,gate_sha256,gate_size_bytes,source,present`

`status` is `proven`, `incomplete`, `stale`, `missing`, or `skipped`.
`skipped` is emitted when the flow ledger has no `postRouteLec` step and
passes the gate as not required. The collector
re-verifies the recorded `*_sha256` and `*_size_bytes` against the referenced
netlist files; a missing or changed netlist is reported as `stale`, and only
`proven` passes the gate.

### `harden.csv`

`kind,metric,value,unit,source,present,sha256,bytes`

Includes Harden QoR metrics and the three final artifacts: `gds`, `lef`, `lib`.

### `area.csv`

`step,metric,value,unit,source,present`

Collects `synthesis_cell_area`, `die_area`, `core_area`, and `core_utilization`
from `Synthesis`, `postFloorplan`, and `Harden` outputs.

## Fixture

```bash
nix run .#signoff-csv-fixture -- --workspace /tmp/signoff-workspace
```

Negative-path coverage lives in `.github/scripts/signoff-csv-test.sh` and runs in CI.

## CLI

```bash
bash nix/scripts/signoff_csv/export.sh \
  --workspace /path/to/workspace \
  --out-dir /path/to/signoff_csv
```

The command writes one CSV per selected check and
`signoff_csv_manifest.json`. It returns non-zero only when a mandatory CSV is
missing or failed; `area` is report-only.
