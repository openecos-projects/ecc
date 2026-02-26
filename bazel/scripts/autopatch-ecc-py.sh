#!/usr/bin/env bash
# Bundle ecc_py runtime dependencies using auto-patchelf
set -euo pipefail

PROJECT_ROOT="${CHIPCOMPILER_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
ECC_PY_DST="$PROJECT_ROOT/chipcompiler/tools/ecc/bin"
ECC_LIB_DST="$ECC_PY_DST/lib"

ecc_py_dir="" runtime_lib_path=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --ecc-py) ecc_py_dir="$2"; shift 2 ;;
        --runtime-lib-path) runtime_lib_path="$2"; shift 2 ;;
        *) echo "ERROR: unknown arg: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$ECC_LIB_DST"

# Copy .so files
find -L "${ecc_py_dir:-.}" -maxdepth 1 -name 'ecc_py*.so' -exec cp -f {} "$ECC_PY_DST/" \; 2>/dev/null || true
[[ -n "$runtime_lib_path" ]] && find -L "$runtime_lib_path" -maxdepth 1 -name '*.so' ! -name 'ecc_py*.so' -exec cp -f {} "$ECC_LIB_DST/" \; 2>/dev/null || true
chmod -R u+w "$ECC_PY_DST" 2>/dev/null || true

# Run auto-patchelf
search_paths=("$ECC_LIB_DST" /lib /lib64 /usr/lib /usr/lib64 /lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu)
"${AUTO_PATCHELF_BIN:-auto-patchelf}" --no-recurse --ignore-missing --paths "$ECC_PY_DST" "$ECC_LIB_DST" --libs "${search_paths[@]}"

# Set RUNPATH
find "$ECC_PY_DST" -maxdepth 1 -name 'ecc_py*.so' -exec patchelf --set-rpath '$ORIGIN:$ORIGIN/lib' {} \;
find "$ECC_LIB_DST" -maxdepth 1 -name '*.so' -exec patchelf --set-rpath '$ORIGIN' {} \; 2>/dev/null || true

echo "[bundle] done"
