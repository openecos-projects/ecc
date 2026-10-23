#!/usr/bin/env bash
# Compare basedpyright and ty diagnostics per first-party root.
#
# basedpyright is the gate; ty is a non-blocking cross-check. The two tools
# report different rule sets, so this compares where each sees noise, not
# whether the diagnostics are identical.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Run basedpyright without its shrink-only baseline so the comparison sees
# the raw diagnostics.
printf '{"files": {}}' > "$tmp/empty-baseline.json"
uv run --no-sync basedpyright --outputjson \
  --baselinefile "$tmp/empty-baseline.json" > "$tmp/basedpyright.json" 2>/dev/null || true
uv run --no-sync ty check --output-format gitlab > "$tmp/ty.json" 2>/dev/null || true

jq -e . "$tmp/basedpyright.json" >/dev/null 2>&1 || {
  echo "cannot parse basedpyright output" >&2
  exit 1
}
jq -e . "$tmp/ty.json" >/dev/null 2>&1 || {
  echo "cannot parse ty output" >&2
  exit 1
}

jq -r --arg prefix "$ROOT/" \
  '.generalDiagnostics[].file | ltrimstr($prefix) | split("/")[0]' \
  "$tmp/basedpyright.json" \
  | sort | uniq -c | awk '{print $2, $1}' | sort > "$tmp/basedpyright.tsv"
jq -r '.[].location.path | split("/")[0]' "$tmp/ty.json" \
  | sort | uniq -c | awk '{print $2, $1}' | sort > "$tmp/ty.tsv"

join -a1 -a2 -e 0 -o 0,1.2,2.2 "$tmp/basedpyright.tsv" "$tmp/ty.tsv" \
  | awk '
      BEGIN { printf "%-20s %12s %6s\n", "root", "basedpyright", "ty" }
      {
        printf "%-20s %12s %6s\n", $1, $2, $3
        basedpyright += $2
        ty += $3
      }
      END { printf "%-20s %12s %6s\n", "total", basedpyright, ty }
    '
