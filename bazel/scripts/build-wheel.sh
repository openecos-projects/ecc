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

# Smoke test: verify the Python package is importable
echo "[wheel] running smoke test"
smoke_dir="$(mktemp -d)"
trap 'rm -rf "$smoke_dir"' EXIT

venv_python="$smoke_dir/venv/bin/python"

# Use a temp venv (via uv) because hermetic Python lacks ensurepip.
"$UV" venv --python "$PYTHON3" "$smoke_dir/venv"

# ecc-dreamplace and ecc-tools are not on PyPI. Install them from the same
# pinned source URLs used by the main project, then install the local ecc wheel
# so uv resolves the remaining PyPI deps against the final artifact.
"$PYTHON3" - "$WS/pyproject.toml" "$smoke_dir/requirements.txt" <<'PY'
import pathlib
import sys
import tomllib

project = tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
requirements = pathlib.Path(sys.argv[2])
sources = project["tool"]["uv"]["sources"]
dependencies = project["project"]["dependencies"]

def pinned_url(name: str) -> str:
    dependency = next(dep for dep in dependencies if dep.startswith(f"{name}=="))
    version = dependency.split("==", 1)[1]
    url = sources[name]["url"]
    wheel_name = name.replace("-", "_")
    if f"{wheel_name}-{version}" not in url:
        raise SystemExit(f"{name} dependency {version} does not match source URL: {url}")
    return url

requirements.write_text(
    "\n".join(
        [
            pinned_url("ecc-tools"),
            pinned_url("ecc-dreamplace"),
        ],
    )
    + "\n",
)
PY
"$UV" pip install --python "$venv_python" -r "$smoke_dir/requirements.txt" "$final_whl"

expected_version=$(grep -E '^version\s*=' "$WS/pyproject.toml" | head -n1 | sed 's/.*"\([^"]*\)".*/\1/')
"$venv_python" -c "
import chipcompiler
from chipcompiler.tools.ecc.module import ECCToolsModule
assert chipcompiler.__version__ == '${expected_version}', f'unexpected version: {chipcompiler.__version__} (expected ${expected_version})'
print('ecc wheel smoke test passed: chipcompiler package importable')
"

echo "[wheel] done"
echo "[wheel] wheel:     $out_dir"
