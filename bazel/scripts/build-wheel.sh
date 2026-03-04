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
    echo "ERROR: missing ecc_bundle runfiles path argument." >&2
    exit 1
fi

for bin in uv python3.11 sha256sum; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "ERROR: required command not found: $bin" >&2
        exit 1
    fi
done

if [[ ! -d "$WS/.venv" ]]; then
    echo "ERROR: .venv not found in workspace. Run: bazel run //:prepare_dev" >&2
    exit 1
fi

auditwheel_bin="${WS}/.venv/bin/auditwheel"
if [[ ! -x "$auditwheel_bin" ]]; then
    if command -v auditwheel >/dev/null 2>&1; then
        auditwheel_bin="$(command -v auditwheel)"
    else
        echo "ERROR: auditwheel not found. Install dev deps: uv sync --frozen --all-groups --python 3.11" >&2
        exit 1
    fi
fi

RF="${RUNFILES_DIR:-${BASH_SOURCE[0]}.runfiles}"
ecc_bundle="$RF/$1"
if [[ ! -f "$ecc_bundle" ]]; then
    echo "ERROR: ecc bundle tar not found: $ecc_bundle" >&2
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

stage_dir="$(mktemp -d /tmp/chipcompiler-wheel-stage.XXXXXX)"
smoke_dir="$(mktemp -d /tmp/chipcompiler-wheel-smoke.XXXXXX)"
cleanup() {
    rm -rf "$stage_dir" "$smoke_dir"
}
trap cleanup EXIT

echo "[wheel] staging source tree at $stage_dir"
if command -v rsync >/dev/null 2>&1; then
    rsync -a \
        --exclude '.git/' \
        --exclude '.venv/' \
        --exclude '.direnv/' \
        --exclude 'bazel-*/' \
        --exclude 'workspacetest/' \
        --exclude 'dist/' \
        "$WS"/ "$stage_dir"/
else
    tar -C "$WS" \
        --exclude=".git" \
        --exclude=".venv" \
        --exclude=".direnv" \
        --exclude="bazel-*" \
        --exclude="workspacetest" \
        --exclude="dist" \
        -cf - . | tar -C "$stage_dir" -xf -
fi

echo "[wheel] extracting ecc bundle into staging tree"
tar -xf "$ecc_bundle" -C "$stage_dir"

shopt -s nullglob
ecc_py_matches=("$stage_dir"/chipcompiler/tools/ecc/bin/ecc_py*.so)
if [[ ${#ecc_py_matches[@]} -eq 0 ]]; then
    echo "ERROR: no ecc_py*.so found after bundle extraction." >&2
    exit 1
fi
shopt -u nullglob

echo "[wheel] building wheel via uv"
(
    cd "$stage_dir"
    uv build --wheel
)

shopt -s nullglob
raw_wheels=("$stage_dir"/dist/*.whl)
if [[ ${#raw_wheels[@]} -eq 0 ]]; then
    echo "ERROR: uv build did not produce wheel artifacts." >&2
    exit 1
fi
for whl in "${raw_wheels[@]}"; do
    cp -f "$whl" "$raw_out/"
done
shopt -u nullglob

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
python3.11 -m venv "$smoke_dir/venv"
"$smoke_dir/venv/bin/pip" install "${repaired_wheels[@]}"
"$smoke_dir/venv/bin/python" -c "import importlib; importlib.import_module('chipcompiler.tools.ecc.bin.ecc_py'); print('ecc_py import ok')"

(
    cd "$repair_out"
    sha256sum ./*.whl > "$out_root/SHA256SUMS"
)

echo "[wheel] done"
echo "[wheel] raw wheels:      $raw_out"
echo "[wheel] repaired wheels: $repair_out"
echo "[wheel] report:          $show_report"
echo "[wheel] checksums:       $out_root/SHA256SUMS"
