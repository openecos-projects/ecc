#!/usr/bin/env bash
# =============================================================================
# ecc-cli-setup.sh -- ECC CLI one-command setup / environment check / dependency installation
#
# Features:
#   1. Downloads and installs the ecc CLI (prebuilt GitHub Release asset, Linux x86_64)
#   2. Configures PATH (creates ~/.ecc-env.sh and updates the shell rc; idempotent and repeatable)
#   3. Checks the ecc components, Yosys (with the slang frontend), Sizer, and the ics55 PDK
#   4. Installs missing dependencies:
#      - PDK: clone icsprout55-pdk and run `make unzip` to download liberty/GDS files
#      - Yosys: download the latest OSS CAD Suite (includes the slang frontend; LEC reuses this Yosys)
#      - Sizer: download the prebuilt ecc-sizer Release for the rtl2gds Timing optimization step
#
# Usage:
#   bash ecc-cli-setup.sh                 # Install, check, and complete dependencies
#   bash ecc-cli-setup.sh --check-only    # Run only the environment check; install nothing
#   bash ecc-cli-setup.sh --force         # Force download and reinstall of the ecc CLI
#   bash ecc-cli-setup.sh --skip-pdk --skip-tools --skip-sizer   # Install only the ecc CLI; the check fails if dependencies are unavailable
#
# Install a local build artifact (for development validation: build with PyInstaller in the ecc
# repository and package dist/release/ecc-cli-linux-x86_64.tar.gz; see section 6 of docs/ecc-cli-dev.cn.md):
#   ECC_CLI_URL=/abs/path/to/ecc/dist/release/ecc-cli-linux-x86_64.tar.gz \
#     bash ecc-cli-setup.sh --force --skip-pdk --skip-tools --skip-sizer
#   (ECC_CLI_URL also accepts a file:// URL; local files are copied directly without GH_PROXY.)
#
# Settings that can be overridden by environment variables (see the configuration section below):
#   ECC_VERSION / ECC_RELEASE_BASE / ECC_ASSET_NAME / ECC_CLI_URL
#   ECC_INSTALL_DIR / ECC_PDK_DIR / ECC_OSS_CAD_DIR / OSS_CAD_URL
#   ECC_SIZER_DIR / ECC_SIZER_URL
#   GH_PROXY (GitHub download proxy prefix, for example https://gh-proxy.org/)
#
# The ics55 PDK repository URL is fixed:
#   https://github.com/openecos-projects/icsprout55-pdk.git
# =============================================================================
set -euo pipefail

# ----------------------------- Configuration (environment overrides supported) -----------------------------
ECC_VERSION="${ECC_VERSION:-latest}"            # latest or an explicit tag, for example v0.1.0-alpha.11
ECC_RELEASE_BASE="${ECC_RELEASE_BASE:-https://github.com/openecos-projects/ecc/releases}"
ECC_ASSET_NAME="${ECC_ASSET_NAME:-ecc-cli-linux-x86_64.tar.gz}"
ECC_CLI_URL="${ECC_CLI_URL:-}"                 # Full direct URL; highest priority (override version or URL here)

ECC_INSTALL_DIR="${ECC_INSTALL_DIR:-$HOME/.local/ecc}"
ECC_PDK_DIR="${ECC_PDK_DIR:-$HOME/.local/icsprout55-pdk}"
ECC_PDK_URL="https://github.com/openecos-projects/icsprout55-pdk.git"   # Fixed URL
ECC_OSS_CAD_DIR="${ECC_OSS_CAD_DIR:-$HOME/.local/oss-cad-suite}"        # Root directory containing bin/
OSS_CAD_URL="${OSS_CAD_URL:-}"                 # Override with a full OSS CAD Suite direct URL
OSS_ARCH_PATTERN="${OSS_ARCH_PATTERN:-linux-x64}"

ECC_SIZER_DIR="${ECC_SIZER_DIR:-$HOME/.local/ecc-sizer}"                 # Sizer root containing bin/Sizer and src/sizer_os.tcl
ECC_SIZER_URL="${ECC_SIZER_URL:-}"              # Override with a full ecc-sizer prebuilt package direct URL

