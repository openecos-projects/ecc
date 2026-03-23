#!/usr/bin/env bash
set -euo pipefail

if [[ "${OSTYPE:-}" != linux* ]]; then
    echo "ERROR: wheel build is only supported on Linux." >&2
    exit 1
fi

WS="${BUILD_WORKSPACE_DIRECTORY:-}"
if [[ -z "$WS" || ! -d "$WS" ]]; then
    echo "ERROR: BUILD_WORKSPACE_DIRECTORY is not set. Run via: bazel run //:build_dreamplace_wheel" >&2
    exit 1
fi

if [[ $# -lt 1 ]]; then
    echo "ERROR: missing dreamplace_raw_wheel runfiles path argument." >&2
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

# Output to the same directory as ecc wheel so a single --find-links works
out_root="$WS/dist/wheel"
raw_out="$out_root/raw"
repair_out="$out_root/repaired"
report_out="$out_root/reports"
mkdir -p "$raw_out" "$repair_out" "$report_out"
show_report="$report_out/dreamplace-show.txt"
: > "$show_report"

smoke_dir="$(mktemp -d)"
cleanup() { rm -rf "$smoke_dir"; }
trap cleanup EXIT

cp "$raw_whl" "$raw_out/"

# Locate torch's lib directory so auditwheel can find libtorch.so, libc10.so, etc.
torch_lib_dir="$("${WS}/.venv/bin/python3" -c "import torch, pathlib; print(pathlib.Path(torch.__file__).parent / 'lib')" 2>/dev/null || true)"
if [[ -n "$torch_lib_dir" && -d "$torch_lib_dir" ]]; then
    export LD_LIBRARY_PATH="${torch_lib_dir}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    echo "[dreamplace-wheel] torch lib dir: $torch_lib_dir"
else
    echo "ERROR: could not locate torch lib directory. Run: uv sync --frozen --all-groups --extra dreamplace --python 3.11" >&2
    exit 1
fi

echo "[dreamplace-wheel] running auditwheel show/repair"
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
    # Exclude torch/CUDA libs — DreamPlace is built with TORCH_ENABLE_CUDA=0 and
    # torch is a runtime dependency (not bundled). auditwheel would otherwise try
    # to bundle libtorch.so, libc10.so, and all CUDA libs which is ~2 GB.
    "$auditwheel_bin" repair "$whl" -w "$repair_out" \
        --exclude libtorch.so \
        --exclude libtorch_cpu.so \
        --exclude libtorch_python.so \
        --exclude libc10.so \
        --exclude libshm.so \
        --exclude libgomp.so.1 \
        --exclude libcudart.so.12 \
        --exclude libcublasLt.so.12 \
        --exclude libcublas.so.12 \
        --exclude libcudnn.so.9 \
        --exclude libcupti.so.12 \
        --exclude libnvToolsExt.so.1 \
        --exclude libnvrtc.so.12 \
        --exclude libcufft.so.11 \
        --exclude libcurand.so.10 \
        --exclude libcusparse.so.12 \
        --exclude libcusolver.so.11 \
        --exclude libnccl.so.2 \
        --exclude libnvJitLink.so.12 \
        --exclude libtriton.so
done
shopt -u nullglob

shopt -s nullglob
repaired_wheels=("$repair_out"/*.whl)
if [[ ${#repaired_wheels[@]} -eq 0 ]]; then
    echo "ERROR: no repaired wheel artifacts found in $repair_out" >&2
    exit 1
fi
shopt -u nullglob

echo "[dreamplace-wheel] running smoke test"
"$PYTHON3" -m pip install --target "$smoke_dir/site" "${repaired_wheels[@]}"
PYTHONPATH="$smoke_dir/site" "$PYTHON3" -c "
from dreamplace.Params import Params
from dreamplace.Placer import PlacementEngine

print('ecc-dreamplace smoke test passed: core imports verified')
"

(
    cd "$repair_out"
    sha256sum ./*.whl > "$out_root/SHA256SUMS"
)

echo "[dreamplace-wheel] done"
echo "[dreamplace-wheel] raw wheels:      $raw_out"
echo "[dreamplace-wheel] repaired wheels: $repair_out"
echo "[dreamplace-wheel] report:          $show_report"
echo "[dreamplace-wheel] checksums:       $out_root/SHA256SUMS"
