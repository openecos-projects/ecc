#!/usr/bin/env bash
# CLI --project scenario: ecc run (Synthesis) then ecc status --project.
# Writes status.plain.txt under OUT_DIR for FileCheck.
#
# Usage: run_cli_project_scenario.sh OUT_DIR
# Env: CHIPCOMPILER_ICS55_PDK_ROOT, ECC_REPO_ROOT, ECC, PYTHON
set -euo pipefail

out_dir="${1:?usage: $0 OUT_DIR}"
root="${ECC_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export ECC_REPO_ROOT="$root"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ecc="${ECC:-$root/.venv/bin/ecc}"
test -x "$ecc"

mkdir -p "$out_dir"
project="$out_dir/project"
bash "$here/prepare_gcd_project.sh" "$project"

# Bounded Synthesis via CLI --project (user-facing path).
"$ecc" run \
  --project "$project" \
  --from Synthesis \
  --to Synthesis \
  --plain \
  | tee "$out_dir/run.plain.txt"

"$ecc" status \
  --project "$project" \
  --workspace default \
  --plain \
  | tee "$out_dir/status.plain.txt"
