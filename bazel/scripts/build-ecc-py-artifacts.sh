#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --src-root <path> --rule-out-root <path> [--python-bin <path>]
EOF
}

SRC_ROOT=""
RULE_OUT_ROOT=""
PYTHON_BIN=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --src-root)
            SRC_ROOT="$2"
            shift 2
            ;;
        --rule-out-root)
            RULE_OUT_ROOT="$2"
            shift 2
            ;;
        --python-bin)
            PYTHON_BIN="$2"
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

if [[ -z "$SRC_ROOT" || -z "$RULE_OUT_ROOT" ]]; then
    echo "ERROR: missing required arguments" >&2
    usage >&2
    exit 1
fi

if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="${CHIPCOMPILER_PYTHON:-$(command -v python3 || true)}"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python interpreter not found. Set CHIPCOMPILER_PYTHON or pass --python-bin." >&2
    exit 1
fi

OUT_DIR="$RULE_OUT_ROOT/ecc_py_build"
BUILD_DIR="$RULE_OUT_ROOT/ecc_py_build_tmp"
RUNTIME_STAGE_DIR="$RULE_OUT_ROOT/ecc_runtime_roots"
OUT_ECC_PY="$OUT_DIR/ecc_py.so"
OUT_RUNTIME_TAR="$OUT_DIR/runtime_roots.tar"

mkdir -p "$OUT_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
rm -rf "$RUNTIME_STAGE_DIR"
mkdir -p "$RUNTIME_STAGE_DIR"

CMAKE_GEN_ARGS=()
if command -v ninja >/dev/null 2>&1; then
    CMAKE_GEN_ARGS=(-G Ninja)
fi

CMAKE_PREFIX_ARGS=()
if [[ -n "${CMAKE_PREFIX_PATH:-}" ]]; then
    CMAKE_PREFIX_ARGS+=("-DCMAKE_PREFIX_PATH=${CMAKE_PREFIX_PATH}")
fi

cmake "${CMAKE_GEN_ARGS[@]}" -S "$SRC_ROOT" -B "$BUILD_DIR" \
    -DBUILD_AIEDA=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DPython_EXECUTABLE="$PYTHON_BIN" \
    -DPython3_EXECUTABLE="$PYTHON_BIN" \
    -DPYTHON_EXECUTABLE="$PYTHON_BIN" \
    "${CMAKE_PREFIX_ARGS[@]}"

cmake --build "$BUILD_DIR" --target ecc_py --parallel

search_dirs=()
if [[ -d "$SRC_ROOT/bin" ]]; then
    search_dirs+=("$SRC_ROOT/bin")
fi
if [[ -d "$BUILD_DIR/bin" ]]; then
    search_dirs+=("$BUILD_DIR/bin")
fi
if [[ ${#search_dirs[@]} -eq 0 ]]; then
    echo "ERROR: ecc_py build succeeded but no bin directory was found." >&2
    exit 1
fi

ECC_PY_SO="$(find "${search_dirs[@]}" -maxdepth 2 -type f -name 'ecc_py*.so' | head -n 1 || true)"
if [[ -z "$ECC_PY_SO" ]]; then
    echo "ERROR: ecc_py build succeeded but ecc_py*.so was not found." >&2
    exit 1
fi

cp -f "$ECC_PY_SO" "$OUT_ECC_PY"

mkdir -p "$RUNTIME_STAGE_DIR/build"
cp -a "$BUILD_DIR/." "$RUNTIME_STAGE_DIR/build/"
tar -cf "$OUT_RUNTIME_TAR" -C "$RUNTIME_STAGE_DIR" .

