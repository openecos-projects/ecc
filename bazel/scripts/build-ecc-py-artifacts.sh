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
if [[ -d "$BUILD_DIR/bin" ]]; then
    search_dirs+=("$BUILD_DIR/bin")
fi
if [[ -d "$SRC_ROOT/bin" ]]; then
    search_dirs+=("$SRC_ROOT/bin")
fi
if [[ ${#search_dirs[@]} -eq 0 ]]; then
    echo "ERROR: ecc_py build succeeded but no bin directory was found." >&2
    exit 1
fi

PY_MM="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')"
PY_TAG_CP="cp${PY_MM}"
PY_TAG_CPYTHON="cpython-${PY_MM}"

ecc_py_candidates=()
for dir in "${search_dirs[@]}"; do
    mapfile -t dir_candidates < <(find "$dir" -maxdepth 2 -type f -name 'ecc_py*.so' | sort)
    if [[ ${#dir_candidates[@]} -gt 0 ]]; then
        ecc_py_candidates+=("${dir_candidates[@]}")
    fi
done

ECC_PY_SO=""
for candidate in "${ecc_py_candidates[@]}"; do
    base_name="$(basename "$candidate")"
    if [[ "$base_name" == *"$PY_TAG_CP"* || "$base_name" == *"$PY_TAG_CPYTHON"* ]]; then
        ECC_PY_SO="$candidate"
        break
    fi
done
if [[ -z "$ECC_PY_SO" && ${#ecc_py_candidates[@]} -eq 1 ]]; then
    ECC_PY_SO="${ecc_py_candidates[0]}"
fi
if [[ -z "$ECC_PY_SO" ]]; then
    if [[ ${#ecc_py_candidates[@]} -eq 0 ]]; then
        echo "ERROR: ecc_py build succeeded but ecc_py*.so was not found." >&2
    else
        echo "ERROR: no ecc_py binary matched Python ABI ${PY_TAG_CPYTHON}/${PY_TAG_CP}." >&2
        echo "Candidates:" >&2
        printf '  - %s\n' "${ecc_py_candidates[@]}" >&2
    fi
    exit 1
fi

echo "INFO: selected ecc_py binary for Python ABI ${PY_TAG_CPYTHON}/${PY_TAG_CP}: $ECC_PY_SO"
cp -f "$ECC_PY_SO" "$OUT_ECC_PY"

mkdir -p "$RUNTIME_STAGE_DIR/build"
cp -a "$BUILD_DIR/." "$RUNTIME_STAGE_DIR/build/"
tar -cf "$OUT_RUNTIME_TAR" -C "$RUNTIME_STAGE_DIR" .
