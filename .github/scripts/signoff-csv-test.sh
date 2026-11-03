#!/usr/bin/env bash
# Negative-path checks for the standalone signoff CSV collector.
# Usage: signoff-csv-test.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "${here}/../.." && pwd)"
fixture_sh="${root}/nix/scripts/signoff-csv-fixture.sh"
export_sh="${root}/nix/scripts/signoff_csv/export.sh"

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

# 4. LEC: cross-engine residue must not satisfy the selected engine.
ws="${tmp}/lec-residue"
fresh_workspace "${ws}"
mutate_json "${ws}/home/flow.json" \
  '(.steps[] | select(.name == "postRouteLec") | .tool) = "yosys_lec"'
check_export "LEC cross-engine residue fails" "${ws}" fail

# 5. LEC: supported yosys_lec engine passes when its own result exists.
ws="${tmp}/lec-yosys"
fresh_workspace "${ws}"
mv "${ws}/postRouteLec_kepler_formal" "${ws}/postRouteLec_yosys_lec"
mutate_json "${ws}/home/flow.json" \
  '(.steps[] | select(.name == "postRouteLec") | .tool) = "yosys_lec"'
check_export "LEC yosys_lec passes" "${ws}" pass

# 6. LEC: supported lec_dual engine is not hidden by directory filtering.
ws="${tmp}/lec-dual"
fresh_workspace "${ws}"
mv "${ws}/postRouteLec_kepler_formal" "${ws}/postRouteLec_dual"
mutate_json "${ws}/home/flow.json" \
  '(.steps[] | select(.name == "postRouteLec") | .tool) = "lec_dual"'
check_export "LEC lec_dual passes" "${ws}" pass

# 7. DRC: clean gate reported as fail -> mandatory gate fails.
ws="${tmp}/drc-fail"
fresh_workspace "${ws}"
mutate_json "${ws}/drc_ecc/analysis/qor_summary.json" \
  '(.gates[] | select(.id == "qor.drc.clean") | .state) = "fail"'
check_export "DRC gate fail fails" "${ws}" fail

# 8. DRC: metric missing while gate claims pass -> inconsistent evidence fails.
ws="${tmp}/drc-missing-metric"
fresh_workspace "${ws}"
mutate_json "${ws}/drc_ecc/analysis/qor_metrics.json" \
  '.metrics = [.metrics[] | select(.id != "drc_count")]'
check_export "DRC missing metric fails" "${ws}" fail

# 9. STA: a missing mandatory metric -> present=false fails.
ws="${tmp}/sta-missing"
fresh_workspace "${ws}"
mutate_json "${ws}/sta_ecc/analysis/qor_metrics.json" \
  '.metrics = [.metrics[] | select(.id != "sta_setup_wns")]'
check_export "STA missing metric fails" "${ws}" fail

# 10. Harden: missing final artifact -> present=false fails.
ws="${tmp}/harden-missing-artifact"
fresh_workspace "${ws}"
rm -f "${ws}/Harden_ecc/output/gcd_Harden.gds"
check_export "Harden missing artifact fails" "${ws}" fail

# 11. Fallback shape: no flow.json.design; design comes from params.toml.
ws="${tmp}/no-flow-json"
fresh_workspace "${ws}"
rm -f "${ws}/home/flow.json"
check_export "no flow.json still passes from params design" "${ws}" pass

# 12. postRouteLec omitted from the ledger is not a mandatory LEC gate.
ws="${tmp}/lec-skipped"
fresh_workspace "${ws}"
mutate_json "${ws}/home/flow.json"   '.steps = [.steps[] | select(.name != "postRouteLec")]'
check_export "postRouteLec omitted from ledger is skipped and passes" "${ws}" pass

# 13. postRouteLec present but non-success must fail, never read stale residue.
ws="${tmp}/lec-non-success"
fresh_workspace "${ws}"
mutate_json "${ws}/home/flow.json"   '(.steps[] | select(.name == "postRouteLec") | .state) = "Incomplete"'
check_export "postRouteLec non-success fails despite stale result" "${ws}" fail

echo "all signoff CSV negative-path checks passed"
