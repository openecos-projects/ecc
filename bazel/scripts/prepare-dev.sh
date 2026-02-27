#!/usr/bin/env bash
# Set up the full development environment.
# Usage: bazel run //:prepare_dev
set -euo pipefail

WS="${BUILD_WORKSPACE_DIRECTORY:?Must run via: bazel run //:prepare_dev}"
cd "$WS"

echo "==> Setting up Python venv..."
uv sync --frozen --all-groups --python 3.11

echo "==> Building and installing Bazel-managed deps..."
bazel run //:install_dev
