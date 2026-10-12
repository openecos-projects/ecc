#!/usr/bin/env bash
# Materialize a temp gcd project (ecc.toml + RTL) for project scenario lit.
# Usage: prepare_gcd_project.sh PROJECT_DIR
# Env: CHIPCOMPILER_ICS55_PDK_ROOT (required), ECC_REPO_ROOT (optional)
set -euo pipefail

project="${1:?usage: $0 PROJECT_DIR}"
root="${ECC_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
pdk_root="${CHIPCOMPILER_ICS55_PDK_ROOT:?CHIPCOMPILER_ICS55_PDK_ROOT is required}"
rtl_src="$root/test/fixtures/gcd/gcd.v"
test -f "$rtl_src"

rm -rf "$project"
mkdir -p "$project/rtl" "$project/constraints"
cp "$rtl_src" "$project/rtl/gcd.v"

cat >"$project/ecc.toml" <<EOF
[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/gcd.v"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "${pdk_root}"

[flow]
preset = "rtl2gds"
skip_steps = ["lec"]
EOF
