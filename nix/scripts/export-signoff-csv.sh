#!/usr/bin/env bash
# CI/lit wrapper → export-signoff-csv.py (test/lit/csv_gates).
# Usage: export-signoff-csv.sh --workspace DIR --out-dir DIR --spec FILE
# Env: ECC_REPO_ROOT, PYTHON, ECC_SIGNOFF_CSV_SPEC, ECC_SIGNOFF_RUN_ID

set -euo pipefail

root="${ECC_REPO_ROOT:-$PWD}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${PYTHON:-}" ]]; then py="$PYTHON"
elif [[ -x "$root/.venv/bin/python" ]]; then py="$root/.venv/bin/python"
else py="python3"; fi

export ECC_REPO_ROOT="$root"

# Allow ECC_SIGNOFF_CSV_SPEC when --spec omitted (lit / CI convenience).
args=("$@")
if [[ -n "${ECC_SIGNOFF_CSV_SPEC:-}" ]]; then
  has_spec=0
  for a in "${args[@]+"${args[@]}"}"; do
    [[ "$a" == "--spec" ]] && has_spec=1 && break
  done
  if [[ $has_spec -eq 0 ]]; then
    args+=(--spec "$ECC_SIGNOFF_CSV_SPEC")
  fi
fi

echo "export-signoff-csv: ${args[*]-}"
exec "$py" "$here/export-signoff-csv.py" "${args[@]+"${args[@]}"}"
