# Standalone signoff product CSV

This directory is intentionally independent of `chipcompiler`, CLI command
handlers, engine code, and tool wrappers. It reads only the artifacts an ECC
workspace already produces:

- `home/flow.json`
- `<step>/analysis/qor_metrics.json`
- `<step>/analysis/qor_summary.json`
- `sta_ecc/feature/<corner>/<rc_corner>/qor_summary.json`
- `postRouteLec_*/output/<design>_postRouteLec_result.json`
- `Harden_ecc/output/<design>_Harden.{gds,lef,lib}`

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

- CI runs `nix/scripts/signoff_csv/fixture.py` only; it does not run real EDA tools or real DRC/LVS/STA/LEC/Harden jobs.
- The STA check currently verifies row presence only; it does not enforce `WNS >= 0` or `TNS == 0`.
- The Harden check currently verifies presence only; it does not enforce `harden_artifact_missing_count == 0`.
- Failure paths (`present=false`, DRC gate fail, LEC not `proven`, negative WNS, Harden missing artifacts) are not covered by fixture tests.
- On fork PRs, the `pull_request` token is read-only, so the notification step cannot reliably post/update the PR comment.

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

`status` is `proven`, `incomplete`, or `missing`. A stale/missing result fails
the CI gate.

### `harden.csv`

`kind,metric,value,unit,source,present,sha256,bytes`

Includes Harden QoR metrics and the three final artifacts: `gds`, `lef`, `lib`.

### `area.csv`

`step,metric,value,unit,source,present`

Collects `synthesis_cell_area`, `die_area`, `core_area`, and `core_utilization`
from `Synthesis`, `postFloorplan`, and `Harden` outputs.

## CLI

```bash
PYTHONPATH="$PWD/nix/scripts" \
python3 -m signoff_csv.cli \
  --workspace /path/to/workspace \
  --out-dir /path/to/signoff_csv
```

The command writes one CSV per selected check and
`signoff_csv_manifest.json`. It returns non-zero only when a mandatory CSV is
missing or failed; `area` is report-only.
