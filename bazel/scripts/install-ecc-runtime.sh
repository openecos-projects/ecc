#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --autopatch-script <path> --ecc-py-cmake <path>... --auto-patchelf-bin <path> --patchelf <path>
EOF
}

AUTOPATCH_SCRIPT=""
ECC_PY_CMAKE=""
AUTO_PATCHELF_BIN=""
PATCHELF=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --autopatch-script)
            AUTOPATCH_SCRIPT="$2"
            shift 2
            ;;
        --ecc-py-cmake)
            shift
            # Consume all paths until next flag, take the lib dir
            while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                ECC_PY_CMAKE="$1"
                shift
            done
            ;;
        --auto-patchelf-bin)
            AUTO_PATCHELF_BIN="$2"
            shift 2
            ;;
        --patchelf)
            PATCHELF="$2"
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

if [[ -z "$AUTOPATCH_SCRIPT" || -z "$ECC_PY_CMAKE" || -z "$AUTO_PATCHELF_BIN" || -z "$PATCHELF" ]]; then
    echo "ERROR: missing required arguments" >&2
    usage >&2
    exit 1
fi

# Resolve paths relative to runfiles
SCRIPT_LINK="$0"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_LINK")" && pwd)"
RUNFILES_DIR="$SCRIPT_DIR/$(basename "$SCRIPT_LINK").runfiles/_main"

resolve_path() {
    local p="$1"
    if [[ "$p" = /* ]]; then
        echo "$p"
    else
        echo "$RUNFILES_DIR/$p"
    fi
}

AUTOPATCH_SCRIPT="$(resolve_path "$AUTOPATCH_SCRIPT")"
ECC_PY_CMAKE="$(resolve_path "$ECC_PY_CMAKE")"
AUTO_PATCHELF_BIN="$(resolve_path "$AUTO_PATCHELF_BIN")"
PATCHELF="$(resolve_path "$PATCHELF")"

WORKSPACE_DIR="${BUILD_WORKSPACE_DIRECTORY:-$PWD}"
DST="$WORKSPACE_DIR/chipcompiler/tools/ecc/bin"
mkdir -p "$DST/lib"

# Copy ecc_py .so from cmake output lib/ dir
find -L "$ECC_PY_CMAKE" -name 'ecc_py*.so' -exec cp -f {} "$DST/" \;
chmod u+w "$DST"/ecc_py*.so

# Run autopatch to bundle dependencies and fix RPATHs
export CHIPCOMPILER_PROJECT_ROOT="$WORKSPACE_DIR"
export AUTO_PATCHELF_BIN
export PATH="$(dirname "$PATCHELF"):$PATH"
bash "$AUTOPATCH_SCRIPT" --ecc-py "$DST" --runtime-lib-path "$ECC_PY_CMAKE"

echo "ECC runtime installed to: $DST"
