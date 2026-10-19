#!/usr/bin/env bash
# RPC stdio scenario: create/open/flow.run via test/rpc_check.py, then CLI status.
# Writes status.plain.txt under OUT_DIR for FileCheck (same contract as CLI scenario).
#
# Usage: run_rpc_project_scenario.sh OUT_DIR
# Env: CHIPCOMPILER_ICS55_PDK_ROOT, ECC_REPO_ROOT, ECC, PYTHON
set -euo pipefail

out_dir="${1:?usage: $0 OUT_DIR}"
root="${ECC_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export ECC_REPO_ROOT="$root"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pdk_root="${CHIPCOMPILER_ICS55_PDK_ROOT:?CHIPCOMPILER_ICS55_PDK_ROOT is required}"

py="${PYTHON:-$root/.venv/bin/python}"
ecc="${ECC:-$root/.venv/bin/ecc}"
test -x "$py"
test -x "$ecc"

mkdir -p "$out_dir"
project="$out_dir/project"
bash "$here/prepare_gcd_project.sh" "$project"

"$py" "$root/test/rpc_check.py" \
  --ecc "$ecc" \
  --project "$project" \
  --workspace default \
  --create \
  --run \
  --pdk-root "$pdk_root" \
  --rtl "$project/rtl/gcd.v" \
  --flow-start Synthesis \
  --flow-end Synthesis \
  --expect-status success \
  | tee "$out_dir/rpc_check.log"

"$ecc" status \
  --project "$project" \
  --workspace default \
  --plain \
  | tee "$out_dir/status.plain.txt"
