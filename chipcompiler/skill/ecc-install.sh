#!/usr/bin/env bash
set -euo pipefail

url='http://release.openecos.com/installers/ecc/latest/ecc-installer.sh'
with_toolchain=false
allow_http=false
keep=''
extra=()

usage() {
  cat <<'EOF'
Usage: bash ecc-install.sh [options]
  --with-toolchain       Also install OSS CAD Suite and ICS55 PDK.
  --installer-url URL    Use an explicitly reviewed installer URL.
  --allow-insecure-http  Permit the documented http:// release URL.
  --keep-installer FILE  Preserve the downloaded installer at FILE.
  --installer-arg ARG    Pass ARG to the official installer; repeatable.
  -h, --help             Show this help.

The official installer is downloaded to a temporary file before execution.
This wrapper does not use curl | sh, sudo, or modify shell startup files.
EOF
}

while (($#)); do
  case "$1" in
    --with-toolchain) with_toolchain=true ;;
    --installer-url) (($# > 1)) || { echo '--installer-url requires a URL.' >&2; exit 2; }; url="$2"; shift ;;
    --allow-insecure-http) allow_http=true ;;
    --keep-installer) (($# > 1)) || { echo '--keep-installer requires a path.' >&2; exit 2; }; keep="$2"; shift ;;
    --installer-arg) (($# > 1)) || { echo '--installer-arg requires a value.' >&2; exit 2; }; extra+=("$2"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$url" in
  https://*) ;;
  http://*) [[ "$allow_http" == true ]] || { echo 'Refusing http://; use --allow-insecure-http after review.' >&2; exit 1; } ;;
  *) echo 'Installer URL must use http:// or https://.' >&2; exit 2 ;;
esac
command -v curl >/dev/null || { echo 'curl is required.' >&2; exit 1; }

tmp="$(mktemp -d "${TMPDIR:-/tmp}/ecc-install.XXXXXX")"
installer="$tmp/ecc-installer.sh"
cleanup() { [[ -n "$keep" ]] || rm -r -- "$tmp"; }
trap cleanup EXIT

echo "Downloading ECC installer: $url"
curl --fail --location --silent --show-error --proto '=http,https' --output "$installer" "$url"
[[ -s "$installer" ]] || { echo 'Downloaded installer is empty.' >&2; exit 1; }
chmod 700 "$installer"
if [[ -n "$keep" ]]; then
  mkdir -p -- "$(dirname -- "$keep")"
  cp -- "$installer" "$keep"
  chmod 700 "$keep"
  echo "Installer preserved at: $keep"
fi

args=("${extra[@]}")
[[ "$with_toolchain" == true ]] && args+=(--with-toolchain)
sh "$installer" "${args[@]}"

ecc_path="$HOME/.local/bin/ecc"
if [[ -x "$ecc_path" ]]; then
  echo "Installed wrapper: $ecc_path"
  "$ecc_path" --version || true
else
  echo 'Installer completed, but ~/.local/bin/ecc was not found.' >&2
  exit 1
fi
