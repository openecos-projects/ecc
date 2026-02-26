#!/usr/bin/env bash
# Setup script for devcontainer post-create command
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
cd "$PROJECT_ROOT"

uv sync --frozen --all-groups --python 3.11
bazel run //chipcompiler/thirdparty:install_ecc_runtime
bazel run //scripts:init_ics55_pdk

echo "✓ Development environment ready!"
