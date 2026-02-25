#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --autopatch-script <path> --ecc-py <path> --runtime-roots-tar <path>
EOF
}

AUTOPATCH_SCRIPT=""
ECC_PY=""
RUNTIME_ROOTS_TAR=""

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

if [[ -z "$AUTOPATCH_SCRIPT" || -z "$ECC_PY" || -z "$RUNTIME_ROOTS_TAR" ]]; then
    echo "ERROR: missing required arguments" >&2
    usage >&2
    exit 1
fi

WORKSPACE_DIR="${BUILD_WORKSPACE_DIRECTORY:-$PWD}"

CHIPCOMPILER_PROJECT_ROOT="$WORKSPACE_DIR" "$AUTOPATCH_SCRIPT" \
    --ecc-py "$ECC_PY" \
    --runtime-roots-tar "$RUNTIME_ROOTS_TAR"

echo "ECC runtime installed to: $WORKSPACE_DIR/chipcompiler/tools/ecc/bin"

