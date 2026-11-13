#!/usr/bin/env bash
# Negative-path checks for the standalone signoff CSV collector.
# Usage: signoff-csv-test.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "${here}/../.." && pwd)"
fixture_sh="${root}/nix/scripts/signoff-csv-fixture.sh"
export_sh="${root}/nix/scripts/signoff_csv/export.sh"
summary_js="${root}/.github/scripts/signoff-csv-summary.js"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "ok: $*"
}

fresh_workspace() {
  local dir="$1"
  rm -rf "${dir}"
  bash "${fixture_sh}" --workspace "${dir}"
}

run_export() {
  local ws="$1"
  local out="${ws}/out"
  mkdir -p "${out}"
  local status=0
  bash "${export_sh}" --workspace "${ws}" --out-dir "${out}" >"${out}/export.log" 2>&1 || status=$?
  local gate
  gate="$(jq -r '.gate // "NO_MANIFEST"' "${out}/signoff_csv_manifest.json" 2>/dev/null || true)"
  printf '%s\n' "${status} ${gate}"
}

check_export() {
  local desc="$1"
  local ws="$2"
  local expect="$3"
  local result status gate
  result="$(run_export "${ws}")"
  status="${result%% *}"
  gate="${result#* }"
  if [[ "${expect}" == pass ]]; then
    if [[ "${status}" == 0 && "${gate}" == PASS ]]; then
      pass "${desc}"
    else
      cat "${ws}/out/export.log" >&2 || true
      fail "${desc}: expected exit 0 / gate PASS, got exit ${status} / gate ${gate}"
    fi
  else
    if [[ "${status}" != 0 && "${gate}" == FAIL ]]; then
      pass "${desc}"
    else
      cat "${ws}/out/export.log" >&2 || true
      fail "${desc}: expected non-zero exit / gate FAIL, got exit ${status} / gate ${gate}"
    fi
  fi
}

mutate_json() {
  local file="$1"
  local filter="$2"
  jq "${filter}" "${file}" > "${file}.tmp"
  mv "${file}.tmp" "${file}"
}

# 1. Happy path must stay green.
ws="${tmp}/happy"
fresh_workspace "${ws}"
check_export "happy path passes" "${ws}" pass

summary_file="${tmp}/summary.md"
sed -i 's/^Harden,die_area,40000.0,/Harden,die_area,,/' "${ws}/out/area.csv"
mkdir -p "${ws}/signoff-artifacts/e2e-signoff-csv-invalid"
ln -s "${ws}/out" "${ws}/signoff-artifacts/e2e-signoff-csv-gcd"
printf '%s\n' '{"schema_version":2,"kind":"signoff_csv_manifest","gate":"PASS","checks":{}}' \
  > "${ws}/signoff-artifacts/e2e-signoff-csv-invalid/signoff_csv_manifest.json"
(
  cd "${ws}"
  EXPECTED_DESIGNS='["gcd","missing","invalid"]' GITHUB_STEP_SUMMARY="${summary_file}" node "${summary_js}"
)
printf -v expected_summary '%s\n' \
  '## Signoff CSV Report' \
  '' \
  '| Design | Gate | DRC | Die area | Setup WNS | Setup TNS | Hold WNS | Hold TNS |' \
  '| --- | --- | --- | --- | --- | --- | --- | --- |' \
  '| `gcd` | `PASS` | `0` count | `40000.0` um^2 | `1.2` ns | `0.0` ns | `0.15` ns | `0.0` ns |' \
  '| `missing` | `Unavailable` | N/A | N/A | N/A | N/A | N/A | N/A |' \
  '| `invalid` | `Unavailable` | N/A | N/A | N/A | N/A | N/A | N/A |' \
  '' \
  '<details>' \
  '<summary>gcd</summary>' \
  '' \
  '#### Area' \
  '' \
  '| Step | Metric | Value |' \
  '| --- | --- | --- |' \
  '| `Synthesis` | `synthesis_cell_area` | `4200.0` um^2 |' \
  '| `postFloorplan` | `die_area` | `40000.0` um^2 |' \
  '| `postFloorplan` | `core_area` | `32000.0` um^2 |' \
  '| `postFloorplan` | `core_utilization` | `0.62` ratio |' \
  '| `Harden` | `die_area` | N/A |' \
  '| `Harden` | `core_area` | `32000.0` um^2 |' \
  '| `Harden` | `core_utilization` | `0.62` ratio |' \
  '' \
  '#### STA' \
  '' \
  '| Corner | RC corner | Setup WNS | Setup TNS | Hold WNS | Hold TNS |' \
  '| --- | --- | --- | --- | --- | --- |' \
  '| `Overall` | `-` | `1.2` ns | `0.0` ns | `0.15` ns | `0.0` ns |' \
  '| `MAX_125` | `RCworst` | `1.2` ns | `0.0` ns | `0.15` ns | `0.0` ns |' \
  '' \
  '</details>' \
  '' \
  '<details>' \
  '<summary>missing</summary>' \
  '' \
  'No CSV artifact was produced by this E2E job.' \
  '' \
  '</details>' \
  '' \
  '<details>' \
  '<summary>invalid</summary>' \
  '' \
  'No CSV artifact was produced by this E2E job.' \
  '' \
  '</details>'
if ! diff -u <(printf '%s' "${expected_summary}") "${summary_file}"; then
  fail "job summary aggregates reports and handles missing or invalid artifacts"
