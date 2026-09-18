#!/usr/bin/env bash
# Export signoff CSV tables + FileCheck projection from a finished workspace.
#
# Operations (in order):
#   1. Resolve repo root and Python (prefer .venv)
#   2. Tabularize QoR / checklist / flow already on disk
#   3. Write csv/ + reports/metrics.check.txt under --out-dir
#
# Usage:
#   export_signoff_csv.sh --workspace DIR [--out-dir DIR] [--spec FILE]
#
# Env:
#   ECC_REPO_ROOT   repo checkout (default: cwd)
#   PYTHON          override interpreter

set -euo pipefail

usage() {
  cat <<'EOF'
Export signoff CSV tables + FileCheck projection from a finished workspace.

Operations:
  1. Resolve repo root and Python (prefer .venv)
  2. Tabularize QoR / checklist / flow already on disk
  3. Write csv/ + reports/metrics.check.txt under --out-dir

Usage:
  export_signoff_csv.sh --workspace DIR [--out-dir DIR] [--spec FILE]

Env:
  ECC_REPO_ROOT   repo checkout (default: cwd)
  PYTHON          override interpreter
EOF
  exit 2
}

workspace=""
out_dir="ci-artifacts/eda-signoff"
spec=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      workspace="${2:?}"
      shift 2
      ;;
    --out-dir)
      out_dir="${2:?}"
      shift 2
      ;;
    --spec)
      spec="${2:?}"
      shift 2
      ;;
    -h | --help)
      usage
      ;;
    *)
      echo "unknown arg: $1" >&2
      usage
      ;;
  esac
done

if [[ -z "$workspace" ]]; then
  echo "error: --workspace is required" >&2
  usage
fi

root="${ECC_REPO_ROOT:-$PWD}"
impl="$root/.github/scripts/_export_signoff_csv.py"

if [[ ! -f "$impl" ]]; then
  echo "error: missing impl $impl" >&2
  exit 1
fi

if [[ -n "${PYTHON:-}" ]]; then
  py="$PYTHON"
elif [[ -x "$root/.venv/bin/python" ]]; then
  py="$root/.venv/bin/python"
else
  py="python3"
fi

export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH="$root/test${PYTHONPATH:+:$PYTHONPATH}"

args=(--workspace "$workspace" --out-dir "$out_dir")
if [[ -n "$spec" ]]; then
  args+=(--spec "$spec")
fi

echo "export_signoff_csv: workspace=$workspace out_dir=$out_dir"
exec "$py" "$impl" "${args[@]}"
