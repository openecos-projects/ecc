#!/usr/bin/env bash
# CI-oriented release build script for ChipCompiler ECC
# Assumes dependencies and submodules are already installed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$PROJECT_ROOT/scripts/common.sh"

GUI_DIR="$PROJECT_ROOT/chipcompiler/gui"
TAURI_DIR="$GUI_DIR/src-tauri"
BINARIES_DIR="$TAURI_DIR/binaries"
TAURI_RESOURCES_DIR="$TAURI_DIR/resources"
OSS_CAD_BUNDLE_DIR="$TAURI_RESOURCES_DIR/oss-cad-suite"

log() {
    echo "[$(date +%H:%M:%S)] $*"
}

require_venv() {
    if [ ! -f "${VENV_DIR}/bin/activate" ]; then
        echo "ERROR: venv not found at ${VENV_DIR}."
        echo "Run: uv sync --frozen --all-groups --python ${PYTHON_VERSION}"
        exit 1
    fi
    # shellcheck disable=SC1090
    source "${VENV_DIR}/bin/activate"
}

build_api_server() {
    cd "$PROJECT_ROOT"
    rm -rf build dist __pycache__
    PYINSTALLER_ONEFILE=1 pyinstaller chipcompiler.spec --clean --noconfirm

    local source_binary="dist/chipcompiler"
    if [[ "$TARGET" == *"windows"* ]]; then
        source_binary="${source_binary}.exe"
    fi
    if [ ! -f "$source_binary" ]; then
        echo "ERROR: PyInstaller build failed"
        exit 1
    fi

    mkdir -p "$BINARIES_DIR"
    local binary_name="api-server-$TARGET"
    if [[ "$TARGET" == *"windows"* ]]; then
        binary_name="$binary_name.exe"
    fi
    cp "$source_binary" "$BINARIES_DIR/$binary_name"
    chmod +x "$BINARIES_DIR/$binary_name"

    echo "$binary_name"
}

main() {
    setup_project_vars
    ENABLE_OSS_CAD_SUITE="${ENABLE_OSS_CAD_SUITE:-true}"
    TARGET=$(get_target_platform)

    log "CI build target: $TARGET"
    log "Activating venv"
    require_venv
    log "Checking yosys"
    ensure_yosys || exit 1
    log "Staging OSS CAD Suite"
    stage_oss_cad_suite "$TAURI_RESOURCES_DIR" "$OSS_CAD_BUNDLE_DIR" "$TARGET" || exit 1

    if [[ ! -d "${ECC_TOOLS_ROOT}" ]]; then
        echo "ERROR: ecc-tools submodule not found."
        exit 1
    fi
    log "Building ecc_py"
    build_ecc_py

    log "Building API server"
    local binary_name
    binary_name=$(build_api_server)

    log "Building Tauri app"
    build_tauri_bundle "$GUI_DIR" "$TAURI_DIR" "$OSS_CAD_BUNDLE_DIR" "$BINARIES_DIR" "$binary_name" || exit 1
}

main "$@"
