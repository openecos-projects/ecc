#!/usr/bin/env bash
# Prepare a gcd project and run test/rpc_check.py (RPC then ecc status --project).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

PROJECT="${PROJECT:-${RUNNER_TEMP:-/tmp}/rpc-project-smoke}"
PDK_ROOT="${CHIPCOMPILER_ICS55_PDK_ROOT:?CHIPCOMPILER_ICS55_PDK_ROOT is required}"
# Prefer the workspace venv (Python >=3.11): manylinux system python3 may lack tomllib.
PY="${PYTHON:-${PY:-$ROOT/.venv/bin/python}}"
ECC="${ECC:-$ROOT/.venv/bin/ecc}"

test -x "$PY"
test -x "$ECC"

rm -rf "$PROJECT"
mkdir -p "$PROJECT/rtl" "$PROJECT/constraints"
cp "$ROOT/test/fixtures/gcd/gcd.v" "$PROJECT/rtl/gcd.v"

cat >"$PROJECT/ecc.toml" <<EOF
[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/gcd.v"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "${PDK_ROOT}"

[flow]
preset = "rtl2gds"
skip_steps = ["lec"]
EOF

exec "$PY" "$ROOT/test/rpc_check.py" \
  --ecc "$ECC" \
  --project "$PROJECT" \
  --workspace default \
  --create \
  --run \
  --pdk-root "$PDK_ROOT" \
  --rtl "$PROJECT/rtl/gcd.v" \
  --flow-start Synthesis \
  --flow-end Synthesis \
  --expect-status success
