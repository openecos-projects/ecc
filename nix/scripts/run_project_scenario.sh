#!/usr/bin/env bash
# Product project scenario: CLI --project and/or RPC stdio Synthesis smoke.
# Shared prepare + status FileCheck contract; mode selects the run driver.
#
# Usage: run_project_scenario.sh --mode=cli|rpc OUT_DIR
# Env: CHIPCOMPILER_ICS55_PDK_ROOT, ECC_REPO_ROOT, ECC, PYTHON
set -euo pipefail

mode=""
out_dir=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode=*) mode="${1#--mode=}"; shift ;;
    --mode) mode="${2:?}"; shift 2 ;;
    -*)
      echo "usage: $0 --mode=cli|rpc OUT_DIR" >&2
      exit 2
      ;;
    *)
      out_dir="$1"
      shift
      ;;
  esac
done

if [[ -z "$mode" || -z "$out_dir" ]]; then
  echo "usage: $0 --mode=cli|rpc OUT_DIR" >&2
  exit 2
fi
case "$mode" in
  cli|rpc) ;;
  *)
    echo "unknown mode: $mode (want cli|rpc)" >&2
    exit 2
    ;;
esac

root="${ECC_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export ECC_REPO_ROOT="$root"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ecc="${ECC:-$root/.venv/bin/ecc}"
test -x "$ecc"

mkdir -p "$out_dir"
project="$out_dir/project"
bash "$here/prepare_gcd_project.sh" "$project"

case "$mode" in
  cli)
    "$ecc" run \
      --project "$project" \
      --from Synthesis \
      --to Synthesis \
      --plain \
      | tee "$out_dir/run.plain.txt"
    ;;
  rpc)
    pdk_root="${CHIPCOMPILER_ICS55_PDK_ROOT:?CHIPCOMPILER_ICS55_PDK_ROOT is required}"
    py="${PYTHON:-$root/.venv/bin/python}"
    test -x "$py"
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
    ;;
esac

"$ecc" status \
  --project "$project" \
  --workspace default \
  --plain \
  | tee "$out_dir/status.plain.txt"
