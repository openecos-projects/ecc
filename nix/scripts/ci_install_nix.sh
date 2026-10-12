#!/usr/bin/env bash
# Install Nix in the CI container when missing (manylinux has no Nix by default).
# Single-user / --no-daemon: GHA manylinux runs as root without sudo/systemd/nixbld.
#
# Usage: bash nix/scripts/ci_install_nix.sh
set -euo pipefail

export USER="${USER:-$(id -un 2>/dev/null || echo root)}"
if [[ "$(id -u)" -eq 0 ]]; then
  export HOME=/root
else
  export HOME="${HOME:-/home/${USER}}"
fi

nix_profile_bin="${HOME}/.nix-profile/bin"
if [[ -x "${nix_profile_bin}/nix" ]]; then
  export PATH="${nix_profile_bin}:${PATH}"
fi

if command -v nix >/dev/null 2>&1; then
  echo "nix already on PATH: $(command -v nix)"
  nix --version
  exit 0
fi

if command -v yum >/dev/null 2>&1; then
  yum install -y curl tar xz gzip bzip2 ca-certificates shadow-utils >/dev/null || true
elif command -v microdnf >/dev/null 2>&1; then
  microdnf install -y curl tar xz gzip bzip2 ca-certificates shadow-utils >/dev/null || true
fi

if [[ ! -d /nix ]]; then
  if [[ "$(id -u)" -eq 0 ]]; then
    mkdir -m 0755 /nix
  else
    echo "error: /nix missing and not root; cannot create store directory" >&2
    exit 1
  fi
fi

mkdir -p /etc/nix "${HOME}/.config/nix"
for conf in /etc/nix/nix.conf "${HOME}/.config/nix/nix.conf"; do
  if [[ ! -f "$conf" ]] || ! grep -q '^build-users-group' "$conf"; then
    {
      echo 'build-users-group ='
      echo 'experimental-features = nix-command flakes'
    } >>"$conf"
  fi
done

echo "Installing Nix (no-daemon) as ${USER} HOME=${HOME}…"
curl -fsSL https://nixos.org/nix/install | sh -s -- --no-daemon --yes

export PATH="${HOME}/.nix-profile/bin:${PATH}"
# shellcheck disable=SC1091
if [[ -f "${HOME}/.nix-profile/etc/profile.d/nix.sh" ]]; then
  # shellcheck source=/dev/null
  . "${HOME}/.nix-profile/etc/profile.d/nix.sh"
  export PATH="${HOME}/.nix-profile/bin:${PATH}"
fi

if ! command -v nix >/dev/null 2>&1; then
  echo "error: nix install finished but nix is not on PATH" >&2
  exit 1
fi

nix --version
