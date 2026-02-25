#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --gui-src-dir <dir> --api-server-bin <path> --out-tar <path> --work-root <dir>
EOF
}

GUI_SRC_DIR=""
API_SERVER_BIN=""
OUT_TAR=""
WORK_ROOT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --gui-src-dir)
            GUI_SRC_DIR="$2"
            shift 2
            ;;
        --api-server-bin)
            API_SERVER_BIN="$2"
            shift 2
            ;;
        --out-tar)
            OUT_TAR="$2"
            shift 2
            ;;
        --work-root)
            WORK_ROOT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$GUI_SRC_DIR" || -z "$API_SERVER_BIN" || -z "$OUT_TAR" || -z "$WORK_ROOT" ]]; then
    echo "ERROR: missing required arguments" >&2
    usage >&2
    exit 1
fi

API_SERVER_BIN="$(readlink -f "$API_SERVER_BIN")"
TARGET_TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
GUI_DIR="$WORK_ROOT/gui"

if [[ ! -f "$API_SERVER_BIN" ]]; then
    echo "ERROR: api server binary not found: $API_SERVER_BIN" >&2
    exit 1
fi
if [[ -z "$TARGET_TRIPLE" ]]; then
    echo "ERROR: failed to resolve rust target triple from rustc -vV" >&2
    exit 1
fi

rm -rf "$WORK_ROOT"
mkdir -p "$GUI_DIR"

# Bazel sandbox exposes source files as symlinks. Vite/Rollup may resolve
# realpaths outside the workspace root and reject emitted asset names.
# Copy with dereference to build from a physical tree.
cp -RL "$GUI_SRC_DIR/." "$GUI_DIR/"

mkdir -p "$GUI_DIR/src-tauri/binaries"
cp -f "$API_SERVER_BIN" "$GUI_DIR/src-tauri/binaries/api-server-$TARGET_TRIPLE"
chmod +x "$GUI_DIR/src-tauri/binaries/api-server-$TARGET_TRIPLE"

export TAURI_API_SERVER_BIN="$API_SERVER_BIN"
TAURI_BUNDLES="${TAURI_BUNDLES:-deb,appimage}"
export APPIMAGE_EXTRACT_AND_RUN="${APPIMAGE_EXTRACT_AND_RUN:-1}"
echo "[bundle] tauri bundles: $TAURI_BUNDLES"

(cd "$GUI_DIR" && pnpm install --frozen-lockfile && pnpm exec tauri build --verbose --bundles "$TAURI_BUNDLES")

BUNDLE_DIR="$GUI_DIR/src-tauri/target/release/bundle"
if [[ ! -d "$BUNDLE_DIR" ]]; then
    echo "ERROR: Tauri bundle directory not found: $BUNDLE_DIR" >&2
    exit 1
fi

if ! find "$BUNDLE_DIR" -mindepth 1 -type f -print -quit | grep -q .; then
    echo "ERROR: Tauri bundle directory is empty: $BUNDLE_DIR" >&2
    find "$GUI_DIR/src-tauri/target" -maxdepth 5 -mindepth 1 -print >&2 || true
    exit 1
fi

mkdir -p "$(dirname "$OUT_TAR")"
tar -cf "$OUT_TAR" -C "$BUNDLE_DIR" .
