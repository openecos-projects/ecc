#!/usr/bin/env bash
# Compat shim → materialize_signoff_workspace.sh --variant ready
# Usage: materialize_ready_workspace.sh WORKSPACE_DIR

set -euo pipefail
[[ $# -eq 1 ]] || { echo "usage: $0 WORKSPACE_DIR" >&2; exit 2; }
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$here/materialize_signoff_workspace.sh" "$1" --variant ready
