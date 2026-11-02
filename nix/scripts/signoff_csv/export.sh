#!/usr/bin/env bash
# Standalone signoff product CSV collector implemented in shell + jq.
# Usage: export.sh --workspace DIR --out-dir DIR [--checks sta,drc,lec,harden,area]
set -euo pipefail

usage() {
  echo "usage: $0 --workspace DIR --out-dir DIR [--checks sta,drc,lec,harden,area]" >&2
  exit 2
}

workspace=
out_dir=
checks=sta,drc,lec,harden,area

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      workspace="${2:-}"
      shift 2
      ;;
    --out-dir)
      out_dir="${2:-}"
      shift 2
      ;;
    --checks)
      checks="${2:-sta,drc,lec,harden,area}"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

[[ -n "${workspace}" && -n "${out_dir}" ]] || usage
[[ -d "${workspace}" ]] || {
  echo "error: workspace not found: ${workspace}" >&2
  exit 2
}
workspace="$(cd "${workspace}" && pwd)"
mkdir -p "${out_dir}"
out_dir="$(cd "${out_dir}" && pwd)"

trim() {
  local v="$1"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  printf '%s' "$v"
}

IFS=',' read -r -a check_array <<< "${checks}"
for i in "${!check_array[@]}"; do
  check_array[i]="$(trim "${check_array[i]}")"
done
for c in "${check_array[@]}"; do
  case "$c" in
    sta|drc|lec|harden|area) ;;
    *)
      echo "unknown checks: $c" >&2
      exit 2
      ;;
  esac
done

flow_file="${workspace}/home/flow.json"
design=
if [[ -f "${flow_file}" ]]; then
  design="$(jq -r '.design // empty' "${flow_file}" 2>/dev/null || true)"
fi
[[ -n "${design}" ]] || design="$(basename "${workspace}")"

relative_path() {
  local p="$1"
  p="${p#"${workspace}"/}"
  printf '%s' "$p"
}

step_tool() {
  local name="$1"
  [[ -f "${flow_file}" ]] || return 0
  jq -r --arg name "${name}" \
    '([.steps[]? | select(.name == $name) | .tool // ""] | .[0]) // ""' \
    "${flow_file}" 2>/dev/null || true
}

step_directory() {
  local name="$1"
  local tool
  case "$name" in
    sta) printf 'sta_ecc' ;;
    drc) printf 'drc_ecc' ;;
    Harden) printf 'Harden_ecc' ;;
    postRouteLec)
      tool="$(step_tool postRouteLec)"
      tool="${tool,,}"
      case "$tool" in
        kepler_formal) printf 'postRouteLec_kepler_formal' ;;
        yosys_lec) printf 'postRouteLec_yosys_lec' ;;
        lec_dual) printf 'postRouteLec_dual' ;;
        *) printf 'postRouteLec_kepler_formal' ;;
      esac
      ;;
    *) printf '%s_ecc' "$name" ;;
  esac
}

json_metric_value() {
  local file="$1"
  local id="$2"
  [[ -f "${file}" ]] || return 0
  jq -r --arg id "$id" \
    '(.metrics[]? // empty | select(.id == $id) | .value) // ""' \
    "${file}" 2>/dev/null || true
}

json_metric_present() {
  local file="$1"
  local id="$2"
  if [[ -f "${file}" ]] &&
    jq -e --arg id "$id" '.metrics[]? | select(.id == $id)' "${file}" >/dev/null 2>&1; then
    printf 'true'
  else
    printf 'false'
  fi
}

gate_state() {
  local file="$1"
  local id="$2"
  [[ -f "${file}" ]] || {
    printf 'unavailable'
    return 0
  }
  jq -r --arg id "$id" \
    '([.gates[]? | select(.id == $id) | .state] | .[0]) // "unavailable"' \
    "${file}" 2>/dev/null || true
}

csv_quote() {
  local v="${1-}"
  case "$v" in
    *','*|*'"'*|*$'\n'*) printf '"%s"' "${v//\"/\"\"}" ;;
    *) printf '%s' "$v" ;;
  esac
}

csv_row() {
  local out=""
  local first=1
  local f
  for f in "$@"; do
    if (( first )); then
      first=0
    else
      out+=','
    fi
    out+="$(csv_quote "$f")"
  done
  printf '%s\n' "$out"
}

