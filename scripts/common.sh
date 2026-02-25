#!/usr/bin/env bash
#
# Deprecated compatibility layer.
# Build orchestration moved to Bazel targets under BUILD.bazel.
#

setup_project_vars() {
    export PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)}"
    export CHIPCOMPILER_ROOT="${PROJECT_ROOT}/chipcompiler"
    export ICS55_PDK_ROOT="${CHIPCOMPILER_ROOT}/thirdparty/icsprout55-pdk"
}

setup_ics55_pdk() {
    local workspace_dir
    workspace_dir="${PROJECT_ROOT:-${BUILD_WORKSPACE_DIRECTORY:-$PWD}}"
    BUILD_WORKSPACE_DIRECTORY="$workspace_dir" "${workspace_dir}/bazel/scripts/init-ics55-pdk.sh"
}

_deprecated() {
    local fn_name="$1"
    echo "ERROR: ${fn_name} is deprecated. Use Bazel targets instead." >&2
    echo "Try: bazel build //:release_bundle" >&2
    return 1
}

setup_uv_env() { _deprecated "setup_uv_env"; }
setup_oss_cad_suite() { _deprecated "setup_oss_cad_suite"; }
ensure_yosys() { _deprecated "ensure_yosys"; }
setup_submodules() { _deprecated "setup_submodules"; }
build_ecc_py() { _deprecated "build_ecc_py"; }
get_target_platform() { _deprecated "get_target_platform"; }
build_tauri_bundle() { _deprecated "build_tauri_bundle"; }