GH_PROXY="${GH_PROXY:-}"                       # For example: https://gh-proxy.org/ (empty disables the proxy)
ECC_ENV_FILE="${ECC_ENV_FILE:-$HOME/.ecc-env.sh}"
# -------------------------------------------------------------------------------------

FORCE=0
SKIP_PDK=0
SKIP_TOOLS=0
SKIP_SIZER=0
CHECK_ONLY=0
EDIT_SHELL_RC=1

# ----------------------------- Output helpers -----------------------------
C_G=$'\033[32m'; C_R=$'\033[31m'; C_Y=$'\033[33m'; C_B=$'\033[1m'; C_0=$'\033[0m'
msg()  { printf '%s\n' "${C_B}==>${C_0} $*"; }
ok()   { printf '    %s\n' "${C_G}[OK]${C_0}  $*"; }
warn() { printf '    %s\n' "${C_Y}[!!]${C_0}  $*"; }
fail() { printf '    %s\n' "${C_R}[FAIL]${C_0} $*"; }
die()  { fail "$*"; exit 1; }

usage() { sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//'; }

# ----------------------------- Argument parsing -----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)          FORCE=1 ;;
    --skip-pdk)       SKIP_PDK=1 ;;
    --skip-tools)     SKIP_TOOLS=1 ;;
    --skip-sizer)     SKIP_SIZER=1 ;;
    --check-only)     CHECK_ONLY=1 ;;
    --no-shell-rc)    EDIT_SHELL_RC=0 ;;
    -h|--help)        usage; exit 0 ;;
    *)                die "Unknown option: $1 (use --help for usage)" ;;
  esac
  shift
done

# ----------------------------- Required tools -----------------------------
DL_CMD=""
command -v curl >/dev/null 2>&1 && DL_CMD="curl"
[[ -z "$DL_CMD" ]] && command -v wget >/dev/null 2>&1 && DL_CMD="wget"
[[ -z "$DL_CMD" ]] && die "curl or wget is required; install one first"

