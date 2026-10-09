#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: bash install-ecc-skill.sh [--replace] [SKILL_DIR]' \
    'Default: $HOME/.agents/skills/ecc-cli plus a $HOME/.claude/skills/ecc-cli symlink to it.' \
    'The default target serves Codex; the symlink exposes the same installation to Claude Code.' \
    'Kimi Code discovers the default target through its own ~/.agents/skills/ scan; no extra entry is created.' \
    'Existing installations are refused unless --replace is supplied.' \
    'Replacement preserves the previous directory as a sibling tar.gz backup.' \
    'A custom SKILL_DIR is installed as-is without the Claude Code symlink.'
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
home_dir="$(cd -- "$HOME" && pwd -P)"
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

claude_skills_dir="$HOME/.claude/skills"
claude_entry="$claude_skills_dir/ecc-cli"
claude_link=false
if [[ "$target" == "$home_dir/.agents/skills/ecc-cli" ]]; then
  claude_link=true
  if [[ -L "$claude_entry" ]]; then
    [[ "$(readlink -- "$claude_entry")" == "$target" ]] || {
      printf 'Claude Code entry is a symlink pointing elsewhere; review it: %s\n' "$claude_entry" >&2
      exit 1
    }
  elif [[ -e "$claude_entry" ]]; then
    [[ -d "$claude_entry" ]] || { printf 'Claude Code entry is not a directory: %s\n' "$claude_entry" >&2; exit 1; }
    [[ "$replace" == true ]] || {
      printf 'Claude Code entry exists; review it before using --replace: %s\n' "$claude_entry" >&2
      exit 1
    }
  fi
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

claude_backup=''
claude_old=''
if [[ "$claude_link" != true ]]; then
  printf 'Custom SKILL_DIR given; no Claude Code symlink created: %s\n' "$claude_entry"
else
  if [[ -d "$claude_entry" && ! -L "$claude_entry" ]]; then
    claude_backup="$(mktemp --suffix=.tar.gz "$claude_skills_dir/.ecc-cli-backup.XXXXXX")"
    if ! tar -czf "$claude_backup" -C "$claude_skills_dir" ecc-cli; then
      rm -f -- "$claude_backup"
      printf 'Could not preserve the existing Claude Code entry; no replacement performed.\n' >&2
      exit 1
    fi
    claude_old="$(mktemp -d "$claude_skills_dir/.ecc-cli-old.XXXXXX")"
    rmdir -- "$claude_old"
    if ! mv -T -- "$claude_entry" "$claude_old"; then
      printf 'Could not set aside the existing Claude Code entry; it was left unchanged.\n' >&2
      exit 1
    fi
  fi
  if [[ ! -e "$claude_entry" && ! -L "$claude_entry" ]]; then
    mkdir -p -- "$claude_skills_dir"
    if ! ln -s -- "$target" "$claude_entry"; then
      printf 'Could not create the Claude Code symlink: %s\n' "$claude_entry" >&2
      if [[ -n "$claude_old" && -d "$claude_old" && ! -e "$claude_entry" && ! -L "$claude_entry" ]]; then
        if mv -T -- "$claude_old" "$claude_entry"; then
          printf 'Previous Claude Code entry restored.\n'
        else
          printf 'Could not restore the previous Claude Code entry; it remains at: %s\n' "$claude_old" >&2
        fi
      fi
      exit 1
    fi
  fi
  if [[ -n "$claude_old" && -d "$claude_old" ]]; then
    rm -rf -- "$claude_old"
  fi
  printf 'Claude Code entry: %s -> %s\n' "$claude_entry" "$target"
  if [[ -n "$claude_backup" ]]; then
    printf 'Previous Claude Code entry preserved: %s\n' "$claude_backup"
  fi
fi
printf 'Start a new session and invoke the skill (Codex: $ecc-cli; Claude Code: /ecc-cli; Kimi Code: /skill:ecc-cli).\n'
