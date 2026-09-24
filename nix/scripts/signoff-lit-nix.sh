#!/usr/bin/env bash
# Run a lit suite using Nix-provided lit + FileCheck (llvmPackages_21).
# Usage: bash nix/scripts/signoff-lit-nix.sh SUITE_DIR [lit-args...]
# Env: ECC_REPO_ROOT, PYTHON, ECC_* (see signoff-lit.sh);
#      NIXPKGS_REF  override the nixpkgs flake ref (default: flake.lock's rev)

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export ECC_REPO_ROOT="${ECC_REPO_ROOT:-$root}"
cd "$ECC_REPO_ROOT"

# Locked to the same nixpkgs rev as flake.lock (llvmPackages_21 / FileCheck).
NIXPKGS_REF="${NIXPKGS_REF:-github:NixOS/nixpkgs/f4b140d5b253f5e2a1ff4e5506edbf8267724bde}"

exec nix shell \
  --extra-experimental-features 'nix-command flakes' \
  "${NIXPKGS_REF}#lit" \
  "${NIXPKGS_REF}#llvmPackages_21.libllvm" \
  "${NIXPKGS_REF}#jq" \
  --command bash nix/scripts/signoff-lit.sh "$@"
