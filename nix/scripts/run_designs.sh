#!/usr/bin/env bash
# Run real-design RTL-to-GDS flows with a given ecc binary, in parallel.
#
# Designs live in an external directory (typically another repository); each
# design is a self-contained ECC project: <name>/ecc.toml + rtl/ (+ optional
# constraints/ and FileCheck .check files consumed by the lit e2e suite).
# pdk.root stays empty in ecc.toml; the PDK is injected here via
# CHIPCOMPILER_ICS55_PDK_ROOT.
#
# Usage:
#   run_designs.sh --ecc BIN --designs-dir DIR [--design NAME ...]
#                  [--jobs N] [--out-root DIR] [--pdk-root DIR]
#
# Layout produced under --out-root (default: ci-artifacts/e2e):
#   <name>/          copied project; flow output in <name>/default/
#   <name>.log       full ecc run log
#
# Exit status is 0 only if every selected design produced
# <name>/default/home/flow.json; failures of one design do not stop the rest.

set -euo pipefail

usage() { sed -n '2,20p' "$0"; exit 2; }

ecc=""
designs_dir=""
out_root=""
pdk_root=""
jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
declare -a designs=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ecc) ecc="${2:?}"; shift 2 ;;
    --designs-dir) designs_dir="${2:?}"; shift 2 ;;
    --design) designs+=("${2:?}"); shift 2 ;;
    --jobs) jobs="${2:?}"; shift 2 ;;
    --out-root) out_root="${2:?}"; shift 2 ;;
    --pdk-root) pdk_root="${2:?}"; shift 2 ;;
    -h | --help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$ecc" && -x "$ecc" ]] || { echo "error: --ecc must be an executable ecc binary" >&2; exit 2; }
[[ -n "$designs_dir" && -d "$designs_dir" ]] || { echo "error: --designs-dir must be a directory" >&2; exit 2; }
out_root="${out_root:-ci-artifacts/e2e}"
mkdir -p "$out_root"
out_root="$(cd "$out_root" && pwd)"
designs_dir="$(cd "$designs_dir" && pwd)"
ecc="$(cd "$(dirname "$ecc")" && pwd)/$(basename "$ecc")"

if [[ -z "$pdk_root" ]]; then
  pdk_root="${CHIPCOMPILER_ICS55_PDK_ROOT:-}"
fi
if [[ -z "$pdk_root" ]]; then
  for candidate in "$PWD/../pdk/icsprout55-pdk" "${ECC_REPO_ROOT:-$PWD}/../pdk/icsprout55-pdk"; do
    [[ -d "$candidate" ]] && pdk_root="$(cd "$candidate" && pwd)" && break
  done
fi
[[ -n "$pdk_root" && -d "$pdk_root" ]] || {
  echo "error: PDK root not found; pass --pdk-root or set CHIPCOMPILER_ICS55_PDK_ROOT" >&2
  exit 1
}

if [[ ${#designs[@]} -eq 0 ]]; then
  while IFS= read -r path; do
    designs+=("$(basename "$(dirname "$path")")")
  done < <(find "$designs_dir" -mindepth 2 -maxdepth 2 -name ecc.toml | sort)
fi
[[ ${#designs[@]} -gt 0 ]] || { echo "error: no designs (no */ecc.toml under $designs_dir)" >&2; exit 2; }

run_one() {
  local name="$1"
  local src="$DESIGNS_DIR/$name"
  local dst="$OUT_ROOT/$name"
  local log="$OUT_ROOT/$name.log"

  if [[ ! -f "$src/ecc.toml" ]]; then
    echo "FAIL $name (missing $src/ecc.toml)"
    return 1
  fi
  rm -rf "$dst"
  mkdir -p "$OUT_ROOT"
  cp -a "$src" "$dst"
  if CHIPCOMPILER_ICS55_PDK_ROOT="$PDK_ROOT" "$ECC" run --project "$dst" --workspace default --plain >"$log" 2>&1 \
    && [[ -f "$dst/default/home/flow.json" ]]; then
    echo "PASS $name"
  else
    echo "FAIL $name (log: $log)"
    return 1
  fi
}

export ECC="$ecc" DESIGNS_DIR="$designs_dir" OUT_ROOT="$out_root" PDK_ROOT="$pdk_root"
export -f run_one

status=0
printf '%s\n' "${designs[@]}" | xargs -P "$jobs" -I{} bash -c 'run_one "$@"' _ {} >"$out_root/summary.txt" || status=$?
cat "$out_root/summary.txt"
exit "$status"
