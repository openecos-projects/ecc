#!/bin/bash
#
# Complete release build script for ChipCompiler ECC
# This script builds both the Python API server and the Tauri application
#

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source common functions
source "${SCRIPT_DIR}/common.sh"

# GUI paths
GUI_DIR="$PROJECT_ROOT/chipcompiler/gui"
TAURI_DIR="$GUI_DIR/src-tauri"
BINARIES_DIR="$TAURI_DIR/binaries"
TAURI_RESOURCES_DIR="$TAURI_DIR/resources"
OSS_CAD_BUNDLE_DIR="$TAURI_RESOURCES_DIR/oss-cad-suite"

# Initialize project variables
setup_project_vars

# Default to enabling OSS CAD Suite bundling unless explicitly disabled
if [ -z "$ENABLE_OSS_CAD_SUITE" ]; then
    ENABLE_OSS_CAD_SUITE="true"
fi

echo "=========================================="
echo "ChipCompiler ECC Release Build"
echo "=========================================="
echo "Project root: $PROJECT_ROOT"
echo ""

# Get target platform
TARGET=$(get_target_platform)
echo "Target platform: $TARGET"
echo ""

# Step 1: Setup Python environment
echo "=== Step 1: Setting up Python environment ==="
setup_uv_env || exit 1
echo ""

# Step 2: Ensure yosys is available
echo "=== Step 2: Ensuring yosys is available ==="
ensure_yosys || exit 1
echo ""

# Step 3: Stage Yosys runtime for bundling
echo "=== Step 3: Staging Yosys runtime ==="
mkdir -p "$TAURI_RESOURCES_DIR"
if [[ "$ENABLE_OSS_CAD_SUITE" != "true" ]]; then
    echo "Skipping yosys bundling (ENABLE_OSS_CAD_SUITE=$ENABLE_OSS_CAD_SUITE)"
    # Ensure resources path exists so Tauri glob doesn't fail
    mkdir -p "$OSS_CAD_BUNDLE_DIR"
    echo ""
else
    # Ensure OSS CAD Suite is downloaded (even if system yosys exists)
    setup_oss_cad_suite

    rm -rf "$OSS_CAD_BUNDLE_DIR"
    mkdir -p "$OSS_CAD_BUNDLE_DIR"

    YOSYS_BIN_SRC="$OSS_CAD_DIR/bin/yosys"
    if [[ "$TARGET" == *"windows"* ]]; then
        YOSYS_BIN_SRC="$OSS_CAD_DIR/bin/yosys.exe"
    fi

    if [ ! -f "$YOSYS_BIN_SRC" ]; then
        echo "ERROR: yosys binary not found at $YOSYS_BIN_SRC"
        exit 1
    fi

    SLANG_SRC=$(ls "$OSS_CAD_DIR/share/yosys/plugins"/slang.* 2>/dev/null | head -1)
    if [ -z "$SLANG_SRC" ]; then
        echo "ERROR: slang plugin not found under $OSS_CAD_DIR/share/yosys/plugins"
        exit 1
    fi

    echo "Syncing OSS CAD Suite into Tauri resources..."
    cp -a "$OSS_CAD_DIR/." "$OSS_CAD_BUNDLE_DIR/"
    chmod +x "$OSS_CAD_BUNDLE_DIR/bin/$(basename "$YOSYS_BIN_SRC")"
    if [ -f "$OSS_CAD_BUNDLE_DIR/bin/abc" ]; then
        chmod +x "$OSS_CAD_BUNDLE_DIR/bin/abc"
    fi
    echo "Bundled yosys: $OSS_CAD_BUNDLE_DIR/bin/$(basename "$YOSYS_BIN_SRC")"
    if [ -d "$OSS_CAD_BUNDLE_DIR/share/yosys" ]; then
        echo "Bundled share/yosys: $OSS_CAD_BUNDLE_DIR/share/yosys"
    fi
    if [ -f "$OSS_CAD_BUNDLE_DIR/bin/abc" ]; then
        echo "Bundled abc: $OSS_CAD_BUNDLE_DIR/bin/abc"
    fi
    echo ""
fi

# Step 4: Ensure ecc_py is built
echo "=== Step 4: Ensuring ecc_py is built ==="
setup_submodules
build_ecc_py || exit 1
echo ""

# Step 5: Build API Server with PyInstaller
echo "=== Step 5: Building API Server ==="
cd "$PROJECT_ROOT"

# Clean previous builds
rm -rf build dist __pycache__

# Build with PyInstaller
echo "Running PyInstaller..."
PYINSTALLER_ONEFILE=1 pyinstaller chipcompiler.spec --clean --noconfirm

SOURCE_BINARY="dist/chipcompiler"
if [[ "$TARGET" == *"windows"* ]]; then
    SOURCE_BINARY="${SOURCE_BINARY}.exe"
fi

if [ ! -f "$SOURCE_BINARY" ]; then
    echo "ERROR: PyInstaller build failed"
    exit 1
fi
echo "API Server built successfully."
echo ""

# Step 6: Copy binary to Tauri binaries directory
echo "=== Step 6: Installing API Server binary ==="
mkdir -p "$BINARIES_DIR"

# Determine binary name based on platform
BINARY_NAME="api-server-$TARGET"
if [[ "$TARGET" == *"windows"* ]]; then
    BINARY_NAME="$BINARY_NAME.exe"
fi

cp "$SOURCE_BINARY" "$BINARIES_DIR/$BINARY_NAME"
chmod +x "$BINARIES_DIR/$BINARY_NAME"
echo "Installed: $BINARIES_DIR/$BINARY_NAME"
echo ""

# Step 7: Install frontend dependencies
echo "=== Step 7: Installing frontend dependencies ==="
cd "$GUI_DIR"
if command -v pnpm &> /dev/null; then
    pnpm install
else
    echo "pnpm not found, installing..."
    npm install -g pnpm
    pnpm install
fi
echo "Frontend dependencies installed."
echo ""

# Step 8: Build Tauri application
echo "=== Step 8: Building Tauri application ==="
if [ ! -d "$OSS_CAD_BUNDLE_DIR" ]; then
    echo "ERROR: Tauri resources missing: $OSS_CAD_BUNDLE_DIR"
    exit 1
fi
pnpm run tauri build

# Step 9: Copy API Server binary to release directory (for direct execution)
echo "=== Step 9: Copying API Server to release directory ==="
RELEASE_DIR="$TAURI_DIR/target/release"
if [ -d "$RELEASE_DIR" ]; then
    cp "$BINARIES_DIR/$BINARY_NAME" "$RELEASE_DIR/$BINARY_NAME"
    chmod +x "$RELEASE_DIR/$BINARY_NAME"
    echo "Copied: $RELEASE_DIR/$BINARY_NAME"
else
    echo "Warning: Release directory not found, skipping copy"
fi
echo ""

echo ""
echo "=========================================="
echo "Build Complete!"
echo "=========================================="
echo ""
echo "Output locations:"
echo "  - Executable: $TAURI_DIR/target/release/ecc-client"
echo "  - Bundles:    $TAURI_DIR/target/release/bundle/"
echo ""

# List generated bundles
if [ -d "$TAURI_DIR/target/release/bundle" ]; then
    echo "Generated packages:"
    find "$TAURI_DIR/target/release/bundle" -type f \( -name "*.dmg" -o -name "*.app" -o -name "*.deb" -o -name "*.rpm" -o -name "*.AppImage" -o -name "*.msi" -o -name "*.exe" \) 2>/dev/null | while read f; do
        echo "  - $f"
    done
fi
