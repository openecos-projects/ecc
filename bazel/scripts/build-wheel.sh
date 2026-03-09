#!/usr/bin/env bash
set -euo pipefail

if [[ "${OSTYPE:-}" != linux* ]]; then
    echo "ERROR: wheel build is only supported on Linux." >&2
    exit 1
fi

WS="${BUILD_WORKSPACE_DIRECTORY:-}"
if [[ -z "$WS" || ! -d "$WS" ]]; then
    echo "ERROR: BUILD_WORKSPACE_DIRECTORY is not set. Run via: bazel run //:build_wheel" >&2
    exit 1
fi

if [[ $# -lt 1 ]]; then
    echo "ERROR: missing raw_wheel runfiles path argument." >&2
    exit 1
fi

if ! command -v sha256sum >/dev/null 2>&1; then
    echo "ERROR: required command not found: sha256sum" >&2
    exit 1
fi

auditwheel_bin=""
if [[ -x "${WS}/.venv/bin/auditwheel" ]]; then
    auditwheel_bin="${WS}/.venv/bin/auditwheel"
elif command -v auditwheel >/dev/null 2>&1; then
    auditwheel_bin="$(command -v auditwheel)"
else
    echo "ERROR: auditwheel not found. Install dev deps: uv sync --frozen --all-groups --python 3.11" >&2
    exit 1
fi

RF="${RUNFILES_DIR:-${BASH_SOURCE[0]}.runfiles}"
raw_whl="$RF/$1"
if [[ ! -f "$raw_whl" ]]; then
    echo "ERROR: raw wheel not found: $raw_whl" >&2
    exit 1
fi

PYTHON3="$RF/$2"
if [[ ! -x "$PYTHON3" ]]; then
    echo "ERROR: hermetic Python 3.11 not found in runfiles: $PYTHON3" >&2
    exit 1
fi

out_root="$WS/dist/wheel"
raw_out="$out_root/raw"
repair_out="$out_root/repaired"
report_out="$out_root/reports"
rm -rf "$out_root"
mkdir -p "$raw_out" "$repair_out" "$report_out"
show_report="$report_out/show.txt"
: > "$show_report"

smoke_dir="$(mktemp -d)"
cleanup() { rm -rf "$smoke_dir"; }
trap cleanup EXIT

cp "$raw_whl" "$raw_out/"

echo "[wheel] running auditwheel show/repair"
shopt -s nullglob
local_raw_wheels=("$raw_out"/*.whl)
if [[ ${#local_raw_wheels[@]} -eq 0 ]]; then
    echo "ERROR: raw wheel output directory is empty: $raw_out" >&2
    exit 1
fi

for whl in "${local_raw_wheels[@]}"; do
    {
        echo "=== $(basename "$whl") ==="
        "$auditwheel_bin" show "$whl"
        echo
    } >> "$show_report"
    "$auditwheel_bin" repair "$whl" -w "$repair_out"
done
shopt -u nullglob

shopt -s nullglob
repaired_wheels=("$repair_out"/*.whl)
if [[ ${#repaired_wheels[@]} -eq 0 ]]; then
    echo "ERROR: no repaired wheel artifacts found in $repair_out" >&2
    exit 1
fi
shopt -u nullglob

echo "[wheel] running smoke test"
"$PYTHON3" -m pip install --target "$smoke_dir/site" "${repaired_wheels[@]}"
PYTHONPATH="$smoke_dir/site" "$PYTHON3" -c "
from chipcompiler.tools.ecc.bin import ecc_py

required = ['flow_init', 'flow_exit', 'db_init', 'def_init', 'lef_init', 'def_save',
            'run_placer', 'run_cts', 'run_rt', 'run_drc', 'run_filler',
            'init_floorplan', 'report_db', 'feature_summary']
missing = [f for f in required if not callable(getattr(ecc_py, f, None))]
assert not missing, f'missing or non-callable bindings: {missing}'

from chipcompiler.tools.ecc.module import ECCToolsModule
m = ECCToolsModule()
assert m.ecc is ecc_py

print(f'ecc_py smoke test passed: {len(required)} bindings verified')
"

(
    cd "$repair_out"
    sha256sum ./*.whl > "$out_root/SHA256SUMS"
)

echo "[wheel] done"
echo "[wheel] raw wheels:      $raw_out"
echo "[wheel] repaired wheels: $repair_out"
echo "[wheel] report:          $show_report"
echo "[wheel] checksums:       $out_root/SHA256SUMS"