collect_sta() {
  csv_row kind corner rc_corner metric value unit source present

  local sta_dir
  sta_dir="$(step_directory sta)"
  local metrics="${workspace}/${sta_dir}/analysis/qor_metrics.json"
  local source
  source="$(relative_path "${metrics}")"

  local item id unit value present
  for item in \
    sta_setup_wns:ns \
    sta_setup_tns:ns \
    sta_setup_violation_count:count \
    sta_hold_wns:ns \
    sta_hold_tns:ns \
    sta_hold_violation_count:count \
    sta_frequency_mhz:MHz \
    sta_corner_count:count \
    sta_expected_corner_count:count \
    sta_missing_corner_count:count; do
    id="${item%%:*}"
    unit="${item#*:}"
    value="$(json_metric_value "${metrics}" "${id}")"
    present="$(json_metric_present "${metrics}" "${id}")"
    csv_row qor_metrics "" "" "$id" "$value" "$unit" "$source" "$present"
  done

  local feature="${workspace}/${sta_dir}/feature"
  [[ -d "${feature}" ]] || return 0

  local summary_path corner rc_corner group field value
  while IFS= read -r -d '' summary_path; do
    rc_corner="$(basename "$(dirname "${summary_path}")")"
    corner="$(basename "$(dirname "$(dirname "${summary_path}")")")"
    source="$(relative_path "${summary_path}")"
    for group in setup hold; do
      for field in wns tns nvp; do
        case "${field}" in
          wns) unit=ns ;;
          tns) unit=ns ;;
          nvp) unit=count ;;
        esac
        value="$(jq -r --arg group "${group}" --arg field "${field}" \
          '.summary[$group][$field] // ""' "${summary_path}" 2>/dev/null || true)"
        csv_row corner_summary "$corner" "$rc_corner" "${group}_${field}" "$value" "$unit" "$source" true
      done
    done
    if jq -e '.summary.setup | has("frequency_mhz")' "${summary_path}" >/dev/null 2>&1; then
      value="$(jq -r '.summary.setup.frequency_mhz // ""' "${summary_path}" 2>/dev/null || true)"
      csv_row corner_summary "$corner" "$rc_corner" setup_frequency_mhz "$value" MHz "$source" true
    fi
  done < <(find "${feature}" -mindepth 3 -maxdepth 3 -type f -name qor_summary.json -print0 | sort -z)
}

collect_drc() {
  csv_row kind metric value unit gate gate_state source present

  local drc_dir
  drc_dir="$(step_directory drc)"
  local metrics="${workspace}/${drc_dir}/analysis/qor_metrics.json"
  local summary="${workspace}/${drc_dir}/analysis/qor_summary.json"
  local source
  source="$(relative_path "${metrics}")"
  local value present state
  value="$(json_metric_value "${metrics}" drc_count)"
  present="$(json_metric_present "${metrics}" drc_count)"
  state="$(gate_state "${summary}" qor.drc.clean)"
  csv_row metric drc_count "$value" count qor.drc.clean "$state" "$source" "$present"
}

collect_lec() {
  csv_row status golden_verilog golden_sha256 golden_size_bytes gate_verilog gate_sha256 gate_size_bytes source present

  local preferred
  preferred="$(step_directory postRouteLec)"
  local result=""
  local fallback=""
  local p parent_dir
  while IFS= read -r -d '' p; do
    parent_dir="$(basename "$(dirname "$(dirname "$p")")")"
    if [[ "${parent_dir}" == postRouteLec_*_* ]]; then
      fallback="${fallback:-$p}"
      if [[ "${parent_dir}" == "${preferred}" ]]; then
        result="$p"
        break
      fi
    fi
  done < <(find "${workspace}" -mindepth 3 -maxdepth 3 -type f -name '*_postRouteLec_result.json' -print0 | sort -z)
  result="${result:-$fallback}"

  if [[ -z "${result}" ]]; then
    csv_row missing "" "" "" "" "" "" "" false
    return 0
  fi

  local status golden_verilog golden_sha256 golden_size_bytes gate_verilog gate_sha256 gate_size_bytes
  status="$(jq -r '.status // "incomplete"' "${result}" 2>/dev/null || true)"
  golden_verilog="$(jq -r '.golden_verilog // ""' "${result}" 2>/dev/null || true)"
  golden_sha256="$(jq -r '.golden_sha256 // ""' "${result}" 2>/dev/null || true)"
  golden_size_bytes="$(jq -r '.golden_size_bytes // ""' "${result}" 2>/dev/null || true)"
  gate_verilog="$(jq -r '.gate_verilog // ""' "${result}" 2>/dev/null || true)"
  gate_sha256="$(jq -r '.gate_sha256 // ""' "${result}" 2>/dev/null || true)"
  gate_size_bytes="$(jq -r '.gate_size_bytes // ""' "${result}" 2>/dev/null || true)"
  csv_row "$status" "$golden_verilog" "$golden_sha256" "$golden_size_bytes" "$gate_verilog" "$gate_sha256" "$gate_size_bytes" "$(relative_path "${result}")" true
}

