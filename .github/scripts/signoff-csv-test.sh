#!/usr/bin/env bash
# Negative-path checks for the standalone signoff CSV collector.
# Usage: signoff-csv-test.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "${here}/../.." && pwd)"
fixture_sh="${root}/nix/lit/signoff/fixture.sh"
export_sh="${root}/nix/export/signoff_csv.sh"
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
sed -i 's/^harden,die_area,40000.0,/harden,die_area,,/' "${ws}/out/area.csv"
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
  '| `synthesis` | `synthesis_cell_area` | `4200.0` um^2 |' \
  '| `post_floorplan` | `die_area` | `40000.0` um^2 |' \
  '| `post_floorplan` | `core_area` | `32000.0` um^2 |' \
  '| `post_floorplan` | `core_utilization` | `0.62` ratio |' \
  '| `harden` | `die_area` | N/A |' \
  '| `harden` | `core_area` | `32000.0` um^2 |' \
  '| `harden` | `core_utilization` | `0.62` ratio |' \
  '' \
  '#### STA' \
  '' \
  '| Corner | RC corner | Setup WNS | Setup TNS | Hold WNS | Hold TNS |' \
  '| --- | --- | --- | --- | --- | --- |' \
  '| `Overall` | `-` | `1.2` ns | `0.0` ns | `0.15` ns | `0.0` ns |' \
  '| `MAX_125` | `RCworst` | `1.2` ns | `0.0` ns | `0.15` ns | `0.0` ns |' \
  '' \
  '#### Recommended frequency [FIXTURE]' \
  '' \
  '| Metric | Value | Status | Detail |' \
  '| --- | --- | --- | --- |' \
  '| Target | `200` MHz | pass |  |' \
  '| PLL output | `180` MHz | pass | N=18; s=1; OD=10; VCO=720 MHz |' \
  '| Achieved Fmax | `195.5` MHz | pass |  |' \
  '| Verified | `190` MHz | pass | run v190 |' \
  '| Guardband limit | `180.5` MHz | pass |  |' \
  '| Recommended | `180` MHz | pass | g_f=0.05; run g180 |' \
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
rm -rf "${ws}/post_route_lec_kepler_formal"
check_export "LEC missing result fails" "${ws}" fail

# 3. LEC: recorded hash no longer matches the netlist -> stale fails.
ws="${tmp}/lec-stale"
fresh_workspace "${ws}"
mutate_json "${ws}/post_route_lec_kepler_formal/output/gcd_post_route_lec_result.json" \
  '.golden_sha256 = ("0" * 64)'
check_export "LEC stale netlist fails" "${ws}" fail

# 4. LEC: a kepler-formal result must not satisfy a ledger naming another
#    engine (one built with the removed yosys_lec engine).
ws="${tmp}/lec-residue"
fresh_workspace "${ws}"
mutate_json "${ws}/home/flow.json" \
  '(.steps[] | select(.name == "post_route_lec")) |= . + {tool: "yosys_lec", directory: "post_route_lec_yosys_lec"}'
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
rm -f "${ws}/harden_ecc/output/gcd_harden.gds"
check_export "harden missing artifact fails" "${ws}" fail

# 9. post_route_lec omitted from the ledger is not a mandatory LEC gate.
ws="${tmp}/lec-skipped"
fresh_workspace "${ws}"
mutate_json "${ws}/home/flow.json"   '.steps = [.steps[] | select(.name != "post_route_lec")]'
check_export "post_route_lec omitted from ledger is skipped and passes" "${ws}" pass

# 10. post_route_lec present but non-success must fail, never read stale residue.
ws="${tmp}/lec-non-success"
fresh_workspace "${ws}"
mutate_json "${ws}/home/flow.json"   '(.steps[] | select(.name == "post_route_lec") | .state) = "Incomplete"'
check_export "post_route_lec non-success fails despite stale result" "${ws}" fail

# 11. Harden area metrics are optional; final artifacts still satisfy the gate.
ws="${tmp}/harden-optional-area"
fresh_workspace "${ws}"
mutate_json "${ws}/harden_ecc/analysis/qor_metrics.json" \
  '.metrics = [.metrics[] | select(.id == "harden_artifact_missing_count")]'
check_export "harden optional area metrics do not fail the gate" "${ws}" pass

# 12. Indexed step directories must populate CSV data used by the job summary.
ws="${tmp}/indexed"
fresh_workspace "${ws}"
mv "${ws}/synthesis_yosys" "${ws}/01_synthesis_yosys"
mv "${ws}/post_floorplan_ecc" "${ws}/04_post_floorplan_ecc"
mv "${ws}/drc_ecc" "${ws}/14_drc_ecc"
mv "${ws}/sta_ecc" "${ws}/18_sta_ecc"
mv "${ws}/post_route_lec_kepler_formal" "${ws}/16_post_route_lec_kepler_formal"
mv "${ws}/harden_ecc" "${ws}/21_harden_ecc"
mutate_json "${ws}/home/flow.json" \
  '.steps = [.steps[] | . + {directory: ({
    "synthesis": "01_synthesis_yosys",
    "post_floorplan": "04_post_floorplan_ecc",
    "drc": "14_drc_ecc",
    "sta": "18_sta_ecc",
    "post_route_lec": "16_post_route_lec_kepler_formal",
    "harden": "21_harden_ecc"
  }[.name] // (.name + "_" + .tool))}]'
check_export "indexed step directories pass" "${ws}" pass
grep -q '^synthesis,synthesis_cell_area,4200.0,um^2,01_synthesis_yosys/analysis/qor_metrics.json,true$' \
  "${ws}/out/area.csv" || fail "indexed synthesis area is missing from the summary CSV"

