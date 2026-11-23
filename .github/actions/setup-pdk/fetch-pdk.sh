#!/usr/bin/env bash
# Fetch the v2 CI subset; the full CCS Liberty set is not used by ECC CI.
set -euo pipefail
manifest="$1"
destination="$2"
resources="$(dirname "$0")/ics55-v2-description.json"
if [[ ! -f "$resources" ]]; then
  resources="$(dirname "$0")/../../../chipcompiler/pdk/profiles/ics55-v2-description.json"
fi
test -s "$resources"
repo="$(jq -er '.repo | select(. == "openecos-projects/icsprout55-pdk")' "$manifest")"
commit="$(jq -er '.git_commit | select(test("^[0-9a-f]{40}$"))' "$manifest")"
release="$(jq -er '.release | select(test("^v2-[0-9.]+$"))' "$manifest")"
if [[ -e "$destination" ]]; then
  echo "PDK destination already exists: $destination" >&2
  exit 1
fi
git init "$destination"
git -C "$destination" remote add origin "https://github.com/$repo.git"
GIT_TERMINAL_PROMPT=0 git -C "$destination" fetch --depth 1 origin "$commit"
git -C "$destination" checkout --detach FETCH_HEAD
test "$(git -C "$destination" rev-parse HEAD)" = "$commit"

[[ "$(cat "$destination/VERSION")" == ics55-v2 ]] || { echo "Expected ICS55 v2 data" >&2; exit 1; }

release_url="${PDK_RELEASE_BASE_URL:-https://github.com/$repo/releases/download/$release}"
trap 'rm -f -- "$destination"/*.part' EXIT
extract_asset() {
  local asset="$1" directory="$2" role="$3" expected
  local archive="$destination/$asset.part"
  local -a members
  mapfile -t members < <(jq -r --arg prefix "$directory/" --arg role "$role" '
    .resources[] | select(.role == $role) | .path | select(startswith($prefix)) | ltrimstr($prefix)
  ' "$resources")
  [[ ${#members[@]} -gt 0 ]] || { echo "No declared $role resources for $asset" >&2; exit 1; }
  expected="$(awk -v asset="$asset" '$2 == asset {print $1}' "$destination/release-assets.sha256")"
  if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Missing or invalid v2 release checksum for $asset" >&2
    exit 1
  fi
  echo "[download] $release: $asset"
  curl --fail --location --silent --show-error --retry 3 --connect-timeout 30 \
    --output "$archive" "$release_url/$asset"
  printf '%s  %s\n' "$expected" "$archive" | sha256sum --check --status
  mkdir -p "$destination/$directory"
  tar -xjf "$archive" -C "$destination/$directory" -- "${members[@]}"
  rm -- "$archive"
}

for vt in HVT LVT SVT; do
  base="ICsprout55_SC9T_BASIC_$vt"
  extract_asset "${base}_liberty_nldm.tar.bz2" "IP/STD_cell/$base" liberty
  extract_asset "${base}_gds.tar.bz2" "IP/STD_cell/$base" gds
done
extract_asset ICsprout_55LLULP1225_IO_0901_gds.tar.bz2 IP/IO gds

# Verify the v2 profile's declared NLDM and GDS files; unreferenced corners and CCS are out of scope.
while IFS= read -r resource; do
  awk -v resource="$resource" '$2 == resource {print; found = 1} END {if (!found) exit 1}' \
    "$destination/release-files.sha256" >> "$destination/ci-release-files.sha256"
done < <(jq -r '.resources[] | select(.role == "gds" or .role == "liberty") | .path' \
  "$resources")
(cd "$destination" && sha256sum --check --quiet ci-release-files.sha256)
rm -- "$destination/ci-release-files.sha256"
