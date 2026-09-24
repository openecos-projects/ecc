#!/usr/bin/env bash
# Run signoff CSV lit gates using Nix-provided lit + FileCheck (LLVM 23).
# Does not use PyPI lit/filecheck. Expects chipcompiler on PYTHONPATH / .venv
# (CI Test job already ran setup-python-deps).
#
# Usage: bash nix/scripts/signoff_lit_nix.sh [lit-args...]
# Env:
#   ECC_REPO_ROOT, PYTHON, ECC_* (see signoff_lit.sh)
#   NIXPKGS_REF  override flake ref (default: pinned rev with llvmPackages_23)

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export ECC_REPO_ROOT="${ECC_REPO_ROOT:-$root}"
cd "$ECC_REPO_ROOT"

export HOME="${HOME:-/root}"
export USER="${USER:-$(id -un 2>/dev/null || echo root)}"
export PATH="${HOME}/.nix-profile/bin:${PATH}"

# shellcheck disable=SC1091
if [[ -f "${HOME}/.nix-profile/etc/profile.d/nix.sh" ]]; then
  # shellcheck source=/dev/null
  . "${HOME}/.nix-profile/etc/profile.d/nix.sh"
  export PATH="${HOME}/.nix-profile/bin:${PATH}"
elif [[ -f /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]]; then
  # shellcheck source=/dev/null
  . /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
fi

if ! command -v nix >/dev/null 2>&1; then
  echo "error: nix not found on PATH (install Nix first)" >&2
  exit 1
fi

# Locked nixpkgs rev (llvmPackages_23 / FileCheck). Keep in sync with local docs if you change it.
NIXPKGS_REF="${NIXPKGS_REF:-github:NixOS/nixpkgs/44a91898084f46797b5fac650c7e8c9ac38c43d4}"
if [[ -x "$ECC_REPO_ROOT/.venv/bin/python" ]]; then
  export PYTHON="${PYTHON:-$ECC_REPO_ROOT/.venv/bin/python}"
fi

inner="$ECC_REPO_ROOT/nix/scripts/signoff_lit_nix_inner.sh"

echo "nix shell ${NIXPKGS_REF}#lit + #llvmPackages_23.libllvm + #jq → signoff_lit.sh"
# FileCheck from llvmPackages_23.libllvm; lit from nixpkgs lit.
exec nix shell \
  --extra-experimental-features 'nix-command flakes' \
  "${NIXPKGS_REF}#lit" \
  "${NIXPKGS_REF}#llvmPackages_23.libllvm" \
  "${NIXPKGS_REF}#jq" \
  --command bash "$inner" "$@"
