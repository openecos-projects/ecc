#!/usr/bin/env bash
# CI/local entry: run test/lit/project with nix-provided lit + FileCheck.
# Usage: bash nix/scripts/ci_project_lit.sh [lit-args...]
# Env: CHIPCOMPILER_ICS55_PDK_ROOT (required), ECC_REPO_ROOT, ECC, PYTHON
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export ECC_REPO_ROOT="${ECC_REPO_ROOT:-$root}"
cd "$ECC_REPO_ROOT"

: "${CHIPCOMPILER_ICS55_PDK_ROOT:?CHIPCOMPILER_ICS55_PDK_ROOT is required}"

export USER="${USER:-$(id -un 2>/dev/null || echo root)}"
if [[ "$(id -u)" -eq 0 ]]; then
  export HOME=/root
else
  export HOME="${HOME:-/home/${USER}}"
fi
export PATH="${HOME}/.nix-profile/bin:${PATH}"

# shellcheck disable=SC1091
if [[ -f "${HOME}/.nix-profile/etc/profile.d/nix.sh" ]]; then
  # shellcheck source=/dev/null
  . "${HOME}/.nix-profile/etc/profile.d/nix.sh"
  export PATH="${HOME}/.nix-profile/bin:${PATH}"
fi

if ! command -v nix >/dev/null 2>&1; then
  bash "$ECC_REPO_ROOT/nix/scripts/ci_install_nix.sh"
  export PATH="${HOME}/.nix-profile/bin:${PATH}"
fi

if [[ -x "$ECC_REPO_ROOT/.venv/bin/python" ]]; then
  export PYTHON="${PYTHON:-$ECC_REPO_ROOT/.venv/bin/python}"
fi
if [[ -x "$ECC_REPO_ROOT/.venv/bin/ecc" ]]; then
  export ECC="${ECC:-$ECC_REPO_ROOT/.venv/bin/ecc}"
fi

# Prefer the flake app (pins lit/FileCheck with the repo).
# Only fall back when the *build* fails — lit test failures must not re-run.
if nix build -L --no-link .#signoff-lit; then
  nix run -L .#signoff-lit -- test/lit/project "$@"
  exit $?
fi

echo "flake signoff-lit build failed; falling back to nixpkgs shell" >&2
# Match flake.nix nixpkgs pin (llvmPackages_21 FileCheck).
NIXPKGS_REF="${NIXPKGS_REF:-github:NixOS/nixpkgs/f4b140d5b253f5e2a1ff4e5506edbf8267724bde}"
exec nix shell \
  --extra-experimental-features 'nix-command flakes' \
  "${NIXPKGS_REF}#lit" \
  "${NIXPKGS_REF}#llvmPackages_21.llvm" \
  --command bash "$ECC_REPO_ROOT/nix/scripts/signoff-lit.sh" test/lit/project "$@"
