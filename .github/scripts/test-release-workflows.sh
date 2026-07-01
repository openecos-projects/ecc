#!/usr/bin/env bash
set -euo pipefail

ci_workflow=".github/workflows/ci.yml"
auto_tag_workflow=".github/workflows/auto-tag.yml"
check_version_sh=".github/scripts/check-version.sh"
check_version_py=".github/scripts/check-version.py"
failures=0

assert_contains() {
  local file="$1"
  local needle="$2"
  local name="$3"

  if grep -Fq -- "${needle}" "${file}"; then
    echo "ok - ${name}"
    return
  fi

  echo "not ok - ${name}: missing '${needle}' in ${file}" >&2
  failures=$((failures + 1))
}

assert_not_contains() {
  local file="$1"
  local needle="$2"
  local name="$3"

  if [[ ! -e "${file}" ]] || ! grep -Fq -- "${needle}" "${file}"; then
    echo "ok - ${name}"
    return
  fi

  echo "not ok - ${name}: found '${needle}' in ${file}" >&2
  failures=$((failures + 1))
}

assert_file_exists() {
  local file="$1"
  local name="$2"

  if [[ -f "${file}" ]]; then
    echo "ok - ${name}"
    return
  fi

  echo "not ok - ${name}: missing ${file}" >&2
  failures=$((failures + 1))
}

assert_contains "${ci_workflow}" "      - main" "CI runs on main pushes"
assert_contains "${ci_workflow}" "      - 'release/v*'" "CI runs on release branch pushes"
assert_contains "${ci_workflow}" "startsWith(github.ref, 'refs/heads/release/v') && github.ref" "release branch pushes pass expected_ref"
assert_contains "${ci_workflow}" "startsWith(github.base_ref, 'release/v') && github.base_ref" "release branch pull requests pass expected_ref"
assert_contains "${ci_workflow}" "      - '.github/scripts/**'" "PR CI covers GitHub helper scripts"

assert_file_exists "${check_version_py}" "version checker uses a Python script"
assert_contains "${check_version_sh}" "check-version.py" "shell wrapper delegates to Python script"
assert_not_contains "${check_version_sh}" "<<'PY'" "shell wrapper does not inline Python"

assert_not_contains "${auto_tag_workflow}" "  push:" "auto tag has no automatic push trigger"
assert_not_contains "${auto_tag_workflow}" "git push origin" "auto tag does not push release tags"

if [[ "${failures}" -ne 0 ]]; then
  echo "${failures} release workflow test(s) failed" >&2
  exit 1
fi

echo "all release workflow tests passed"