# 13. Frequency: unknown higher evidence cannot promote a lower candidate.
ws="${tmp}/frequency-higher-unknown"
fresh_workspace "${ws}"
mutate_json "${ws}/home/frequency.json" \
  '(.runs[] | select(.run_id == "v200") | .status) = "unknown"'
check_export "frequency higher unknown keeps the mandatory gate green" "${ws}" pass
grep -Fq 'frequency,recommended_frequency_mhz,,MHz,incomplete_evidence,higher_candidate_unknown,,fixture' \
  "${ws}/out/frequency.csv" || fail "frequency higher unknown produced a recommendation"
jq -e '.gate == "PASS" and .checks.frequency.status == "incomplete_evidence"' \
  "${ws}/out/signoff_csv_manifest.json" >/dev/null || fail "frequency higher unknown manifest is inconsistent"
pass "frequency higher unknown is report-only and fail-closed"

# 14. Frequency: missing native target stays unavailable in CSV and Markdown.
ws="${tmp}/frequency-target-missing"
fresh_workspace "${ws}"
mutate_json "${ws}/sta_ecc/analysis/qor_metrics.json" \
  '.metrics = [.metrics[] | select(.id != "sta_target_frequency_mhz")]'
check_export "frequency missing native target keeps the mandatory gate green" "${ws}" pass
grep -Fq 'frequency,target_frequency_mhz,,MHz,unavailable,native_target_unavailable,,fixture' \
  "${ws}/out/frequency.csv" || fail "missing target was rendered as available"
grep -Fq 'frequency,recommended_frequency_mhz,,MHz,unavailable,target_unavailable,,fixture' \
  "${ws}/out/frequency.csv" || fail "missing target produced a recommendation"
mkdir -p "${ws}/signoff-artifacts"
ln -s "${ws}/out" "${ws}/signoff-artifacts/e2e-signoff-csv-gcd"
(
  cd "${ws}"
  EXPECTED_DESIGNS='["gcd"]' GITHUB_STEP_SUMMARY="${tmp}/frequency-target-missing.md" node "${summary_js}"
)
grep -Fqx '| Target | N/A | unavailable | native_target_unavailable |' \
  "${tmp}/frequency-target-missing.md" || fail "renderer did not preserve unavailable target"
grep -Fqx '| Recommended | N/A | unavailable | target_unavailable |' \
  "${tmp}/frequency-target-missing.md" || fail "renderer did not preserve unavailable recommendation"
grep -Fqx '#### Recommended frequency [FIXTURE]' \
  "${tmp}/frequency-target-missing.md" || fail "renderer omitted fixture evidence label"
pass "frequency target and recommendation remain unavailable end to end"

# 15. Frequency: absent input produces an unavailable report, not a gate failure.
ws="${tmp}/frequency-input-missing"
fresh_workspace "${ws}"
rm "${ws}/home/frequency.json"
check_export "frequency missing input keeps the mandatory gate green" "${ws}" pass
grep -Fq 'frequency,recommended_frequency_mhz,,MHz,unavailable,frequency_input_missing,,' \
  "${ws}/out/frequency.csv" || fail "missing frequency input did not stay unavailable"
jq -e '.gate == "PASS" and .checks.frequency.status == "unavailable" and .checks.frequency.evidence_mode == ""' \
  "${ws}/out/signoff_csv_manifest.json" >/dev/null || fail "missing frequency input manifest is inconsistent"
pass "frequency missing input is explicit and report-only"

# 16. Frequency: malformed input produces an unavailable report, not a gate failure.
ws="${tmp}/frequency-input-invalid"
fresh_workspace "${ws}"
mutate_json "${ws}/home/frequency.json" '.params.pll_bypass = 1'
check_export "frequency invalid input keeps the mandatory gate green" "${ws}" pass
grep -Fq 'frequency,recommended_frequency_mhz,,MHz,unavailable,invalid_frequency_input,,' \
  "${ws}/out/frequency.csv" || fail "invalid frequency input did not stay unavailable"
pass "frequency invalid input is explicit and report-only"

# 17. Frequency: unknown guardband evidence blocks a lower recommendation.
ws="${tmp}/frequency-guardband-unknown"
fresh_workspace "${ws}"
mutate_json "${ws}/home/frequency.json" \
  '(.runs[] | select(.run_id == "g180") | .status) = "unknown"'
check_export "frequency guardband unknown keeps the mandatory gate green" "${ws}" pass
grep -Fq 'frequency,verified_frequency_mhz,190,MHz,pass,,v190,fixture' \
  "${ws}/out/frequency.csv" || fail "guardband unknown discarded the verified candidate"
grep -Fq 'frequency,recommended_frequency_mhz,,MHz,incomplete_evidence,guardband_higher_unknown,,fixture' \
  "${ws}/out/frequency.csv" || fail "guardband unknown produced a recommendation"
pass "frequency guardband unknown is fail-closed"

# 18. Repeated exports of one workspace must be byte-identical.
ws="${tmp}/frequency-deterministic"
fresh_workspace "${ws}"
check_export "frequency deterministic first export passes" "${ws}" pass
cp -a "${ws}/out" "${tmp}/frequency-deterministic-first"
check_export "frequency deterministic second export passes" "${ws}" pass
if ! diff -ru --exclude=export.log "${tmp}/frequency-deterministic-first" "${ws}/out"; then
  fail "repeated signoff CSV exports differ"
fi
pass "repeated signoff CSV exports are byte-identical"

echo "all signoff CSV negative-path checks passed"
