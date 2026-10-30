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
