#!/usr/bin/env bash
# Set up the full development environment.
# Usage: bazel run //:prepare_dev
set -euo pipefail

GREEN='\033[0;32m'
CYAN='\033[0;36m'
RESET='\033[0m'

WS="${BUILD_WORKSPACE_DIRECTORY:?Must run via: bazel run //:prepare_dev}"
cd "$WS"

echo "==> Setting up Python venv..."
uv sync --frozen --all-groups --python 3.11
source .venv/bin/activate

echo "==> Building and installing Bazel-managed deps..."
bazel run //:install_dev

echo ""
echo -e "${GREEN}Dev environment is ready.${RESET}"
echo -e "${CYAN}Run 'source .venv/bin/activate' to activate the venv.${RESET}"
echo ""
echo "Next steps:"
echo "  bazel build //:server_bundle    Build API server executable"
echo "  bazel build //:tauri_bundle     Build Tauri GUI bundle"
echo "  bazel build //:release_bundle   Build release artifact"
echo "  uv run pytest test/             Run tests"
echo "  uv run chipcompiler --reload    Start API server (dev mode, port 8765)"
