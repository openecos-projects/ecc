#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CHECK_VERSION_SH="${SCRIPT_DIR}/check-version.sh"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
  else
    echo "ERROR: no Python interpreter found for check-version tests" >&2
    exit 127
  fi
fi
export PYTHON_BIN

failures=0

make_fixture() {
  local dir="$1"
  local py_version="$2"
  local init_version="$3"

  mkdir -p "${dir}/chipcompiler"
  cat > "${dir}/pyproject.toml" <<EOF
[project]
name = "ecc"
version = "${py_version}"
EOF
  cat > "${dir}/chipcompiler/__init__.py" <<EOF
__version__ = "${init_version}"
EOF
}

run_case() {
  local name="$1"
  local expected_status="$2"
  local expected_ref="$3"
  local py_version="${4:-0.1.0-alpha.5}"
  local init_version="${5:-${py_version}}"
  local tmp
  local status

  tmp="$(mktemp -d)"
  make_fixture "${tmp}" "${py_version}" "${init_version}"

  set +e
  (
    cd "${tmp}"
    EXPECTED_REF="${expected_ref}" "${CHECK_VERSION_SH}" >output.txt 2>&1
  )
  status=$?
  set -e

  rm -rf "${tmp}"

  if [[ "${status}" -eq "${expected_status}" ]]; then
    echo "ok - ${name}"
    return
  fi

  echo "not ok - ${name}: expected status ${expected_status}, got ${status}" >&2
  failures=$((failures + 1))
}

run_case "empty expected ref passes" 0 ""
run_case "short tag passes" 0 "v0.1.0-alpha.5"
run_case "full tag ref passes" 0 "refs/tags/v0.1.0-alpha.5"
run_case "release branch passes" 0 "release/v0.1.0-alpha.5"
run_case "full release branch ref passes" 0 "refs/heads/release/v0.1.0-alpha.5"
run_case "mismatched release branch fails" 1 "release/v0.1.0-alpha.4"
run_case "unsupported explicit ref fails" 1 "refs/heads/feature/foo"
run_case "empty short tag fails" 1 "v"
run_case "empty full tag ref fails" 1 "refs/tags/v"
run_case "empty release branch fails" 1 "release/v"
run_case "empty full release branch ref fails" 1 "refs/heads/release/v"
run_case "package version mismatch fails" 1 "" "0.1.0-alpha.5" "0.1.0-alpha.4"

if [[ "${failures}" -ne 0 ]]; then
  echo "${failures} check-version test(s) failed" >&2
  exit 1
fi

echo "all check-version tests passed"
