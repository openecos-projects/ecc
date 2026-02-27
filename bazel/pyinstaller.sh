#!/usr/bin/env bash
# Bazel-managed PyInstaller wrapper
set -euo pipefail

# Find Python interpreter from runfiles
PYTHON="${PYTHON_INTERPRETER:-python3}"

# Run PyInstaller with all arguments
exec "$PYTHON" -m PyInstaller "$@"
