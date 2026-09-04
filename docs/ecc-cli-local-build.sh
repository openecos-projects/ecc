#!/usr/bin/env bash
# Build the local ECC CLI PyInstaller bundle in the same format as the release.
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
readonly DIST_DIR="$REPO_DIR/dist"
readonly BUNDLE_DIR="$DIST_DIR/ecc"
readonly RELEASE_DIR="$DIST_DIR/release"
readonly ARCHIVE_NAME="ecc-cli-linux-x86_64.tar.gz"
readonly ARCHIVE_PATH="$RELEASE_DIR/$ARCHIVE_NAME"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

if (( $# != 0 )); then
  die "usage: $(basename "$0")"
fi

[[ "$(uname -s)" == "Linux" ]] || die "the release archive is supported only on Linux"
[[ "$(uname -m)" == "x86_64" ]] || die "the release archive requires x86_64"
command -v uv >/dev/null || die "uv is required"
command -v tar >/dev/null || die "tar is required"
command -v gzip >/dev/null || die "gzip is required"
[[ -f "$REPO_DIR/ecc.spec" ]] || die "ecc.spec not found under $REPO_DIR"

umask 022

printf 'Building PyInstaller bundle from %s\n' "$REPO_DIR"
(
  cd "$REPO_DIR"
  ECOS_PYINSTALLER_MODE=onedir uv run --no-sync --managed-python \
    pyinstaller ecc.spec --clean --noconfirm
)

[[ -x "$BUNDLE_DIR/ecc" ]] || die "PyInstaller did not create $BUNDLE_DIR/ecc"
[[ -d "$BUNDLE_DIR/_internal" ]] || die "PyInstaller did not create $BUNDLE_DIR/_internal"
[[ -x "$BUNDLE_DIR/_internal/torch/bin/torch_shm_manager" ]] || \
  die "PyInstaller bundle is missing torch_shm_manager"

mkdir -p "$RELEASE_DIR"
TEMP_DIR="$(mktemp -d "$RELEASE_DIR/.ecc-cli-local-build.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT

TAR_PATH="$TEMP_DIR/ecc.tar"
STAGED_ARCHIVE="$TEMP_DIR/$ARCHIVE_NAME"
SMOKE_DIR="$TEMP_DIR/smoke"

tar -cf "$TAR_PATH" -C "$BUNDLE_DIR" .
gzip -n -9 -c "$TAR_PATH" > "$STAGED_ARCHIVE"

mkdir -p "$SMOKE_DIR"
tar -xzf "$STAGED_ARCHIVE" -C "$SMOKE_DIR"
"$SMOKE_DIR/ecc" --help >/dev/null
"$SMOKE_DIR/ecc" --version >/dev/null
"$SMOKE_DIR/ecc" version --json >/dev/null
[[ -x "$SMOKE_DIR/_internal/torch/bin/torch_shm_manager" ]] || \
  die "smoke test bundle is missing torch_shm_manager"

mv -f "$STAGED_ARCHIVE" "$ARCHIVE_PATH"
printf 'Built %s\n' "$ARCHIVE_PATH"
if command -v sha256sum >/dev/null; then
  sha256sum "$ARCHIVE_PATH"
fi
