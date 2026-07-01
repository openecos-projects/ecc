#!/usr/bin/env bash
set -euo pipefail

ci_workflow=".github/workflows/ci.yml"
auto_tag_workflow=".github/workflows/auto-tag.yml"
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

assert_contains "${ci_workflow}" "      - main" "CI runs on main pushes"
assert_contains "${ci_workflow}" "      - 'release/v*'" "CI runs on release branch pushes"
assert_contains "${ci_workflow}" "          expected_ref: \${{ startsWith(github.ref, 'refs/heads/release/v') && github.ref || '' }}" "release branches pass expected_ref"
assert_contains "${ci_workflow}" "      - '.github/scripts/**'" "PR CI covers GitHub helper scripts"

assert_not_contains "${auto_tag_workflow}" "  push:" "auto tag has no automatic push trigger"
assert_not_contains "${auto_tag_workflow}" "git push origin" "auto tag does not push release tags"

if [[ "${failures}" -ne 0 ]]; then
  echo "${failures} release workflow test(s) failed" >&2
  exit 1
fi

echo "all release workflow tests passed"
