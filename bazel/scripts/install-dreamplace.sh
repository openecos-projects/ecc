#!/usr/bin/env bash
# Install DreamPlace Bazel build artifacts into the source tree for dev use.
# Usage: bazel run //bazel/scripts:install_dreamplace
#        bazel run //bazel/scripts:install_dreamplace -- --clean
set -euo pipefail

WS="${BUILD_WORKSPACE_DIRECTORY:?Must run via: bazel run //bazel/scripts:install_dreamplace}"
DREAMPLACE_ROOT="${WS}/chipcompiler/thirdparty/ecc-dreamplace"
MANIFEST="${DREAMPLACE_ROOT}/dreamplace/.install_manifest.txt"

# Handle --clean: remove only files listed in the manifest.
if [[ "${1:-}" == "--clean" ]]; then
    if [[ ! -f "${MANIFEST}" ]]; then
        echo "Nothing to clean (no install manifest found)."
        exit 0
    fi
    echo "Cleaning installed DreamPlace artifacts..."
    count=0
    while IFS= read -r file; do
        if [[ -f "${DREAMPLACE_ROOT}/dreamplace/${file}" ]]; then
            rm -f "${DREAMPLACE_ROOT}/dreamplace/${file}"
            echo "  Removed: dreamplace/${file}"
            ((count++)) || true
        fi
    done < "${MANIFEST}"
    # Remove empty directories left behind
    find "${DREAMPLACE_ROOT}/dreamplace/ops" -type d -empty -delete 2>/dev/null || true
    rm -f "${MANIFEST}"
    echo "Done. Removed ${count} files."
    exit 0
fi

# $(locations ...) passes multiple paths; find the one ending in /dreamplace
RF="${RUNFILES_DIR:-${BASH_SOURCE[0]}.runfiles}"
DREAMPLACE_DIR=""
for arg in "$@"; do
    if [[ "$arg" == */dreamplace && -d "$RF/_main/$arg" ]]; then
        DREAMPLACE_DIR="$RF/_main/$arg"
        break
    fi
done

if [[ -z "${DREAMPLACE_DIR}" ]]; then
    echo "ERROR: Could not locate dreamplace output directory in args: $*" >&2
    exit 1
fi

echo "Bazel output: ${DREAMPLACE_DIR}"
echo "Installing to: ${DREAMPLACE_ROOT}/dreamplace/"

# Clear previous manifest
: > "${MANIFEST}"

# Copy .so files into the correct ops/ subdirectories
find "${DREAMPLACE_DIR}/ops" -name '*.so' | while read -r so_file; do
    rel="${so_file#"${DREAMPLACE_DIR}/"}"
    dest="${DREAMPLACE_ROOT}/dreamplace/${rel}"
    mkdir -p "$(dirname "${dest}")"
    cp -f --no-preserve=ownership "${so_file}" "${dest}"
    echo "${rel}" >> "${MANIFEST}"
    echo "  Installed: dreamplace/${rel}"
done

# Copy generated configure.py
if [[ -f "${DREAMPLACE_DIR}/configure.py" ]]; then
    cp -f --no-preserve=ownership "${DREAMPLACE_DIR}/configure.py" "${DREAMPLACE_ROOT}/dreamplace/configure.py"
    echo "configure.py" >> "${MANIFEST}"
    echo "  Installed: dreamplace/configure.py"
fi

SO_COUNT=$(grep -c '\.so$' "${MANIFEST}" || true)
echo "Done. ${SO_COUNT} .so files installed to source tree."
