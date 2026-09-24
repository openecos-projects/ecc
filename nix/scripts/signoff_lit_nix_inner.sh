#!/usr/bin/env bash
# Invoked inside `nix shell …#lit …#llvmPackages_23.libllvm …#jq`.
# Resolves lit / FileCheck then runs signoff_lit.sh.
set -euo pipefail

root="${ECC_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export ECC_REPO_ROOT="$root"

export LIT="${LIT:-$(command -v lit || true)}"
export FILECHECK="${FILECHECK:-$(command -v FileCheck || true)}"

if [[ -z "${LIT}" || -z "${FILECHECK}" ]]; then
  echo "error: lit or FileCheck missing from nix shell PATH" >&2
  echo "PATH=$PATH" >&2
  exit 1
fi

echo "LIT=$LIT"
echo "FILECHECK=$FILECHECK"
exec bash "$root/nix/scripts/signoff_lit.sh" "$@"
