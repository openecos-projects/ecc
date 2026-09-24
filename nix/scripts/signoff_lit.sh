#!/usr/bin/env bash
# Run lit against a lit suite directory (one containing lit.cfg.py), e.g. an
# ecc-ci-designs checkout. lit suites carry their own config and cases.
# Usage: signoff_lit.sh SUITE_DIR [lit-args...]
# Env: ECC_REPO_ROOT, PYTHON, FILECHECK, LIT,
#      ECC_EXPORT_SIGNOFF_CSV, ECC_SIGNOFF_CSV_SPEC

set -euo pipefail

root="${ECC_REPO_ROOT:-$PWD}"
export ECC_REPO_ROOT="$root"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ECC_EXPORT_SIGNOFF_CSV="${ECC_EXPORT_SIGNOFF_CSV:-$here/export_signoff_csv.sh}"
# Prefer LLVM FileCheck from nix; lit from nixpkgs `lit` (or llvm-lit if present).
if [[ -z "${FILECHECK:-}" ]]; then
  if command -v FileCheck >/dev/null 2>&1; then
    FILECHECK=$(command -v FileCheck)
  else
    FILECHECK=filecheck
  fi
fi
if [[ -z "${LIT:-}" ]]; then
  if command -v lit >/dev/null 2>&1; then
    LIT=$(command -v lit)
  elif command -v llvm-lit >/dev/null 2>&1; then
    LIT=$(command -v llvm-lit)
  else
    LIT=lit
  fi
fi
export FILECHECK LIT

if [[ -n "${PYTHON:-}" ]]; then
  py="$PYTHON"
elif [[ -x "$root/.venv/bin/python" ]]; then
  py="$root/.venv/bin/python"
else
  py="python3"
fi
export PYTHON="$py"
# Repo root for chipcompiler; test/lit for csv_gates (CI-only, not product signoff).
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}:$root/test/lit"

if [[ $# -eq 0 ]]; then
  echo "usage: $0 SUITE_DIR [lit-args...]" >&2
  exit 2
fi
if [[ -d "$1" ]]; then
  suite="$(cd "$1" && pwd)"
elif [[ -d "$root/$1" ]]; then
  suite="$(cd "$root/$1" && pwd)"
else
  echo "error: no such suite directory: $1" >&2
  exit 1
fi
shift
if [[ ! -f "$suite/lit.cfg.py" ]]; then
  echo "error: missing lit.cfg.py under $suite" >&2
  exit 1
fi

exec "$LIT" -v "$suite" "$@"
