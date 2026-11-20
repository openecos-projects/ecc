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

release_url="${PDK_RELEASE_BASE_URL:-https://github.com/$repo/releases/download/$release}"
trap 'rm -f -- "$destination"/*.part' EXIT
fetch_asset() {
  local asset="$1" expected archive
  expected="$(awk -v asset="$asset" '$2 == asset {print $1}' "$destination/release-assets.sha256")"
  if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Missing or invalid v2 release checksum for $asset" >&2
    exit 1
  fi
  archive="$destination/$asset"
  echo "[download] $release: $asset"
  curl --fail --location --silent --show-error --retry 3 --connect-timeout 30 \
    --output "$archive.part" "$release_url/$asset"
  printf '%s  %s\n' "$expected" "$archive.part" | sha256sum --check --status
  mv -- "$archive.part" "$archive"
}

for vt in HVT LVT SVT; do
  base="ICsprout55_SC9T_BASIC_$vt"
  target="$destination/IP/STD_cell/$base"
  mkdir -p "$target"
  asset="${base}_liberty_nldm.tar.bz2"
  mapfile -t members < <(
    jq -r --arg prefix "IP/STD_cell/$base/" \
      '.resources[] | select(.role == "liberty" and (.path | startswith($prefix))) |
       .path | ltrimstr($prefix)' "$resources"
  )
  [[ ${#members[@]} -gt 0 ]] || { echo "No declared v2 NLDM resources for $vt" >&2; exit 1; }
  fetch_asset "$asset"
  tar --use-compress-program=bzip2 -xf "$destination/$asset" -C "$target" -- "${members[@]}"
  rm -- "$destination/$asset"

  asset="${base}_gds.tar.bz2"
  mapfile -t members < <(
    jq -r --arg prefix "IP/STD_cell/$base/" \
      '.resources[] | select(.role == "gds" and (.path | startswith($prefix))) |
       .path | ltrimstr($prefix)' "$resources"
  )
  [[ ${#members[@]} -gt 0 ]] || { echo "No declared v2 GDS resources for $vt" >&2; exit 1; }
  fetch_asset "$asset"
  tar --use-compress-program=bzip2 -xf "$destination/$asset" -C "$target" -- "${members[@]}"
  rm -- "$destination/$asset"
done
mkdir -p "$destination/IP/IO"
mapfile -t members < <(
  jq -r '.resources[] | select(.role == "gds" and (.path | startswith("IP/IO/"))) |
    .path | ltrimstr("IP/IO/")' "$resources"
)
[[ ${#members[@]} -gt 0 ]] || { echo "No declared v2 IO GDS resources" >&2; exit 1; }
fetch_asset ICsprout_55LLULP1225_IO_0901_gds.tar.bz2
tar --use-compress-program=bzip2 -xf \
  "$destination/ICsprout_55LLULP1225_IO_0901_gds.tar.bz2" \
  -C "$destination/IP/IO" -- "${members[@]}"
rm -- "$destination/ICsprout_55LLULP1225_IO_0901_gds.tar.bz2"

# Verify the v2 profile's declared NLDM and GDS files; unreferenced corners and CCS are out of scope.
while IFS= read -r resource; do
  awk -v resource="$resource" '$2 == resource {print; found = 1} END {if (!found) exit 1}' \
    "$destination/release-files.sha256" >> "$destination/ci-release-files.sha256"
done < <(jq -r '.resources[] | select(.role == "gds" or .role == "liberty") | .path' \
  "$resources")
(cd "$destination" && sha256sum --check --quiet ci-release-files.sha256)
rm -- "$destination/ci-release-files.sha256"
