#!/usr/bin/env bash
# Materialize a signoff fixture workspace for lit / local smoke (jq JSON).
#
# Usage: materialize_signoff_workspace.sh WORKSPACE_DIR [--variant NAME]
#
# Variants:
#   ready              all gates pass (default)
#   metric_fail        drc_count=3 → metric gate fail
#   checklist_blocked  quality.drc.clean blocked
#   missing_metric     omit drc_count → present=false gate fail

set -euo pipefail

usage() {
  echo "usage: $0 WORKSPACE_DIR [--variant ready|metric_fail|checklist_blocked|missing_metric]" >&2
  exit 2
}

[[ $# -ge 1 ]] || usage
root="$1"
shift
variant="ready"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --variant) variant="${2:?}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

case "$variant" in
  ready|metric_fail|checklist_blocked|missing_metric) ;;
  *) echo "unknown variant: $variant" >&2; usage ;;
esac

command -v jq >/dev/null || { echo "error: jq is required" >&2; exit 1; }

mkdir -p "$root"

write_json() {
  local path="$1"
  shift
  mkdir -p "$(dirname "$path")"
  jq -n "$@" >"$path"
}

metric() {
  # metric <id> <value> [unit]
  local id="$1" value="$2" unit="${3:-}"
  jq -n --arg id "$id" --argjson value "$value" --arg unit "$unit" '{
    id: $id, display_name: $id, value: $value, unit: $unit,
    category: "timing", direction: "lower_is_better", scope: "project",
    corner: null, project_role: "gate", step_role: "primary",
    rating: {gate: true, score: true, trend: true},
    source: {kind: "analysis", path: "x"}
  }'
}

item() {
  # item <id> <step> <category> <title> [state] [blocked]
  local id="$1" step="$2" category="$3" title="$4"
  local state="${5:-pass}" blocked="${6:-false}"
  local summary="ok"
  if [[ "$state" != "pass" || "$blocked" == "true" ]]; then
    summary="violated"
  fi
  jq -n \
    --arg id "$id" --arg step "$step" --arg category "$category" --arg title "$title" \
    --arg state "$state" --argjson blocked "$blocked" --arg summary "$summary" '{
      id: $id, step: $step, category: $category, title: $title,
      policy: "block", state: $state, blocked: $blocked, summary: $summary,
      source: {}, evidence: []
    }'
}

write_json "$root/home/flow.json" '{
  steps: [
    {name: "drc", tool: "ecc", state: "Success"},
    {name: "lvs", tool: "ecc", state: "Success"},
    {name: "sta", tool: "ecc", state: "Success"},
    {name: "Harden", tool: "ecc", state: "Success"}
  ]
}'

write_json "$root/home/parameters.json" '{Design: "gcd", frequency_max: 50.0}'

drc_value=0
[[ "$variant" == "metric_fail" ]] && drc_value=3

if [[ "$variant" == "missing_metric" ]]; then
  write_json "$root/drc_ecc/analysis/qor_metrics.json" \
    '{schema_version: 3, kind: "qor_metrics", metrics: []}'
else
  write_json "$root/drc_ecc/analysis/qor_metrics.json" \
    --argjson metrics "$(jq -n --argjson m "$(metric drc_count "$drc_value")" '[$m]')" \
    '{schema_version: 3, kind: "qor_metrics", metrics: $metrics}'
fi

write_json "$root/lvs_ecc/analysis/qor_metrics.json" \
  --argjson metrics "$(jq -n --argjson m "$(metric lvs_count 0)" '[$m]')" \
  '{schema_version: 3, kind: "qor_metrics", metrics: $metrics}'

write_json "$root/sta_ecc/analysis/qor_metrics.json" \
  --argjson metrics "$(jq -n \
    --argjson a "$(metric sta_setup_wns 0.05 ns)" \
    --argjson b "$(metric sta_hold_wns 0.02 ns)" \
    '[$a, $b]')" \
  '{schema_version: 3, kind: "qor_metrics", metrics: $metrics}'

drc_item="$(item quality.drc.clean drc quality "DRC clean")"
if [[ "$variant" == "checklist_blocked" ]]; then
  drc_item="$(item quality.drc.clean drc quality "DRC clean" fail true)"
fi
checklist_status="ready"
blocked_n=0
passed_n=4
if [[ "$variant" == "checklist_blocked" ]]; then
  checklist_status="blocked"
  blocked_n=1
  passed_n=3
fi

write_json "$root/home/checklist.json" \
  --arg status "$checklist_status" \
  --argjson passed "$passed_n" \
  --argjson blocked "$blocked_n" \
  --argjson drc "$drc_item" \
  --argjson lvs "$(item quality.lvs.clean lvs quality "LVS clean")" \
  --argjson setup "$(item quality.sta.setup_closed sta quality "Setup closed")" \
  --argjson hold "$(item quality.sta.hold_closed sta quality "Hold closed")" \
  '{
    schema_version: 3,
    kind: "signoff_checklist",
    checker_revision: "signoff-v1",
    generated_at: "2026-01-01T00:00:00Z",
    status: $status,
    summary: {passed: $passed, blocked: $blocked, attention: 0, unavailable: 0},
    checklist: [$drc, $lvs, $setup, $hold]
  }'

realpath "$root" 2>/dev/null || readlink -f "$root" 2>/dev/null || echo "$(cd "$root" && pwd)"