collect_harden() {
  csv_row kind metric value unit source present sha256 bytes

  local harden_dir
  harden_dir="$(step_directory Harden)"
  local metrics="${workspace}/${harden_dir}/analysis/qor_metrics.json"
  local source
  source="$(relative_path "${metrics}")"
  local item id unit value present
  for item in \
    harden_artifact_missing_count:count \
    die_area:um^2 \
    core_area:um^2 \
    core_utilization:ratio; do
    id="${item%%:*}"
    unit="${item#*:}"
    value="$(json_metric_value "${metrics}" "${id}")"
    present="$(json_metric_present "${metrics}" "${id}")"
    csv_row metric "$id" "$value" "$unit" "$source" "$present" "" ""
  done

  local artifact path present sha bytes
  for artifact in gds lef lib; do
    path="${workspace}/${harden_dir}/output/${design}_Harden.${artifact}"
    source="$(relative_path "${path}")"
    if [[ -f "${path}" ]]; then
      present=true
      sha="$(sha256sum "${path}" | awk '{print $1}')"
      bytes="$(stat -c %s "${path}")"
    else
      present=false
      sha=""
      bytes=""
    fi
    csv_row artifact "$artifact" "" "" "$source" "$present" "$sha" "$bytes"
  done
}

collect_area() {
  csv_row step metric value unit source present

  local step dir source metrics value present
  local metric unit
  for spec in \
    "Synthesis Synthesis_yosys synthesis_cell_area um^2" \
    "postFloorplan postFloorplan_ecc die_area um^2" \
    "postFloorplan postFloorplan_ecc core_area um^2" \
    "postFloorplan postFloorplan_ecc core_utilization ratio" \
    "Harden Harden_ecc die_area um^2" \
    "Harden Harden_ecc core_area um^2" \
    "Harden Harden_ecc core_utilization ratio"; do
    read -r step dir metric unit <<< "${spec}"
    metrics="${workspace}/${dir}/analysis/qor_metrics.json"
    source="$(relative_path "${metrics}")"
    value="$(json_metric_value "${metrics}" "${metric}")"
    present="$(json_metric_present "${metrics}" "${metric}")"
    csv_row "$step" "$metric" "$value" "$unit" "$source" "$present"
  done
}

contains_check() {
  local wanted="$1"
  local c
  for c in "${check_array[@]}"; do
    [[ "$c" == "$wanted" ]] && return 0
  done
  return 1
}

declare -A statuses rows files
sta_selected=0
drc_selected=0
lec_selected=0
harden_selected=0
area_selected=0
sta_status=pass
drc_status=pass
lec_status=pass
harden_status=pass
area_status=pass
sta_rows=0
drc_rows=0
lec_rows=0
harden_rows=0
area_rows=0

for check in "${check_array[@]}"; do
  case "$check" in
    sta)
      sta_selected=1
      collect_sta > "${out_dir}/sta.csv"
      sta_rows=$(($(wc -l < "${out_dir}/sta.csv") - 1))
      ;;
    drc)
      drc_selected=1
      collect_drc > "${out_dir}/drc.csv"
      drc_rows=$(($(wc -l < "${out_dir}/drc.csv") - 1))
      ;;
    lec)
      lec_selected=1
      collect_lec > "${out_dir}/lec.csv"
      lec_rows=$(($(wc -l < "${out_dir}/lec.csv") - 1))
      ;;
    harden)
      harden_selected=1
      collect_harden > "${out_dir}/harden.csv"
      harden_rows=$(($(wc -l < "${out_dir}/harden.csv") - 1))
      ;;
    area)
      area_selected=1
      collect_area > "${out_dir}/area.csv"
      area_rows=$(($(wc -l < "${out_dir}/area.csv") - 1))
      ;;
  esac
done

