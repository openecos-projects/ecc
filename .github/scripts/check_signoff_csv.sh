#!/usr/bin/env bash
# Check (consume) an exported signoff CSV projection with FileCheck.
#
# Operations:
#   1. Require --input (metrics.check.txt) and --check (FileCheck contract)
#   2. Run filecheck; non-zero fails CI
#
# Usage:
#   check_signoff_csv.sh --input FILE --check FILE
#
# Env:
#   FILECHECK   filecheck binary (default: filecheck)

set -euo pipefail

usage() {
  cat <<'EOF'
Check (consume) an exported signoff CSV projection with FileCheck.

Operations:
  1. Require --input (metrics.check.txt) and --check (FileCheck contract)
  2. Run filecheck; non-zero fails CI

Usage:
  check_signoff_csv.sh --input FILE --check FILE

Env:
  FILECHECK   filecheck binary (default: filecheck)
EOF
  exit 2
}

input=""
check=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      input="${2:?}"
      shift 2
      ;;
    --check)
      check="${2:?}"
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

if [[ -z "$input" || -z "$check" ]]; then
  echo "error: --input and --check are required" >&2
  usage
fi

if [[ ! -f "$input" ]]; then
  echo "error: input missing: $input" >&2
  exit 1
fi
if [[ ! -f "$check" ]]; then
  echo "error: check missing: $check" >&2
  exit 1
fi

fc="${FILECHECK:-filecheck}"
if ! command -v "$fc" >/dev/null 2>&1; then
  echo "error: filecheck not found (FILECHECK=$fc)" >&2
  exit 1
fi

echo "check_signoff_csv: input=$input check=$check"
exec "$fc" --input-file="$input" "$check"