fetch() { # fetch <url> <output-file>: downloads through GH_PROXY when configured; supports local paths and file:// URLs
  local url="$1" out="$2" local_path=""
  if [[ "$url" =~ ^file:// ]]; then
    local_path="${url#file://}"
  elif [[ "$url" != *://* && -f "$url" ]]; then
    local_path="$url"
  fi
  if [[ -n "$local_path" ]]; then
    [[ -f "$local_path" ]] || { warn "Local package does not exist: $local_path"; return 1; }
    cp -f "$local_path" "$out"
    return 0
  fi
  [[ -n "$GH_PROXY" ]] && url="${GH_PROXY}${url}"
  if [[ "$DL_CMD" == "curl" ]]; then
    curl -fL --retry 3 --connect-timeout 30 -o "$out" "$url"
  else
    wget -q --tries=3 -O "$out" "$url"
  fi
}

fetch_stdout() { # fetch_stdout <url>: writes to stdout and returns nonzero on failure
  local url="$1"
  if [[ "$DL_CMD" == "curl" ]]; then
    curl -fsSL --connect-timeout 30 "$url"
  else
    wget -q -O - "$url"
  fi
}

# ----------------------------- Detection helpers -----------------------------
ecc_installed() { [[ -x "$ECC_INSTALL_DIR/ecc" ]]; }

resolve_ecc_url() {
  if [[ -n "$ECC_CLI_URL" ]]; then
    echo "$ECC_CLI_URL"; return 0
  fi
  if [[ "$ECC_VERSION" == "latest" ]]; then
    echo "${ECC_RELEASE_BASE}/latest/download/${ECC_ASSET_NAME}"; return 0
  fi
  echo "${ECC_RELEASE_BASE}/download/${ECC_VERSION}/${ECC_ASSET_NAME}"
}

# Resolve the direct URL for the latest OSS CAD Suite Linux asset through the GitHub API.
resolve_oss_cad_url() {
  if [[ -n "$OSS_CAD_URL" ]]; then
    echo "$OSS_CAD_URL"; return 0
  fi
  local api="https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest" url
  url=$(fetch_stdout "$api" 2>/dev/null \
        | grep -oE "https://[^\"]*oss-cad-suite-${OSS_ARCH_PATTERN}-[^\"]*\.tgz" | head -1) || true
  [[ -n "$url" ]] || return 1
  echo "$url"
}

# Resolve the direct URL for the latest ecc-sizer linux-x64 prebuilt Release through the GitHub API.
# Asset names include the version, for example ecc-sizer-0.1.0-linux-x64.tar.gz, so API matching is required.
# If no tagged release exists, resolution fails and the caller suggests building from source.
resolve_sizer_url() {
  if [[ -n "$ECC_SIZER_URL" ]]; then
    echo "$ECC_SIZER_URL"; return 0
  fi
  local api="https://api.github.com/repos/openecos-projects/ecc-sizer/releases/latest" url
  url=$(fetch_stdout "$api" 2>/dev/null \
        | grep -oE "https://[^\"]*/download/[^\"]*linux-x64[^\"]*\.tar\.gz" | head -1) || true
  [[ -n "$url" ]] || return 1
  echo "$url"
}

# Select the Yosys binary ecc will use: CHIPCOMPILER_OSS_CAD_DIR/ECC_OSS_CAD_DIR first, then PATH.
pick_yosys() {
  local d="${CHIPCOMPILER_OSS_CAD_DIR:-$ECC_OSS_CAD_DIR}"
  if [[ -x "$d/bin/yosys" ]]; then echo "$d/bin/yosys"; return 0; fi
  if command -v yosys >/dev/null 2>&1; then command -v yosys; return 0; fi
  return 1
}

# Check the Yosys slang frontend, equivalent to ecc's internal check_slang_support.
# Either the built-in read_slang command or plugin -i slang is sufficient.
slang_ok() {
  local ybin="$1" dir out
  dir=$(dirname "$ybin")
  out=$(cd "$dir" && PATH="$dir:$PATH" "$ybin" -Q -T -p "help read_slang" 2>&1) \
    && [[ "$out" != *"No such command"* ]] && return 0
  (cd "$dir" && PATH="$dir:$PATH" "$ybin" -Q -T -p "plugin -i slang" >/dev/null 2>&1)
}

# Keep resolution consistent with chipcompiler/tools/ecc_sizer/utility.py:
# the Sizer binary comes from PATH or $ECC_SIZER_DIR/bin/Sizer, and the runtime root contains
# src/sizer_os.tcl. Search upward from the binary, including share/ecc-sizer and share/sizer.
# CHIPCOMPILER_ECC_SIZER_ROOT may specify the root directly.
sizer_binary() {
  local d="${CHIPCOMPILER_ECC_SIZER_ROOT:-$ECC_SIZER_DIR}"
  if [[ -x "$d/bin/Sizer" ]]; then echo "$d/bin/Sizer"; return 0; fi
  command -v Sizer >/dev/null 2>&1 && command -v Sizer
}

find_sizer_root() {
  local candidates=() bin p
  [[ -n "${CHIPCOMPILER_ECC_SIZER_ROOT:-}" ]] && candidates+=("${CHIPCOMPILER_ECC_SIZER_ROOT%/}")
  bin=$(sizer_binary) || true
  if [[ -n "$bin" ]]; then
    p=$(cd "$(dirname "$bin")" && pwd -P)
    while [[ "$p" != "/" ]]; do
      candidates+=("$p" "$p/share/ecc-sizer" "$p/share/sizer")
      p=$(dirname "$p")
    done
  fi
  (( ${#candidates[@]} )) || return 1
  for p in "${candidates[@]}"; do
    [[ -f "$p/src/sizer_os.tcl" ]] && { echo "$p"; return 0; }
  done
  return 1
}

sizer_ready() { sizer_binary >/dev/null 2>&1 && find_sizer_root >/dev/null 2>&1; }

# Keep this list in sync with the required ics55 files in chipcompiler/data/pdk.py.
pdk_ready() {
  local std="$1/IP/STD_cell/ics55_LLSC_H7C_V1p10C100"
  [[ -f "$1/prtech/techLEF/N551P6M_ecos.lef" ]] || return 1
  [[ -f "$std/ics55_LLSC_H7CR/lef/ics55_LLSC_H7CR_ecos.lef" ]] || return 1
  [[ -f "$std/ics55_LLSC_H7CL/lef/ics55_LLSC_H7CL_ecos.lef" ]] || return 1
  [[ -f "$std/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib" ]] || return 1
  [[ -f "$std/ics55_LLSC_H7CL/liberty/ics55_LLSC_H7CL_ss_rcworst_1p08_125_nldm.lib" ]] || return 1
}

# ----------------------------- Preflight -----------------------------
step_preflight() {
  msg "Preflight (system and required commands)"
  [[ "$(uname -s)" == "Linux" ]] || die "This script supports Linux only"
  [[ "$(uname -m)" == "x86_64" ]] \
    || warn "Current architecture $(uname -m) is not x86_64; override the asset name with ECC_ASSET_NAME / OSS_ARCH_PATTERN"
  local miss=()
  command -v tar    >/dev/null 2>&1 || miss+=(tar)
  command -v git    >/dev/null 2>&1 || miss+=(git)
  command -v make   >/dev/null 2>&1 || miss+=(make)
  command -v bzip2  >/dev/null 2>&1 || miss+=(bzip2)
  if (( ${#miss[@]} )); then
    die "Missing required commands: ${miss[*]} (Debian/Ubuntu: sudo apt install ${miss[*]})"
  fi
  ok "Required commands are available (using $DL_CMD for downloads)"
}

# ----------------------------- 1. Install ecc CLI -----------------------------
step_install_ecc() {
  msg "ECC CLI (installing to $ECC_INSTALL_DIR)"
  if ecc_installed && (( ! FORCE )); then
    ok "Already installed; skipping download: $("$ECC_INSTALL_DIR/ecc" --version 2>/dev/null || echo unknown)"
    ok "To upgrade or reinstall: bash $0 --force, or ECC_VERSION=<tag> bash $0 --force"
    return 0
  fi
  local url archive tmpdir
  url=$(resolve_ecc_url)
  tmpdir=$(mktemp -d)
  archive="$tmpdir/$ECC_ASSET_NAME"
  msg "Downloading $url"
  if ! fetch "$url" "$archive"; then
    # ECC_CLI_URL is an explicitly selected source, including local packages; do not fall back to the official asset.
    if [[ -n "$ECC_CLI_URL" ]]; then
      die "Failed to fetch the package specified by ECC_CLI_URL: $ECC_CLI_URL"
    fi
    # /releases/latest returns 404 when it excludes prereleases; fall back to the GitHub API to find the matching asset.
    warn "Direct download failed; trying the GitHub API to locate the asset..."
    local owner_repo alt
    owner_repo="${ECC_RELEASE_BASE#*://github.com/}"
    owner_repo="${owner_repo%/releases}"
    alt=$(fetch_stdout "https://api.github.com/repos/${owner_repo}/releases?per_page=20" 2>/dev/null \
          | grep -oE "https://[^\"]*/download/[^\"]*/${ECC_ASSET_NAME}" | head -1) || true
    [[ -n "$alt" ]] || die "Download failed. Set ECC_CLI_URL=<full-direct-url> and try again"
    url="$alt"
    fetch "$url" "$archive" || die "Download failed: $url"
  fi
  rm -rf "$ECC_INSTALL_DIR"   # Clear the old directory before extraction to avoid mixing incomplete/old installs with new files.
  mkdir -p "$ECC_INSTALL_DIR"
  tar -xzf "$archive" -C "$ECC_INSTALL_DIR"
  rm -rf "$tmpdir"
  ecc_installed || die "Did not find $ECC_INSTALL_DIR/ecc after extraction (the asset layout may have changed; check $ECC_ASSET_NAME)"
  ok "Installation complete: $("$ECC_INSTALL_DIR/ecc" --version 2>/dev/null || echo unknown)"
}

# ----------------------------- 2. PATH / environment variables -----------------------------
step_setup_env() {
  msg "Environment variables and PATH (writing $ECC_ENV_FILE)"
  local bin_dir="" sizer_bin=""
  [[ -x "$ECC_OSS_CAD_DIR/bin/yosys" ]] && bin_dir="$ECC_OSS_CAD_DIR/bin"
  [[ -x "$ECC_SIZER_DIR/bin/Sizer" ]] && sizer_bin="$ECC_SIZER_DIR/bin"

  {
    echo "# ecc CLI environment -- generated by ecc-cli-setup.sh"
    echo "export PATH=\"$ECC_INSTALL_DIR${bin_dir:+:$bin_dir}${sizer_bin:+:$sizer_bin}:\$PATH\""
    echo "export CHIPCOMPILER_ICS55_PDK_ROOT=\"$ECC_PDK_DIR\""
    if [[ -n "$bin_dir" ]]; then
      echo "export CHIPCOMPILER_OSS_CAD_DIR=\"$ECC_OSS_CAD_DIR\""
    fi
    if [[ -n "$sizer_bin" ]]; then
      echo "export CHIPCOMPILER_ECC_SIZER_ROOT=\"$ECC_SIZER_DIR\""
    fi
  } > "$ECC_ENV_FILE"
  ok "Wrote $ECC_ENV_FILE"

  # Convenience symlink: ~/.local/bin is on PATH by default on most distributions.
  if [[ -d "$HOME/.local/bin" ]] || [[ ":$PATH:" == *":$HOME/.local/bin:"* ]]; then
    mkdir -p "$HOME/.local/bin"
    ln -sf "$ECC_INSTALL_DIR/ecc" "$HOME/.local/bin/ecc"
    ok "Created symlink ~/.local/bin/ecc -> $ECC_INSTALL_DIR/ecc"
  fi

  if (( EDIT_SHELL_RC )); then
    local rcs=("$HOME/.bashrc") rc
    [[ "${SHELL:-}" == */zsh ]] && rcs=("$HOME/.zshrc")
    # Bash login shells (SSH or a new tmux window) read .profile instead of .bashrc. Because .profile often
    # does not source .bashrc, append the load line there as well when .bash_profile/.bash_login is absent.
    if [[ "${SHELL:-}" != */zsh ]] && [[ ! -f "$HOME/.bash_profile" && ! -f "$HOME/.bash_login" ]]; then
      rcs+=("$HOME/.profile")
    fi
    for rc in "${rcs[@]}"; do
      if [[ -f "$rc" ]] && ! grep -qF "$ECC_ENV_FILE" "$rc"; then
        printf '\n# Added by ecc-cli-setup.sh\n[ -f %q ] && . %q\n' "$ECC_ENV_FILE" "$ECC_ENV_FILE" >> "$rc"
        ok "Added a load line for $ECC_ENV_FILE to $rc (idempotent; no duplicate entries)"
      else
        ok "$rc is already configured or does not exist; skipping (use --no-shell-rc to disable this behavior)"
      fi
    done
  fi
  ok "Apply to the current shell now: source $ECC_ENV_FILE"
}

# ----------------------------- 3. PDK -----------------------------
step_pdk() {
  msg "ICS55 PDK ($ECC_PDK_DIR)"
  if pdk_ready "$ECC_PDK_DIR"; then
    ok "PDK is complete (tech LEF / LEF / liberty are present)"
    return 0
  fi
  if [[ ! -d "$ECC_PDK_DIR/.git" ]]; then
    msg "Cloning $ECC_PDK_URL (--depth 1)"
    rm -rf "$ECC_PDK_DIR"
    if [[ -n "$GH_PROXY" ]]; then
      git clone --depth 1 "${GH_PROXY}${ECC_PDK_URL}" "$ECC_PDK_DIR"
    else
      git clone --depth 1 "$ECC_PDK_URL" "$ECC_PDK_DIR"
    fi
  else
    ok "Repository already exists; completing data files"
  fi
  msg "Downloading and extracting liberty/GDS files (make unzip from PDK Releases; retries up to 3 times)"
  local make_args=(unzip)
  [[ -n "$GH_PROXY" ]] && make_args+=(USE_PROXY=true "GH_PROXY=$GH_PROXY")
  local attempt rc=1
  for attempt in 1 2 3; do
    if (cd "$ECC_PDK_DIR" && make "${make_args[@]}"); then rc=0; break; fi
    warn "Attempt $attempt failed; retrying (downloaded archives are retained and resume is supported)..."
  done
  (( rc )) && die "make unzip failed repeatedly; check network access or GH_PROXY and run the script again"
  pdk_ready "$ECC_PDK_DIR" && ok "PDK is ready" || die "Files are still missing after make unzip; check the log above"
}

# ----------------------------- 4. Yosys / OSS CAD Suite -----------------------------
step_tools() {
  msg "Yosys (synthesis tool with slang frontend)"
  local ybin=""
  if ybin=$(pick_yosys); then
    ok "Found Yosys: $ybin ($("$ybin" -V 2>/dev/null | head -1))"
    if slang_ok "$ybin"; then
      ok "slang frontend is available"
      return 0
    fi
    warn "This Yosys has no slang frontend -> installing the latest OSS CAD Suite (ecc prefers CHIPCOMPILER_OSS_CAD_DIR)"
  else
    warn "Yosys not found -> installing the latest OSS CAD Suite"
  fi

  local url tmpdir
  url=$(resolve_oss_cad_url) \
    || die "Cannot resolve the direct URL for the latest OSS CAD Suite (GitHub API rate limit or network restriction). Set OSS_CAD_URL=<direct-url> and try again"
  msg "Downloading $url (about 700+ MB; this may take a while)"
  tmpdir=$(mktemp -d)
  fetch "$url" "$tmpdir/oss-cad-suite.tgz" || { rm -rf "$tmpdir"; die "Download failed: $url"; }
  msg "Extracting and installing to $ECC_OSS_CAD_DIR"
  tar -xzf "$tmpdir/oss-cad-suite.tgz" -C "$tmpdir"
  rm -rf "$ECC_OSS_CAD_DIR"
  mv "$tmpdir"/oss-cad-suite "$ECC_OSS_CAD_DIR"
  rm -rf "$tmpdir"
  ybin="$ECC_OSS_CAD_DIR/bin/yosys"
  [[ -x "$ybin" ]] || die "Did not find $ybin after extraction"
  ok "Installation complete: $("$ybin" -V 2>/dev/null | head -1)"
  slang_ok "$ybin" && ok "slang frontend is available" || die "Yosys from OSS CAD Suite still has no slang frontend; report this to the ECC maintainers"
}

# ----------------------------- 5. Sizer (required for Timing optimization; LEC reuses Yosys) -----------------------------
step_sizer() {
  msg "Sizer (required by the rtl2gds Timing optimization step)"
  if sizer_ready; then
    ok "Ready: $(sizer_binary) (root: $(find_sizer_root))"
    return 0
  fi
  local url tmpdir top
  if ! url=$(resolve_sizer_url); then
    warn "ecc-sizer has no prebuilt Release yet (or the GitHub API is unavailable); skipping automatic installation (a new or --overwrite rtl2gds run fails preflight, while an existing workspace can still fail at Timing optimization)"
    warn "Build from source when needed (it depends on the OpenROAD submodule stack and may take time). Rerun this script after building for automatic detection:"
    cat <<EOF
      git clone --recursive https://github.com/openecos-projects/ecc-sizer.git
      cd ecc-sizer
      cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
      cmake --build build --target Sizer -j "\$(nproc)"     # output: build/src/Sizer
      export PATH="\$PWD/build/src:\$PATH"                  # or: export CHIPCOMPILER_ECC_SIZER_ROOT="\$PWD"
EOF
    return 0
  fi
  msg "Downloading $url"
  tmpdir=$(mktemp -d)
  fetch "$url" "$tmpdir/ecc-sizer.tar.gz" || { rm -rf "$tmpdir"; warn "Download failed: $url (the later check will fail)"; return 0; }
  msg "Extracting and installing to $ECC_SIZER_DIR"
  tar -xzf "$tmpdir/ecc-sizer.tar.gz" -C "$tmpdir"
  top=$(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d | head -1)
  [[ -n "$top" ]] || { rm -rf "$tmpdir"; warn "Unexpected archive layout (no top-level directory); skipping"; return 0; }
  mkdir -p "$(dirname "$ECC_SIZER_DIR")"
  rm -rf "$ECC_SIZER_DIR"
  mv "$top" "$ECC_SIZER_DIR"
  rm -rf "$tmpdir"
  [[ -x "$ECC_SIZER_DIR/bin/Sizer" && -f "$ECC_SIZER_DIR/src/sizer_os.tcl" ]] \
    || { warn "Package lacks bin/Sizer or src/sizer_os.tcl; skipping (the asset layout may have changed)"; return 0; }
  ok "Installation complete: $ECC_SIZER_DIR/bin/Sizer ($("$ECC_SIZER_DIR/bin/Sizer" --version 2>/dev/null | head -1 || echo unknown))"
}

# ----------------------------- 6. Summary check -----------------------------
step_verify() {
  msg "Summary check"
  local pass=1

  if ecc_installed; then
    ok "ecc CLI   : $ECC_INSTALL_DIR/ecc ($("$ECC_INSTALL_DIR/ecc" --version 2>/dev/null || echo unknown))"
  else
    fail "ecc CLI   : not installed"; pass=0
  fi

  if pdk_ready "$ECC_PDK_DIR"; then
    ok "PDK ics55 : $ECC_PDK_DIR (liberty/LEF/techLEF are present)"
  else
    fail "PDK ics55 : $ECC_PDK_DIR is incomplete (missing liberty or LEF)"; pass=0
  fi

  local ybin
  if ybin=$(pick_yosys); then
    if slang_ok "$ybin"; then
      ok "yosys     : $ybin (slang frontend is available)"
    else
      fail "yosys     : $ybin has no slang frontend"; pass=0
    fi
    ok "yosys_lec : reuses the same Yosys (read_verilog/equiv_*; no separate installation needed)"
  else
    fail "yosys     : not found"; pass=0
  fi

  if sizer_ready; then
    ok "sizer     : $(sizer_binary) (Timing optimization)"
  else
    fail "sizer     : not ready (required for rtl2gds Timing optimization)"; pass=0
  fi

  # Delegate component-level checks to the built-in CLI doctor; skip it if an older release lacks the command.
  if ecc_installed && "$ECC_INSTALL_DIR/ecc" doctor --help >/dev/null 2>&1; then
    if "$ECC_INSTALL_DIR/ecc" doctor >/dev/null 2>&1; then
      ok "ecc doctor: component check passed (including bundled components)"
    else
      fail "ecc doctor: required components are not ready; inspect with: $ECC_INSTALL_DIR/ecc doctor"; pass=0
    fi
  fi

  echo
  if (( pass )); then
    msg "Everything is ready. Quick start:"
    cat <<EOF
      source "$ECC_ENV_FILE"          # Apply to the current shell (new terminals apply it automatically)
      ecc init gcd && cd gcd          # Create a project (ecc.toml already uses CHIPCOMPILER_ICS55_PDK_ROOT)
      ecc check && ecc run            # Validate and run RTL-to-GDS
      ecc status && ecc log           # View progress and logs
EOF
  else
    warn "Some items are not ready (see above). Fix them and rerun this script to complete them incrementally."
    exit 1
  fi
}

# ----------------------------- Main flow -----------------------------
main() {
  msg "ECC CLI one-command setup script (ecc=$ECC_VERSION, PDK=$ECC_PDK_URL)"
  step_preflight
  if (( CHECK_ONLY )); then
    step_verify
    return 0
  fi
  step_install_ecc
  (( SKIP_TOOLS )) || step_tools
  (( SKIP_SIZER )) || step_sizer
  (( SKIP_PDK ))    || step_pdk
  step_setup_env
  step_verify
}

main "$@"
