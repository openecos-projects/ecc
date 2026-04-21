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

UV="$RF/$3"
if [[ ! -x "$UV" ]]; then
    echo "ERROR: uv not found in runfiles: $UV" >&2
    exit 1
fi

out_root="$WS/dist/wheel"
out_dir="$out_root/repaired"
mkdir -p "$out_dir"
# Clean only ecc wheels to preserve prior build
rm -f "$out_dir"/ecc-*.whl

cp "$raw_whl" "$out_dir/"
final_whl="$out_dir/$(basename "$raw_whl")"

echo "[wheel] ecc wheel is pure Python (ecc_py bindings come from ecc-tools wheel)"
echo "[wheel] skipping auditwheel — no native code in this wheel"

# Smoke test: verify the Python package is importable (with deps resolved via uv)
echo "[wheel] running smoke test"
smoke_dir="$(mktemp -d)"
trap 'rm -rf "$smoke_dir"' EXIT

# Create a temp venv so uv pip install runs in project mode (reads pyproject.toml / tool.uv.sources).
# Using --target skips project config reading, which breaks ecc-dreamplace/ecc-tools resolution.
"$PYTHON3" -m venv "$smoke_dir/venv"
venv_python="$smoke_dir/venv/bin/python"

cd "$WS"
"$UV" pip install --python "$venv_python" "$final_whl"

"$venv_python" -c "
import chipcompiler
from chipcompiler.tools.ecc.module import ECCToolsModule
assert chipcompiler.__version__ == '0.1.0', f'unexpected version: {chipcompiler.__version__}'
print('ecc wheel smoke test passed: chipcompiler package importable')
"

(
    cd "$out_dir"
    sha256sum ./*.whl > "$out_root/SHA256SUMS"
)

echo "[wheel] done"
echo "[wheel] wheel:     $out_dir"
echo "[wheel] checksums: $out_root/SHA256SUMS"