status_for() {
  local check="$1"
  local file="$2"
  local present_field="${3:-}"
  local row_count
  row_count=$(($(wc -l < "${file}") - 1))
  if (( row_count <= 0 )); then
    printf 'fail'
    return 0
  fi
  case "$check" in
    lec)
      local lec_state
      lec_state="$(awk -F, 'NR==2 {print $1; exit}' "${file}")"
      if [[ "${lec_state}" == proven ]]; then
        printf 'pass'
      else
        printf 'fail'
      fi
      ;;
    drc)
      local drc_gate
      drc_gate="$(awk -F, 'NR==2 {print $6; exit}' "${file}")"
      if [[ "${drc_gate}" == pass ]]; then
        printf 'pass'
      else
        printf 'fail'
      fi
      ;;
    *)
      if awk -F, -v p="$present_field" 'NR>1 && $p != "true" {f=1} END {exit f ? 0 : 1}' "${file}" >/dev/null; then
        printf 'fail'
      else
        printf 'pass'
      fi
      ;;
  esac
}

if [[ "${sta_selected}" == 1 ]]; then sta_status="$(status_for sta "${out_dir}/sta.csv" 8)"; fi
if [[ "${drc_selected}" == 1 ]]; then drc_status="$(status_for drc "${out_dir}/drc.csv")"; fi
if [[ "${lec_selected}" == 1 ]]; then lec_status="$(status_for lec "${out_dir}/lec.csv")"; fi
if [[ "${harden_selected}" == 1 ]]; then harden_status="$(status_for harden "${out_dir}/harden.csv" 6)"; fi
if [[ "${area_selected}" == 1 ]]; then area_status="$(status_for area "${out_dir}/area.csv" 6)"; fi

gate=PASS
for check in "${check_array[@]}"; do
  case "$check" in
    sta) [[ "$sta_status" == pass ]] || gate=FAIL ;;
    drc) [[ "$drc_status" == pass ]] || gate=FAIL ;;
    lec) [[ "$lec_status" == pass ]] || gate=FAIL ;;
    harden) [[ "$harden_status" == pass ]] || gate=FAIL ;;
  esac
done

manifest="$(
  jq -n \
    --arg workspace "${workspace}" \
    --arg design "${design}" \
    --arg sta_selected "${sta_selected}" \
    --arg drc_selected "${drc_selected}" \
    --arg lec_selected "${lec_selected}" \
    --arg harden_selected "${harden_selected}" \
    --arg area_selected "${area_selected}" \
    --arg sta_status "${sta_status}" \
    --arg drc_status "${drc_status}" \
    --arg lec_status "${lec_status}" \
    --arg harden_status "${harden_status}" \
    --arg area_status "${area_status}" \
    --argjson sta_rows "${sta_rows}" \
    --argjson drc_rows "${drc_rows}" \
    --argjson lec_rows "${lec_rows}" \
    --argjson harden_rows "${harden_rows}" \
    --argjson area_rows "${area_rows}" \
    --arg sta_file "sta.csv" \
    --arg drc_file "drc.csv" \
    --arg lec_file "lec.csv" \
    --arg harden_file "harden.csv" \
    --arg area_file "area.csv" \
    --arg sta_path "${out_dir}/sta.csv" \
    --arg drc_path "${out_dir}/drc.csv" \
    --arg lec_path "${out_dir}/lec.csv" \
    --arg harden_path "${out_dir}/harden.csv" \
    --arg area_path "${out_dir}/area.csv" \
    --arg gate "${gate}" \
    '{
       schema_version: 1,
       kind: "signoff_csv_manifest",
       workspace: $workspace,
       design: $design,
       checks: (
         (if $sta_selected == "1" then {"sta": {"status": $sta_status, "rows": $sta_rows, "file": $sta_file}} else {} end)
         + (if $drc_selected == "1" then {"drc": {"status": $drc_status, "rows": $drc_rows, "file": $drc_file}} else {} end)
         + (if $lec_selected == "1" then {"lec": {"status": $lec_status, "rows": $lec_rows, "file": $lec_file}} else {} end)
         + (if $harden_selected == "1" then {"harden": {"status": $harden_status, "rows": $harden_rows, "file": $harden_file}} else {} end)
         + (if $area_selected == "1" then {"area": {"status": $area_status, "rows": $area_rows, "file": $area_file}} else {} end)
       ),
       files: (
         (if $sta_selected == "1" then {"sta": $sta_path} else {} end)
         + (if $drc_selected == "1" then {"drc": $drc_path} else {} end)
         + (if $lec_selected == "1" then {"lec": $lec_path} else {} end)
         + (if $harden_selected == "1" then {"harden": $harden_path} else {} end)
         + (if $area_selected == "1" then {"area": $area_path} else {} end)
       ),
       gate: $gate
     }'
)"

printf '%s\n' "${manifest}" > "${out_dir}/signoff_csv_manifest.json"

if [[ "${gate}" == PASS ]]; then
  exit 0
fi
exit 1
