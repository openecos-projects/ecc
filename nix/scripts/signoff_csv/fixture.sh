#!/usr/bin/env bash
# Deterministic workspace fixture for CI smoke tests.
# Usage: fixture.sh --workspace DIR
set -euo pipefail

usage() {
  echo "usage: $0 --workspace DIR" >&2
  exit 2
}

workspace=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      workspace="${2:-}"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done
[[ -n "${workspace}" ]] || usage

mkdir -p "$workspace"

write_json() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
  cat > "$path"
}

design=gcd

write_json "$workspace/home/flow.json" <<'JSON'
{
  "design": "gcd",
  "steps": [
    {"name": "Synthesis", "tool": "yosys", "state": "Success"},
    {"name": "postFloorplan", "tool": "ecc", "state": "Success"},
    {"name": "place", "tool": "dreamplace", "state": "Success"},
    {"name": "drc", "tool": "ecc", "state": "Success"},
    {"name": "lvs", "tool": "ecc", "state": "Success"},
    {"name": "sta", "tool": "ecc", "state": "Success"},
    {"name": "postRouteLec", "tool": "kepler_formal", "state": "Success"},
    {"name": "Harden", "tool": "ecc", "state": "Success"}
  ]
}
JSON

write_json "$workspace/Synthesis_yosys/analysis/qor_metrics.json" <<'JSON'
{
  "schema_version": 3,
  "metrics": [
    {"id": "synthesis_cell_area", "value": 4200.0, "unit": "", "source": {"kind": "analysis", "path": ""}}
  ]
}
JSON

write_json "$workspace/postFloorplan_ecc/analysis/qor_metrics.json" <<'JSON'
{
  "schema_version": 3,
  "metrics": [
    {"id": "die_area", "value": 40000.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "core_area", "value": 32000.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "core_utilization", "value": 0.62, "unit": "", "source": {"kind": "analysis", "path": ""}}
  ]
}
JSON

write_json "$workspace/drc_ecc/analysis/qor_metrics.json" <<'JSON'
{
  "schema_version": 3,
  "metrics": [
    {"id": "drc_count", "value": 0, "unit": "", "source": {"kind": "analysis", "path": ""}}
  ]
}
JSON

write_json "$workspace/drc_ecc/analysis/qor_summary.json" <<'JSON'
{
  "schema_version": 4,
  "quality_status": "pass",
  "gates": [
    {
      "id": "qor.drc.clean",
      "state": "pass",
      "title": "DRC clean",
      "metrics": [{"id": "drc_count", "actual": 0, "operator": "==", "expected": 0}]
    }
  ]
}
JSON

write_json "$workspace/sta_ecc/analysis/qor_metrics.json" <<'JSON'
{
  "schema_version": 3,
  "metrics": [
    {"id": "sta_setup_wns", "value": 1.2, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_setup_tns", "value": 0.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_setup_violation_count", "value": 0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_hold_wns", "value": 0.15, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_hold_tns", "value": 0.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_hold_violation_count", "value": 0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_frequency_mhz", "value": 100.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_corner_count", "value": 1, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_expected_corner_count", "value": 1, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_missing_corner_count", "value": 0, "unit": "", "source": {"kind": "analysis", "path": ""}}
  ]
}
JSON

write_json "$workspace/sta_ecc/feature/MAX_125/RCworst/qor_summary.json" <<'JSON'
{
  "summary": {
    "setup": {"wns": 1.2, "tns": 0.0, "nvp": 0, "frequency_mhz": 100.0},
    "hold": {"wns": 0.15, "tns": 0.0, "nvp": 0}
  }
}
JSON

write_json "$workspace/postRouteLec_kepler_formal/output/${design}_postRouteLec_result.json" <<'JSON'
{
  "status": "proven",
  "golden_verilog": "golden.v",
  "gate_verilog": "gate.v",
  "golden_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "gate_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
  "golden_size_bytes": 10,
  "gate_size_bytes": 20
}
JSON

write_json "$workspace/Harden_ecc/analysis/qor_metrics.json" <<'JSON'
{
  "schema_version": 3,
  "metrics": [
    {"id": "harden_artifact_missing_count", "value": 0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "die_area", "value": 40000.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "core_area", "value": 32000.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "core_utilization", "value": 0.62, "unit": "", "source": {"kind": "analysis", "path": ""}}
  ]
}
JSON

mkdir -p "$workspace/Harden_ecc/output"
for artifact in gds lef lib; do
  printf '%s' "$artifact" > "$workspace/Harden_ecc/output/${design}_Harden.${artifact}"
done
