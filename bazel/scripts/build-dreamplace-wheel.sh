#!/usr/bin/env bash
set -euo pipefail

die() { echo "ERROR: $1" >&2; exit 1; }

[[ "${OSTYPE:-}" == linux* ]] || die "wheel build is only supported on Linux."

WS="${BUILD_WORKSPACE_DIRECTORY:-}"
[[ -n "$WS" && -d "$WS" ]] || die "BUILD_WORKSPACE_DIRECTORY is not set. Run via: bazel run //:build_dreamplace_wheel"
[[ $# -ge 1 ]] || die "missing dreamplace_raw_wheel runfiles path argument."
command -v sha256sum >/dev/null 2>&1 || die "required command not found: sha256sum"

# Resolve auditwheel binary
if [[ -x "${WS}/.venv/bin/auditwheel" ]]; then
    auditwheel_bin="${WS}/.venv/bin/auditwheel"
elif command -v auditwheel >/dev/null 2>&1; then
    auditwheel_bin="$(command -v auditwheel)"
else
    die "auditwheel not found. Install dev deps: uv sync --frozen --all-groups --python 3.11"
fi

# Resolve runfiles inputs
RF="${RUNFILES_DIR:-${BASH_SOURCE[0]}.runfiles}"
raw_whl="$RF/$1"
[[ -f "$raw_whl" ]] || die "raw wheel not found: $raw_whl"
PYTHON3="$RF/$2"
[[ -x "$PYTHON3" ]] || die "hermetic Python 3.11 not found in runfiles: $PYTHON3"

# Output to the same directory as ecc wheel so a single --find-links works
out_root="$WS/dist/wheel"
raw_out="$out_root/raw"
repair_out="$out_root/repaired"
report_out="$out_root/reports"
mkdir -p "$raw_out" "$repair_out" "$report_out"
show_report="$report_out/dreamplace-show.txt"
: > "$show_report"

smoke_dir="$(mktemp -d)"
trap 'rm -rf "$smoke_dir"' EXIT

cp "$raw_whl" "$raw_out/"

# Locate torch's lib directory so auditwheel can find libtorch.so, libc10.so, etc.
torch_lib_dir="$("${WS}/.venv/bin/python3" -c "import torch, pathlib; print(pathlib.Path(torch.__file__).parent / 'lib')" 2>/dev/null || true)"
[[ -n "$torch_lib_dir" && -d "$torch_lib_dir" ]] \
    || die "could not locate torch lib directory. Run: uv sync --frozen --all-groups --extra dreamplace --python 3.11"
export LD_LIBRARY_PATH="${torch_lib_dir}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
echo "[dreamplace-wheel] torch lib dir: $torch_lib_dir"

# Torch and CUDA libs excluded from auditwheel repair -- DreamPlace is built with
# TORCH_ENABLE_CUDA=0 and torch is a runtime dependency (not bundled). Without these
# exclusions auditwheel would bundle ~2 GB of shared libraries.
EXCLUDE_LIBS=(
    libtorch.so libtorch_cpu.so libtorch_python.so libc10.so libshm.so
    libgomp.so.1
    libcudart.so.12 libcublasLt.so.12 libcublas.so.12 libcudnn.so.9
    libcupti.so.12 libnvToolsExt.so.1 libnvrtc.so.12 libcufft.so.11
    libcurand.so.10 libcusparse.so.12 libcusolver.so.11 libnccl.so.2
    libnvJitLink.so.12 libtriton.so
)
exclude_flags=()
for lib in "${EXCLUDE_LIBS[@]}"; do
    exclude_flags+=(--exclude "$lib")
done

echo "[dreamplace-wheel] running auditwheel show/repair"
shopt -s nullglob
local_raw_wheels=("$raw_out"/*.whl)
[[ ${#local_raw_wheels[@]} -gt 0 ]] || die "raw wheel output directory is empty: $raw_out"

for whl in "${local_raw_wheels[@]}"; do
    {
        echo "=== $(basename "$whl") ==="
        "$auditwheel_bin" show "$whl"
        echo
    } >> "$show_report"
    "$auditwheel_bin" repair "$whl" -w "$repair_out" "${exclude_flags[@]}"
done

repaired_wheels=("$repair_out"/*.whl)
[[ ${#repaired_wheels[@]} -gt 0 ]] || die "no repaired wheel artifacts found in $repair_out"
shopt -u nullglob

echo "[dreamplace-wheel] running smoke test"
"$PYTHON3" -m pip install --target "$smoke_dir/site" "${repaired_wheels[@]}"
PYTHONPATH="$smoke_dir/site" "$PYTHON3" -c "
from dreamplace.Params import Params
from dreamplace.Placer import PlacementEngine

print('ecc-dreamplace smoke test passed: core imports verified')
"

(cd "$repair_out" && sha256sum ./*.whl > "$out_root/SHA256SUMS")

echo "[dreamplace-wheel] done"
echo "[dreamplace-wheel] raw wheels:      $raw_out"
echo "[dreamplace-wheel] repaired wheels: $repair_out"
echo "[dreamplace-wheel] report:          $show_report"
echo "[dreamplace-wheel] checksums:       $out_root/SHA256SUMS"
