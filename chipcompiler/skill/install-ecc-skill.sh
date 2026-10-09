#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: bash install-ecc-skill.sh [--replace] [SKILL_DIR]' \
    'Default: $HOME/.agents/skills/ecc-cli' \
    'Existing installations are refused unless --replace is supplied.' \
    'Replacement preserves the previous directory as a sibling tar.gz backup.'
}

replace=false
target=''
while (($#)); do
  case "$1" in
    --replace) replace=true ;;
    --help|-h) usage; exit 0 ;;
    --*) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    *)
      if [[ -n "$target" ]]; then
        usage >&2
        exit 2
      fi
      target="$1"
      ;;
  esac
  shift
done

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
target="${target:-$HOME/.agents/skills/ecc-cli}"
while [[ "$target" == */ ]]; do
  target="${target%/}"
done
if [[ -z "$target" || "$target" != /* || "$(basename -- "$target")" != ecc-cli ]]; then
  printf 'SKILL_DIR must be an absolute directory ending in /ecc-cli.\n' >&2
  exit 2
fi
if [[ -L "$target" || ( -e "$target" && ! -d "$target" ) ]]; then
  printf 'Refusing a symlink or non-directory target: %s\n' "$target" >&2
  exit 1
fi
if [[ -d "$target" && "$replace" != true ]]; then
  printf 'Installation exists; review it before using --replace: %s\n' "$target" >&2
  exit 1
fi

references=(environment-project run-workspaces config-floorplan qor-signoff optimization troubleshooting installation-sources)
for relative_path in SKILL.md agents/config.yaml; do
  [[ -f "$source_dir/$relative_path" ]] || { printf 'Missing source: %s\n' "$relative_path" >&2; exit 1; }
done
for reference in "${references[@]}"; do
  [[ -f "$source_dir/references/$reference.md" ]] || { printf 'Missing reference: %s\n' "$reference" >&2; exit 1; }
done

parent="$(dirname -- "$target")"
mkdir -p -- "$parent"
parent="$(cd -- "$parent" && pwd -P)"
target="$parent/ecc-cli"
if [[ "$target" == "$source_dir" || "$source_dir" == "$target/"* ]]; then
  printf 'Refusing to replace the source directory or its ancestor.\n' >&2
  exit 1
fi
stage="$(mktemp -d "$parent/.ecc-cli-install.XXXXXX")"
old_stage=''
cleanup() {
  if [[ -n "$old_stage" && -d "$old_stage" && ! -e "$target" && ! -L "$target" ]]; then
    if ! mv -T -- "$old_stage" "$target"; then
      printf 'Could not restore the old directory; it remains at: %s\n' "$old_stage" >&2
    fi
  fi
  rm -rf -- "$stage"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -- "$stage/references" "$stage/agents"
cp -- "$source_dir/SKILL.md" "$stage/SKILL.md"
cp -- "$source_dir/agents/config.yaml" "$stage/agents/openai.yaml"
for reference in "${references[@]}"; do
  cp -- "$source_dir/references/$reference.md" "$stage/references/$reference.md"
done

backup=''
if [[ -d "$target" ]]; then
  backup="$(mktemp --suffix=.tar.gz "$parent/.ecc-cli-backup.XXXXXX")"
  if ! tar -czf "$backup" -C "$parent" ecc-cli; then
    rm -f -- "$backup"
    printf 'Could not preserve the existing installation; no replacement performed.\n' >&2
    exit 1
  fi
  old_stage="$(mktemp -d "$parent/.ecc-cli-old.XXXXXX")"
  rmdir -- "$old_stage"
  mv -T -- "$target" "$old_stage"
fi
if ! mv -T -- "$stage" "$target"; then
  if [[ -n "$old_stage" ]]; then
    mv -T -- "$old_stage" "$target"
  fi
  printf 'Installation failed; previous installation restored when present.\n' >&2
  exit 1
fi
if [[ -n "$old_stage" ]]; then
  rm -rf -- "$old_stage"
fi
printf 'Installed: %s\n' "$target"
if [[ -n "$backup" ]]; then
  printf 'Previous installation preserved: %s\n' "$backup"
fi
printf 'Start a new Codex session in the appropriate skill scope and invoke $ecc-cli.\n'
