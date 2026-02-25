#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

if [[ "${ENABLE_ICS55_PDK_DOWNLOAD:-false}" == "true" ]]; then
    bazel run //scripts:init_ics55_pdk
fi

bazel build //:release_bundle

echo "Bazel build complete."
echo "Release bundle: $PROJECT_ROOT/bazel-bin/tauri_bundle/tauri_bundle.tar"
echo "Install ECC runtime (optional): bazel run //chipcompiler/thirdparty:install_ecc_runtime"

