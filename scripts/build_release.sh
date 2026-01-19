#!/bin/bash
#
# Complete release build script for ChipCompiler ECC
# This script builds both the Python API server and the Tauri application
#

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICES_DIR="$PROJECT_ROOT/chipcompiler/services"
GUI_DIR="$PROJECT_ROOT/chipcompiler/gui"
TAURI_DIR="$GUI_DIR/src-tauri"
BINARIES_DIR="$TAURI_DIR/binaries"
VENV_DIR="$PROJECT_ROOT/.venv"

echo "=========================================="
echo "ChipCompiler ECC Release Build"
echo "=========================================="
echo "Project root: $PROJECT_ROOT"
echo ""

# Get target platform
TARGET=$(rustc -vV | grep host | cut -d' ' -f2)
echo "Target platform: $TARGET"
echo ""

# Step 1: Ensure virtual environment is activated
echo "=== Step 1: Setting up Python environment ==="
if [ -d "$VENV_DIR" ]; then
    echo "Activating virtual environment..."
    source "$VENV_DIR/bin/activate"
else
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
fi

# Install dependencies
echo "Installing Python dependencies..."
pip install -e "$PROJECT_ROOT" --quiet
pip install pyinstaller --quiet
echo "Python environment ready."
echo ""

# Step 2: Build API Server with PyInstaller
echo "=== Step 2: Building API Server ==="
cd "$SERVICES_DIR"

# Clean previous builds
rm -rf build dist __pycache__

# Build with PyInstaller
echo "Running PyInstaller..."
pyinstaller api-server.spec --clean --noconfirm

if [ ! -f "dist/api-server" ]; then
    echo "ERROR: PyInstaller build failed"
    exit 1
fi
echo "API Server built successfully."
echo ""

# Step 3: Copy binary to Tauri binaries directory
echo "=== Step 3: Installing API Server binary ==="
mkdir -p "$BINARIES_DIR"

# Determine binary name based on platform
BINARY_NAME="api-server-$TARGET"
if [[ "$TARGET" == *"windows"* ]]; then
    BINARY_NAME="$BINARY_NAME.exe"
fi

cp "dist/api-server" "$BINARIES_DIR/$BINARY_NAME"
chmod +x "$BINARIES_DIR/$BINARY_NAME"
echo "Installed: $BINARIES_DIR/$BINARY_NAME"
echo ""

# Step 4: Install frontend dependencies
echo "=== Step 4: Installing frontend dependencies ==="
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

# Step 5: Build Tauri application
echo "=== Step 5: Building Tauri application ==="
pnpm run tauri build

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
