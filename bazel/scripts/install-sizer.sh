#!/usr/bin/env bash
# Install ECC-Sizer Bazel build artifacts into the source tree for dev use.
# Usage: bazel run //bazel/scripts:install_sizer
#        bazel run //bazel/scripts:install_sizer -- --clean
set -euo pipefail

WS="${BUILD_WORKSPACE_DIRECTORY:?Must run via: bazel run //bazel/scripts:install_sizer}"
SIZER_RUNTIME_DIR="${WS}/chipcompiler/tools/ecc_sizer/bin"
MANIFEST="${SIZER_RUNTIME_DIR}/.install_manifest.txt"

if [[ "${1:-}" == "--clean" ]]; then
    if [[ ! -f "${MANIFEST}" ]]; then
        echo "Nothing to clean (no install manifest found)."
        exit 0
    fi
    echo "Cleaning installed ECC-Sizer artifacts..."
    while IFS= read -r file; do
        rm -f "${SIZER_RUNTIME_DIR}/${file}"
        echo "  Removed: chipcompiler/tools/ecc_sizer/bin/${file}"
    done < "${MANIFEST}"
    rm -f "${MANIFEST}"
    rmdir "${SIZER_RUNTIME_DIR}" 2>/dev/null || true
    echo "Done."
    exit 0
fi

RF="${RUNFILES_DIR:-${BASH_SOURCE[0]}.runfiles}"
SIZER_BIN=""
for arg in "$@"; do
    for candidate_root in "$arg" "${RF}/_main/${arg}" "${RF}/${arg}"; do
        if [[ -f "${candidate_root}" && "$(basename "${candidate_root}")" == "Sizer" ]]; then
            SIZER_BIN="${candidate_root}"
            break 2
        fi
        if [[ -d "${candidate_root}" ]]; then
            found="$(find "${candidate_root}" -type f -name Sizer -perm /111 -print -quit)"
            if [[ -n "${found}" ]]; then
                SIZER_BIN="${found}"
                break 2
            fi
        fi
    done
done

if [[ -z "${SIZER_BIN}" ]]; then
    echo "ERROR: Could not locate Sizer executable in args: $*" >&2
    exit 1
fi

echo "Bazel output: ${SIZER_BIN}"
echo "Installing to: ${SIZER_RUNTIME_DIR}/"

mkdir -p "${SIZER_RUNTIME_DIR}"
cp -f --no-preserve=ownership "${SIZER_BIN}" "${SIZER_RUNTIME_DIR}/Sizer"
chmod +x "${SIZER_RUNTIME_DIR}/Sizer"
echo "Sizer" > "${MANIFEST}"
echo "Done. Installed chipcompiler/tools/ecc_sizer/bin/Sizer."
