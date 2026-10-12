#!/usr/bin/env bash
# Compatibility wrapper → run_project_scenario.sh --mode=cli
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$here/run_project_scenario.sh" --mode=cli "$@"