fi
pass "job summary aggregates reports and handles missing or invalid artifacts"

# 2. LEC: no selected-engine result -> mandatory gate fails.
ws="${tmp}/lec-missing"
fresh_workspace "${ws}"
rm -rf "${ws}/postRouteLec_kepler_formal"
check_export "LEC missing result fails" "${ws}" fail

# 3. LEC: recorded hash no longer matches the netlist -> stale fails.
ws="${tmp}/lec-stale"
fresh_workspace "${ws}"
mutate_json "${ws}/postRouteLec_kepler_formal/output/gcd_postRouteLec_result.json" \
  '.golden_sha256 = ("0" * 64)'
check_export "LEC stale netlist fails" "${ws}" fail

# 4. LEC: a kepler-formal result must not satisfy a ledger naming another
#    engine (one built with the removed yosys_lec engine).
ws="${tmp}/lec-residue"
fresh_workspace "${ws}"
mutate_json "${ws}/home/flow.json" \
  '(.steps[] | select(.name == "postRouteLec") | .tool) = "yosys_lec"'
check_export "LEC cross-engine residue fails" "${ws}" fail

# 5. DRC: clean gate reported as fail -> mandatory gate fails.
ws="${tmp}/drc-fail"
fresh_workspace "${ws}"
mutate_json "${ws}/drc_ecc/analysis/qor_summary.json" \
  '(.gates[] | select(.id == "qor.drc.clean") | .state) = "fail"'
check_export "DRC gate fail fails" "${ws}" fail

# 6. DRC: metric missing while gate claims pass -> inconsistent evidence fails.
ws="${tmp}/drc-missing-metric"
fresh_workspace "${ws}"
mutate_json "${ws}/drc_ecc/analysis/qor_metrics.json" \
  '.metrics = [.metrics[] | select(.id != "drc_count")]'
check_export "DRC missing metric fails" "${ws}" fail

# 7. STA: a missing mandatory metric -> present=false fails.
ws="${tmp}/sta-missing"
fresh_workspace "${ws}"
mutate_json "${ws}/sta_ecc/analysis/qor_metrics.json" \
  '.metrics = [.metrics[] | select(.id != "sta_setup_wns")]'
check_export "STA missing metric fails" "${ws}" fail

# 8. Harden: missing final artifact -> present=false fails.
ws="${tmp}/harden-missing-artifact"
fresh_workspace "${ws}"
rm -f "${ws}/Harden_ecc/output/gcd_Harden.gds"
check_export "Harden missing artifact fails" "${ws}" fail

# 9. Fallback shape: no flow.json.design; design comes from params.toml.
ws="${tmp}/no-flow-json"
fresh_workspace "${ws}"
rm -f "${ws}/home/flow.json"
check_export "no flow.json still passes from params design" "${ws}" pass

# 10. postRouteLec omitted from the ledger is not a mandatory LEC gate.
ws="${tmp}/lec-skipped"
fresh_workspace "${ws}"
mutate_json "${ws}/home/flow.json"   '.steps = [.steps[] | select(.name != "postRouteLec")]'
check_export "postRouteLec omitted from ledger is skipped and passes" "${ws}" pass

# 11. postRouteLec present but non-success must fail, never read stale residue.
ws="${tmp}/lec-non-success"
fresh_workspace "${ws}"
mutate_json "${ws}/home/flow.json"   '(.steps[] | select(.name == "postRouteLec") | .state) = "Incomplete"'
check_export "postRouteLec non-success fails despite stale result" "${ws}" fail

# 12. Harden area metrics are optional; final artifacts still satisfy the gate.
ws="${tmp}/harden-optional-area"
fresh_workspace "${ws}"
mutate_json "${ws}/Harden_ecc/analysis/qor_metrics.json" \
  '.metrics = [.metrics[] | select(.id == "harden_artifact_missing_count")]'
check_export "Harden optional area metrics do not fail the gate" "${ws}" pass

# 13. Indexed step directories must populate CSV data used by the job summary.
ws="${tmp}/indexed"
fresh_workspace "${ws}"
mv "${ws}/Synthesis_yosys" "${ws}/01_Synthesis_yosys"
mv "${ws}/postFloorplan_ecc" "${ws}/04_postFloorplan_ecc"
mv "${ws}/drc_ecc" "${ws}/14_drc_ecc"
mv "${ws}/sta_ecc" "${ws}/18_sta_ecc"
mv "${ws}/postRouteLec_kepler_formal" "${ws}/16_postRouteLec_kepler_formal"
mv "${ws}/Harden_ecc" "${ws}/21_Harden_ecc"
mutate_json "${ws}/home/flow.json" \
  '.steps = [.steps[] | . + {directory: ({
    "Synthesis": "01_Synthesis_yosys",
    "postFloorplan": "04_postFloorplan_ecc",
    "drc": "14_drc_ecc",
    "sta": "18_sta_ecc",
    "postRouteLec": "16_postRouteLec_kepler_formal",
    "Harden": "21_Harden_ecc"
  }[.name] // (.name + "_" + .tool))}]'
check_export "indexed step directories pass" "${ws}" pass
grep -q '^Synthesis,synthesis_cell_area,4200.0,um^2,01_Synthesis_yosys/analysis/qor_metrics.json,true$' \
  "${ws}/out/area.csv" || fail "indexed Synthesis area is missing from the summary CSV"

echo "all signoff CSV negative-path checks passed"
