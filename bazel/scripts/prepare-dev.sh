#!/usr/bin/env bash
# Set up the full development environment.
# Usage: bazel run //:prepare_dev
set -euo pipefail

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
RESET='\033[0m'

WS="${BUILD_WORKSPACE_DIRECTORY:?Must run via: bazel run //:prepare_dev}"
cd "$WS"

echo "==> Setting up Python venv..."
if [[ "${SKIP_VENV:-}" != "1" ]]; then
    uv sync --frozen --all-groups --python 3.11
    source .venv/bin/activate
else
    echo "    Skipped (SKIP_VENV=1)"
fi

echo "==> Building and installing Bazel-managed deps..."
# Same as install-dev.sh, inline here to avoid deps change
RF="${RUNFILES_DIR:-${BASH_SOURCE[0]}.runfiles}"
ecc_bundle="$RF/$1"
tar -xf "$ecc_bundle" -C "$WS" --keep-directory-symlink --no-same-owner
echo "Installed ECC runtime -> chipcompiler/tools/ecc/bin/"

# Install DreamPlace .so files by reusing install-dreamplace.sh
shift
if ! RUNFILES_DIR="${RF}" "${RF}/_main/bazel/scripts/install-dreamplace.sh" "$@"; then
    echo -e "${YELLOW}WARNING: DreamPlace install failed. DreamPlace operators will not be available.${RESET}"
    echo -e "${YELLOW}  You can retry with: bazel run //bazel/scripts:install_dreamplace${RESET}"
fi

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
