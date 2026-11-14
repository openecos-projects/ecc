#!/usr/bin/env bash
# The public CI artifact contains provenance and this downloader, never the PDK.
set -euo pipefail
manifest="$1"
destination="$2"
read -r repo commit release < <(python3 - "$manifest" <<'PY'
import json
import re
import sys

source = json.load(open(sys.argv[1], encoding="utf-8"))
assert source["repo"] == "openecos-projects/icsprout55-pdk-v2"
assert re.fullmatch(r"[0-9a-f]{40}", source["git_commit"])
assert re.fullmatch(r"v2-[0-9.]+", source["release"])
print(source["repo"], source["git_commit"], source["release"])
PY
)
if [[ -e "$destination" ]]; then
  echo "PDK destination already exists: $destination" >&2
  exit 1
fi
command -v gh >/dev/null || { echo 'Install gh and authenticate with access to the private PDK repository.' >&2; exit 1; }
git init "$destination"
git -C "$destination" remote add origin "https://github.com/$repo.git"
GIT_TERMINAL_PROMPT=0 git -C "$destination" \
  -c credential.helper= -c 'credential.helper=!gh auth git-credential' \
  fetch --depth 1 origin "$commit"
git -C "$destination" checkout --detach FETCH_HEAD
test "$(git -C "$destination" rev-parse HEAD)" = "$commit"
# The existing Liberty/GDS release assets remain at their original public URLs.
# Credentials are used only by the Git credential helper, never stored in Git.
env -u GH_TOKEN -u GITHUB_TOKEN make -C "$destination" unzip RELEASE_TAG="$release"
(cd "$destination" && sha256sum --check --quiet release-files.sha256)
