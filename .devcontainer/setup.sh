#!/usr/bin/env bash
# Setup script for devcontainer post-create command
# This script is extracted from .devcontainer/devcontainer.json postCreateCommand

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

rm -rf .venv

cd scripts
source common.sh
setup_project_vars
cd -

uv sync --frozen --all-groups --python 3.11

build_ecc_py

setup_oss_cad_suite

