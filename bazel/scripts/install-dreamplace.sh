#!/usr/bin/env bash
# Install DreamPlace Bazel build artifacts into the source tree for dev use.
# Usage: bazel run //bazel/scripts:install_dreamplace
set -euo pipefail

WS="${BUILD_WORKSPACE_DIRECTORY:?Must run via: bazel run //bazel/scripts:install_dreamplace}"
DREAMPLACE_ROOT="${WS}/chipcompiler/thirdparty/ecc-dreamplace"

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

# Copy .so files into the correct ops/ subdirectories
find "${DREAMPLACE_DIR}/ops" -name '*.so' | while read -r so_file; do
    rel="${so_file#"${DREAMPLACE_DIR}/"}"
    dest="${DREAMPLACE_ROOT}/dreamplace/${rel}"
    mkdir -p "$(dirname "${dest}")"
    cp -f "${so_file}" "${dest}"
    echo "  Installed: dreamplace/${rel}"
done

# Copy generated configure.py
if [[ -f "${DREAMPLACE_DIR}/configure.py" ]]; then
    cp -f "${DREAMPLACE_DIR}/configure.py" "${DREAMPLACE_ROOT}/dreamplace/configure.py"
    echo "  Installed: dreamplace/configure.py"
fi

SO_COUNT=$(find "${DREAMPLACE_ROOT}/dreamplace/ops" -name '*.so' | wc -l)
echo "Done. ${SO_COUNT} .so files installed to source tree."
