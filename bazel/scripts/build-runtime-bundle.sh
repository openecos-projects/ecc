#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --autopatch-script <path> --ecc-py <path> --runtime-roots-tar <path> --out-tar <path> --bundle-stage-dir <path>
EOF
}

AUTOPATCH_SCRIPT=""
ECC_PY=""
RUNTIME_ROOTS_TAR=""
OUT_TAR=""
BUNDLE_STAGE_DIR=""
RUNTIME_DIR_IN_EXECROOT="chipcompiler/tools/ecc/bin"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --autopatch-script)
            AUTOPATCH_SCRIPT="$2"
            shift 2
            ;;
        --ecc-py)
            ECC_PY="$2"
            shift 2
            ;;
        --runtime-roots-tar)
            RUNTIME_ROOTS_TAR="$2"
            shift 2
            ;;
        --out-tar)
            OUT_TAR="$2"
            shift 2
            ;;
        --bundle-stage-dir)
            BUNDLE_STAGE_DIR="$2"
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

if [[ -z "$AUTOPATCH_SCRIPT" || -z "$ECC_PY" || -z "$RUNTIME_ROOTS_TAR" || -z "$OUT_TAR" || -z "$BUNDLE_STAGE_DIR" ]]; then
    echo "ERROR: missing required arguments" >&2
    usage >&2
    exit 1
fi

rm -rf "$BUNDLE_STAGE_DIR"
mkdir -p "$BUNDLE_STAGE_DIR/chipcompiler/tools/ecc"

CHIPCOMPILER_PROJECT_ROOT="$PWD" "$AUTOPATCH_SCRIPT" \
    --ecc-py "$ECC_PY" \
    --runtime-roots-tar "$RUNTIME_ROOTS_TAR"

if [[ ! -d "$RUNTIME_DIR_IN_EXECROOT" ]]; then
    echo "ERROR: expected runtime dir not found after autopatch: $RUNTIME_DIR_IN_EXECROOT" >&2
    exit 1
fi

cp -a "$RUNTIME_DIR_IN_EXECROOT" "$BUNDLE_STAGE_DIR/chipcompiler/tools/ecc/"
mkdir -p "$(dirname "$OUT_TAR")"
tar -cf "$OUT_TAR" -C "$BUNDLE_STAGE_DIR" .

