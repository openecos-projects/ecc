#!/usr/bin/env bash
# Setup script for devcontainer post-create command
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

cd scripts
source common.sh
setup_project_vars
cd -

uv sync --frozen --all-groups --python 3.11
source .venv/bin/activate

setup_oss_cad_suite
setup_ics55_pdk
build_ecc_py
bash ./scripts/autopatch-ecc-py.sh

echo "✓ Development environment ready!"