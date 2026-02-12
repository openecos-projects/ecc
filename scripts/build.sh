#!/usr/bin/env bash

set -e

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "${SCRIPT_DIR}/common.sh"

GUI_DIR="$PROJECT_ROOT/chipcompiler/gui"
TAURI_DIR="$GUI_DIR/src-tauri"
BINARIES_DIR="$TAURI_DIR/binaries"
TAURI_RESOURCES_DIR="$TAURI_DIR/resources"
OSS_CAD_BUNDLE_DIR="$TAURI_RESOURCES_DIR/oss-cad-suite"

setup_project_vars
ENABLE_OSS_CAD_SUITE="${ENABLE_OSS_CAD_SUITE:-true}"
ENABLE_ICS55_PDK_DOWNLOAD="${ENABLE_ICS55_PDK_DOWNLOAD:-false}"

echo "=========================================="
echo "ChipCompiler ECC Release Build"
echo "=========================================="
echo "Project root: $PROJECT_ROOT"
echo

TARGET="$(get_target_platform || true)"
if [[ -z "$TARGET" ]]; then
    echo "ERROR: target platform is empty. Install Rust toolchain and ensure 'rustc' is in PATH."
    exit 1
fi

echo "Target platform: $TARGET"
echo

echo "=== Step 1: Setting up Python environment ==="
setup_uv_env
echo

echo "=== Step 2: Ensuring yosys is available ==="
ensure_yosys
echo

echo "=== Step 3: Preparing Yosys runtime source ==="
if [[ "$ENABLE_OSS_CAD_SUITE" == "true" ]]; then
    setup_oss_cad_suite
fi
echo

echo "=== Step 4: Ensuring ecc_py is built ==="
setup_submodules
if [[ "$ENABLE_ICS55_PDK_DOWNLOAD" == "true" ]]; then
    echo "ICS55 PDK download is enabled."
    setup_ics55_pdk
else
    echo "Skipping ICS55 PDK download (set ENABLE_ICS55_PDK_DOWNLOAD=true to enable)."
fi
build_ecc_py
echo

echo "=== Step 5: Building API Server ==="
cd "$PROJECT_ROOT"
rm -rf build dist __pycache__
PYINSTALLER_ONEFILE=1 pyinstaller chipcompiler.spec --clean --noconfirm

SOURCE_BINARY="$PROJECT_ROOT/dist/chipcompiler"
if [[ "$TARGET" == *"windows"* ]]; then
    SOURCE_BINARY="${SOURCE_BINARY}.exe"
fi

if [[ ! -f "$SOURCE_BINARY" ]]; then
    echo "ERROR: PyInstaller build failed"
    exit 1
fi

echo "API Server built successfully."
echo

echo "=== Step 6: Installing API Server binary ==="
mkdir -p "$BINARIES_DIR"

BINARY_NAME="api-server-$TARGET"
if [[ "$TARGET" == *"windows"* ]]; then
    BINARY_NAME="${BINARY_NAME}.exe"
fi

cp "$SOURCE_BINARY" "$BINARIES_DIR/$BINARY_NAME"
chmod +x "$BINARIES_DIR/$BINARY_NAME"
echo "Installed: $BINARIES_DIR/$BINARY_NAME"
echo

echo "=== Step 7: Installing frontend dependencies ==="
cd "$GUI_DIR"
if command -v pnpm >/dev/null 2>&1; then
    pnpm install
else
    echo "pnpm not found, installing..."
    npm install -g pnpm
    pnpm install
fi

echo "Frontend dependencies installed."
echo

build_tauri_bundle "$GUI_DIR" "$TAURI_DIR" "$OSS_CAD_BUNDLE_DIR" "$BINARIES_DIR" "$BINARY_NAME"

echo
echo "=========================================="
echo "Build Complete!"
echo "=========================================="
echo
echo "Output locations:"
echo "  - Executable: $TAURI_DIR/target/release/ecc-client"
echo "  - Bundles:    $TAURI_DIR/target/release/bundle/"
echo
