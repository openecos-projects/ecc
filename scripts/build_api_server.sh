#!/bin/bash
#
# Build script for ChipCompiler API Server
# This script uses PyInstaller to create a standalone executable
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICES_DIR="$PROJECT_ROOT/chipcompiler/services"
TAURI_DIR="$PROJECT_ROOT/chipcompiler/gui/src-tauri"
BINARIES_DIR="$TAURI_DIR/binaries"

echo "=== Building ChipCompiler API Server ==="
echo "Project root: $PROJECT_ROOT"
echo "Services dir: $SERVICES_DIR"

# Ensure we're in the services directory
cd "$SERVICES_DIR"

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build dist __pycache__

# Build with PyInstaller
echo "Running PyInstaller..."
pyinstaller api-server.spec --clean --noconfirm

# Check if build succeeded
if [ ! -f "dist/api-server" ]; then
    echo "ERROR: Build failed - api-server executable not found"
    exit 1
fi

echo "Build successful: $SERVICES_DIR/dist/api-server"

# Get the target triple for the current platform
TARGET=$(rustc -vV | grep host | cut -d' ' -f2)
echo "Target platform: $TARGET"

# Create binaries directory if it doesn't exist
mkdir -p "$BINARIES_DIR"

# Copy to Tauri binaries directory with platform suffix
DEST_NAME="api-server-$TARGET"
if [[ "$TARGET" == *"windows"* ]]; then
    DEST_NAME="$DEST_NAME.exe"
fi

cp "dist/api-server" "$BINARIES_DIR/$DEST_NAME"
echo "Copied to: $BINARIES_DIR/$DEST_NAME"

# Make executable
chmod +x "$BINARIES_DIR/$DEST_NAME"

echo "=== API Server build complete ==="
echo "Binary location: $BINARIES_DIR/$DEST_NAME"
