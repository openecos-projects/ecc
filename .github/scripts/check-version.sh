#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"

read_pyproject_version() {
  "${PYTHON_BIN}" - <<'PY'
import pathlib
import re

text = pathlib.Path("pyproject.toml").read_text()
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
print(match.group(1) if match else "")
PY
}

read_chipcompiler_version() {
  "${PYTHON_BIN}" - <<'PY'
import pathlib
import re

text = pathlib.Path("chipcompiler/__init__.py").read_text()
match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
print(match.group(1) if match else "")
PY
}

normalize_expected_version() {
  local expected_ref="$1"

  case "${expected_ref}" in
    "")
      echo ""
      ;;
    refs/tags/v*)
      echo "${expected_ref#refs/tags/v}"
      ;;
    refs/heads/release/v*)
      echo "${expected_ref#refs/heads/release/v}"
      ;;
    release/v*)
      echo "${expected_ref#release/v}"
      ;;
    v*)
      echo "${expected_ref#v}"
      ;;
    *)
      echo "ERROR: unsupported expected ref '${expected_ref}'" >&2
      return 1
      ;;
  esac
}

py_ver="$(read_pyproject_version)"
init_ver="$(read_chipcompiler_version)"
expected_ref="${EXPECTED_REF:-${EXPECTED_TAG:-}}"

echo "pyproject.toml version: ${py_ver}"
echo "chipcompiler/__version__: ${init_ver}"

if [[ -z "${py_ver}" || -z "${init_ver}" ]]; then
  echo "ERROR: missing version metadata. pyproject.toml='${py_ver}' chipcompiler/__version__='${init_ver}'" >&2
  exit 1
fi

if [[ "${py_ver}" != "${init_ver}" ]]; then
  echo "ERROR: version mismatch. pyproject.toml='${py_ver}' chipcompiler/__version__='${init_ver}'" >&2
  exit 1
fi

expected_version="$(normalize_expected_version "${expected_ref}")"

if [[ -n "${expected_version}" && "${expected_version}" != "${py_ver}" ]]; then
  echo "ERROR: ref mismatch. ref='${expected_ref}' expected='v${py_ver}'" >&2
  exit 1
fi

echo "Version check passed: ${py_ver}"
