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

mkdir -p "$workspace/home"
cat > "$workspace/home/params.toml" <<'TOML'
schema_version = 2

[design]
name = "gcd"
top = "gcd"

[pdk]
name = "sky130A"
TOML

write_json "$workspace/home/flow.json" <<'JSON'
{
  "schema_version": 2,
  "steps": [
    {"name": "synthesis", "tool": "yosys", "directory": "synthesis_yosys", "state": "Success"},
    {"name": "post_floorplan", "tool": "ecc", "directory": "post_floorplan_ecc", "state": "Success"},
    {"name": "placement", "tool": "dreamplace", "directory": "placement_dreamplace", "state": "Success"},
    {"name": "drc", "tool": "ecc", "directory": "drc_ecc", "state": "Success"},
    {"name": "lvs", "tool": "ecc", "directory": "lvs_ecc", "state": "Success"},
    {"name": "sta", "tool": "ecc", "directory": "sta_ecc", "state": "Success"},
    {"name": "post_route_lec", "tool": "kepler_formal", "directory": "post_route_lec_kepler_formal", "state": "Success"},
    {"name": "harden", "tool": "ecc", "directory": "harden_ecc", "state": "Success"}
  ]
}
JSON

write_json "$workspace/synthesis_yosys/analysis/qor_metrics.json" <<'JSON'
{
  "schema_version": 3,
  "metrics": [
    {"id": "synthesis_cell_area", "value": 4200.0, "unit": "", "source": {"kind": "analysis", "path": ""}}
  ]
}
JSON

write_json "$workspace/post_floorplan_ecc/analysis/qor_metrics.json" <<'JSON'
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
  "design": "gcd",
  "metrics": [
    {"id": "sta_setup_wns", "value": 1.2, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_setup_tns", "value": 0.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_setup_violation_count", "value": 0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_hold_wns", "value": 0.15, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_hold_tns", "value": 0.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_hold_violation_count", "value": 0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_frequency_mhz", "value": 195.5, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_target_frequency_mhz", "value": 200.0, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_corner_count", "value": 1, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_expected_corner_count", "value": 1, "unit": "", "source": {"kind": "analysis", "path": ""}},
    {"id": "sta_missing_corner_count", "value": 0, "unit": "", "source": {"kind": "analysis", "path": ""}}
  ]
}
JSON

write_json "$workspace/sta_ecc/feature/MAX_125/RCworst/qor_summary.json" <<'JSON'
{
  "summary": {
    "setup": {"wns": 1.2, "tns": 0.0, "nvp": 0, "frequency_mhz": 195.5},
    "hold": {"wns": 0.15, "tns": 0.0, "nvp": 0}
  }
}
JSON

write_json "$workspace/home/frequency.json" <<'JSON'
{
  "schema_version": 1,
  "kind": "frequency_run_results",
  "design": "gcd",
  "base_id": "fixture-gcd-v1",
  "evidence_mode": "fixture",
  "params": {
    "pll_refclk_mhz": "20",
    "pll_bypass": false,
    "frequency_min_mhz": "150",
    "frequency_max_mhz": "200",
    "guardband_frequency_ratio": "0.05"
  },
  "runs": [
    {"candidate_mhz": "200", "phase": "verification", "run_id": "v200", "base_id": "fixture-gcd-v1", "status": "fail", "coverage_status": "pass"},
    {"candidate_mhz": "195", "phase": "verification", "run_id": "v195", "base_id": "fixture-gcd-v1", "status": "fail", "coverage_status": "pass"},
    {"candidate_mhz": "190", "phase": "verification", "run_id": "v190", "base_id": "fixture-gcd-v1", "status": "pass", "coverage_status": "pass"},
    {"candidate_mhz": "180", "phase": "guardband", "run_id": "g180", "base_id": "fixture-gcd-v1", "status": "pass", "coverage_status": "pass"}
  ]
}
JSON

printf 'module gcd;\nendmodule\n' > "$workspace/golden.v"
printf 'module gcd_gate;\nendmodule\n' > "$workspace/gate.v"
golden_sha="$(sha256sum "$workspace/golden.v" | awk '{print $1}')"
gate_sha="$(sha256sum "$workspace/gate.v" | awk '{print $1}')"
golden_size="$(stat -c %s "$workspace/golden.v")"
gate_size="$(stat -c %s "$workspace/gate.v")"

write_json "$workspace/post_route_lec_kepler_formal/output/${design}_post_route_lec_result.json" <<JSON
{
  "status": "proven",
  "golden_verilog": "golden.v",
  "gate_verilog": "gate.v",
  "golden_sha256": "${golden_sha}",
  "gate_sha256": "${gate_sha}",
  "golden_size_bytes": ${golden_size},
  "gate_size_bytes": ${gate_size}
}
JSON

write_json "$workspace/harden_ecc/analysis/qor_metrics.json" <<'JSON'
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

mkdir -p "$workspace/harden_ecc/output"
for artifact in gds lef lib; do
  printf '%s' "$artifact" > "$workspace/harden_ecc/output/${design}_harden.${artifact}"
done
