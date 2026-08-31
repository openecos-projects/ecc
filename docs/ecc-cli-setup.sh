#!/usr/bin/env bash
# =============================================================================
# ecc-cli-setup.sh — ECC CLI 一键安装 / 环境自检 / 依赖补齐
#
# 功能：
#   1. 下载并安装 ecc CLI（GitHub Releases 预编译包，Linux x86_64）
#   2. 配置 PATH（生成 ~/.ecc-env.sh 并写入 shell rc，幂等可重复运行）
#   3. 环境自检：ecc 组件 / Yosys(+slang 前端) / ics55 PDK 完整性
#   4. 补齐缺失依赖：
#      - PDK：clone icsprout55-pdk 并 `make unzip` 下载 liberty/GDS
#      - Yosys：下载 OSS CAD Suite 最新发行版（内置 slang 前端）
#
# 用法：
#   bash ecc-cli-setup.sh                 # 一键安装 + 自检 + 补齐
#   bash ecc-cli-setup.sh --check-only    # 只做环境体检，不安装任何东西
#   bash ecc-cli-setup.sh --force         # 强制重新下载安装 ecc CLI
#   bash ecc-cli-setup.sh --skip-pdk --skip-tools   # 只装 ecc CLI 本体
#
# 可通过环境变量覆盖的配置（见下方"配置区"）：
#   ECC_VERSION / ECC_RELEASE_BASE / ECC_ASSET_NAME / ECC_CLI_URL
#   ECC_INSTALL_DIR / ECC_PDK_DIR / ECC_OSS_CAD_DIR / OSS_CAD_URL
#   GH_PROXY（GitHub 下载代理前缀，如 https://gh-proxy.org/）
#
# ics55 PDK 仓库地址固定为：
#   https://github.com/openecos-projects/icsprout55-pdk.git
# =============================================================================
set -euo pipefail

# ----------------------------- 配置区（可用环境变量覆盖） -----------------------------
ECC_VERSION="${ECC_VERSION:-latest}"            # latest 或显式 tag，如 v0.1.0-alpha.11
ECC_RELEASE_BASE="${ECC_RELEASE_BASE:-https://github.com/openecos-projects/ecc/releases}"
ECC_ASSET_NAME="${ECC_ASSET_NAME:-ecc-cli-linux-x86_64.tar.gz}"
ECC_CLI_URL="${ECC_CLI_URL:-}"                 # 完整直链，优先级最高（版本/地址变了改这里）

ECC_INSTALL_DIR="${ECC_INSTALL_DIR:-$HOME/.local/ecc}"
ECC_PDK_DIR="${ECC_PDK_DIR:-$HOME/.local/icsprout55-pdk}"
ECC_PDK_URL="https://github.com/openecos-projects/icsprout55-pdk.git"   # 固定不变
ECC_OSS_CAD_DIR="${ECC_OSS_CAD_DIR:-$HOME/.local/oss-cad-suite}"        # 含 bin/ 的根目录
OSS_CAD_URL="${OSS_CAD_URL:-}"                 # OSS CAD Suite 完整直链覆盖
OSS_ARCH_PATTERN="${OSS_ARCH_PATTERN:-linux-x64}"

GH_PROXY="${GH_PROXY:-}"                       # 例：https://gh-proxy.org/（留空不用代理）
ECC_ENV_FILE="${ECC_ENV_FILE:-$HOME/.ecc-env.sh}"
# -------------------------------------------------------------------------------------

FORCE=0
SKIP_PDK=0
SKIP_TOOLS=0
CHECK_ONLY=0
EDIT_SHELL_RC=1

# ----------------------------- 输出工具 -----------------------------
C_G=$'\033[32m'; C_R=$'\033[31m'; C_Y=$'\033[33m'; C_B=$'\033[1m'; C_0=$'\033[0m'
msg()  { printf '%s\n' "${C_B}==>${C_0} $*"; }
ok()   { printf '    %s\n' "${C_G}[OK]${C_0}  $*"; }
warn() { printf '    %s\n' "${C_Y}[!!]${C_0}  $*"; }
fail() { printf '    %s\n' "${C_R}[FAIL]${C_0} $*"; }
die()  { fail "$*"; exit 1; }

usage() { sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; }

# ----------------------------- 参数解析 -----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)          FORCE=1 ;;
    --skip-pdk)       SKIP_PDK=1 ;;
    --skip-tools)     SKIP_TOOLS=1 ;;
    --check-only)     CHECK_ONLY=1 ;;
    --no-shell-rc)    EDIT_SHELL_RC=0 ;;
    -h|--help)        usage; exit 0 ;;
    *)                die "未知参数: $1（--help 查看用法）" ;;
  esac
  shift
done

# ----------------------------- 基础工具 -----------------------------
DL_CMD=""
command -v curl >/dev/null 2>&1 && DL_CMD="curl"
[[ -z "$DL_CMD" ]] && command -v wget >/dev/null 2>&1 && DL_CMD="wget"
[[ -z "$DL_CMD" ]] && die "需要 curl 或 wget，请先安装"

fetch() { # fetch <url> <输出文件>   下载（可选走 GH_PROXY）
  local url="$1" out="$2"
  [[ -n "$GH_PROXY" ]] && url="${GH_PROXY}${url}"
  if [[ "$DL_CMD" == "curl" ]]; then
    curl -fL --retry 3 --connect-timeout 30 -o "$out" "$url"
  else
    wget -q --tries=3 -O "$out" "$url"
  fi
}

fetch_stdout() { # fetch_stdout <url>   输出到 stdout，失败返回非 0
  local url="$1"
  if [[ "$DL_CMD" == "curl" ]]; then
    curl -fsSL --connect-timeout 30 "$url"
  else
    wget -q -O - "$url"
  fi
}

# ----------------------------- 检测函数 -----------------------------
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

# 从 GitHub API 解析 OSS CAD Suite 最新版 linux 资产直链
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

# 选出 ecc 实际会用的 yosys：优先 CHIPCOMPILER_OSS_CAD_DIR/ECC_OSS_CAD_DIR，其次 PATH
pick_yosys() {
  local d="${CHIPCOMPILER_OSS_CAD_DIR:-$ECC_OSS_CAD_DIR}"
  if [[ -x "$d/bin/yosys" ]]; then echo "$d/bin/yosys"; return 0; fi
  if command -v yosys >/dev/null 2>&1; then command -v yosys; return 0; fi
  return 1
}

# yosys slang 前端探测（等价于 ecc 内部 check_slang_support 的内置分支）
slang_ok() {
  local ybin="$1" out
  out=$(cd "$(dirname "$ybin")" && PATH="$(dirname "$ybin"):$PATH" \
        "$ybin" -Q -T -p "help read_slang" 2>&1) || return 1
  [[ "$out" != *"No such command"* ]]
}

# 与 chipcompiler/data/pdk.py 中 ics55 的必需文件清单保持一致
pdk_ready() {
  local std="$1/IP/STD_cell/ics55_LLSC_H7C_V1p10C100"
  [[ -f "$1/prtech/techLEF/N551P6M_ecos.lef" ]] || return 1
  [[ -f "$std/ics55_LLSC_H7CR/lef/ics55_LLSC_H7CR_ecos.lef" ]] || return 1
  [[ -f "$std/ics55_LLSC_H7CL/lef/ics55_LLSC_H7CL_ecos.lef" ]] || return 1
  [[ -f "$std/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib" ]] || return 1
  [[ -f "$std/ics55_LLSC_H7CL/liberty/ics55_LLSC_H7CL_ss_rcworst_1p08_125_nldm.lib" ]] || return 1
}

# ----------------------------- 前置检查 -----------------------------
step_preflight() {
  msg "前置检查（系统与基础命令）"
  [[ "$(uname -s)" == "Linux" ]] || die "本脚本仅支持 Linux"
  [[ "$(uname -m)" == "x86_64" ]] \
    || warn "当前架构 $(uname -m) 非 x86_64：请通过 ECC_ASSET_NAME / OSS_ARCH_PATTERN 覆盖资产名"
  local miss=()
  command -v tar    >/dev/null 2>&1 || miss+=(tar)
  command -v git    >/dev/null 2>&1 || miss+=(git)
  command -v make   >/dev/null 2>&1 || miss+=(make)
  command -v bzip2  >/dev/null 2>&1 || miss+=(bzip2)
  if (( ${#miss[@]} )); then
    die "缺少基础命令: ${miss[*]}（Debian/Ubuntu: sudo apt install ${miss[*]}）"
  fi
  ok "基础命令齐备（下载用 $DL_CMD）"
}

# ----------------------------- 1. 安装 ecc CLI -----------------------------
step_install_ecc() {
  msg "ECC CLI（安装到 $ECC_INSTALL_DIR）"
  if ecc_installed && (( ! FORCE )); then
    ok "已安装，跳过下载：$("$ECC_INSTALL_DIR/ecc" --version 2>/dev/null || echo unknown)"
    ok "如需升级/重装：bash $0 --force，或 ECC_VERSION=<tag> bash $0 --force"
    return 0
  fi
  local url archive tmpdir
  url=$(resolve_ecc_url)
  tmpdir=$(mktemp -d)
  archive="$tmpdir/$ECC_ASSET_NAME"
  msg "下载 $url"
  if ! fetch "$url" "$archive"; then
    # /releases/latest 不含 prerelease 时会 404，回退到 GitHub API 找同名资产
    warn "直链下载失败，尝试通过 GitHub API 定位资产…"
    local owner_repo alt
    owner_repo="${ECC_RELEASE_BASE#*://github.com/}"
    owner_repo="${owner_repo%/releases}"
    alt=$(fetch_stdout "https://api.github.com/repos/${owner_repo}/releases?per_page=20" 2>/dev/null \
          | grep -oE "https://[^\"]*/download/[^\"]*/${ECC_ASSET_NAME}" | head -1) || true
    [[ -n "$alt" ]] || die "下载失败。可 export ECC_CLI_URL=<完整直链> 后重试"
    url="$alt"
    fetch "$url" "$archive" || die "下载失败: $url"
  fi
  (( FORCE )) && rm -rf "$ECC_INSTALL_DIR"
  mkdir -p "$ECC_INSTALL_DIR"
  tar -xzf "$archive" -C "$ECC_INSTALL_DIR"
  rm -rf "$tmpdir"
  ecc_installed || die "解压后未找到 $ECC_INSTALL_DIR/ecc（资产布局可能变化，请检查 $ECC_ASSET_NAME）"
  ok "安装完成：$("$ECC_INSTALL_DIR/ecc" --version 2>/dev/null || echo unknown)"
}

# ----------------------------- 2. PATH / 环境变量 -----------------------------
step_setup_env() {
  msg "环境变量与 PATH（写入 $ECC_ENV_FILE）"
  local bin_dir=""
  [[ -x "$ECC_OSS_CAD_DIR/bin/yosys" ]] && bin_dir="$ECC_OSS_CAD_DIR/bin"

  {
    echo "# ecc CLI environment — generated by ecc-cli-setup.sh"
    echo "export PATH=\"$ECC_INSTALL_DIR${bin_dir:+:$bin_dir}:\$PATH\""
    echo "export CHIPCOMPILER_ICS55_PDK_ROOT=\"$ECC_PDK_DIR\""
    if [[ -n "$bin_dir" ]]; then
      echo "export CHIPCOMPILER_OSS_CAD_DIR=\"$ECC_OSS_CAD_DIR\""
    fi
  } > "$ECC_ENV_FILE"
  ok "已写入 $ECC_ENV_FILE"

  # 便利软链接：~/.local/bin 在多数发行版默认位于 PATH
  if [[ -d "$HOME/.local/bin" ]] || [[ ":$PATH:" == *":$HOME/.local/bin:"* ]]; then
    mkdir -p "$HOME/.local/bin"
    ln -sf "$ECC_INSTALL_DIR/ecc" "$HOME/.local/bin/ecc"
    ok "软链接 ~/.local/bin/ecc → $ECC_INSTALL_DIR/ecc"
  fi

  if (( EDIT_SHELL_RC )); then
    local rc="$HOME/.bashrc"
    [[ "${SHELL:-}" == */zsh ]] && rc="$HOME/.zshrc"
    if [[ -f "$rc" ]] && ! grep -qF "$ECC_ENV_FILE" "$rc"; then
      printf '\n# Added by ecc-cli-setup.sh\n[ -f %q ] && . %q\n' "$ECC_ENV_FILE" "$ECC_ENV_FILE" >> "$rc"
      ok "已向 $rc 追加加载 $ECC_ENV_FILE（幂等，不会重复添加）"
    else
      ok "$rc 已配置或不存在，跳过（可用 --no-shell-rc 禁用本行为）"
    fi
  fi
  ok "当前 shell 立即生效：source $ECC_ENV_FILE"
}

# ----------------------------- 3. PDK -----------------------------
step_pdk() {
  msg "ICS55 PDK（$ECC_PDK_DIR）"
  if pdk_ready "$ECC_PDK_DIR"; then
    ok "PDK 完整（tech LEF / LEF / liberty 均在）"
    return 0
  fi
  if [[ ! -d "$ECC_PDK_DIR/.git" ]]; then
    msg "clone $ECC_PDK_URL（--depth 1）"
    rm -rf "$ECC_PDK_DIR"
    if [[ -n "$GH_PROXY" ]]; then
      git clone --depth 1 "${GH_PROXY}${ECC_PDK_URL}" "$ECC_PDK_DIR"
    else
      git clone --depth 1 "$ECC_PDK_URL" "$ECC_PDK_DIR"
    fi
  else
    ok "仓库已存在，补齐数据文件"
  fi
  msg "下载 liberty/GDS 并解压（make unzip，来自 PDK 官方 Releases，自动重试 3 次）"
  local make_args=(unzip)
  [[ -n "$GH_PROXY" ]] && make_args+=(USE_PROXY=true "GH_PROXY=$GH_PROXY")
  local attempt rc=1
  for attempt in 1 2 3; do
    if (cd "$ECC_PDK_DIR" && make "${make_args[@]}"); then rc=0; break; fi
    warn "第 $attempt 次尝试失败，重试（已下载的压缩包会保留，断点续传）…"
  done
  (( rc )) && die "make unzip 连续失败，请检查网络（或 GH_PROXY 代理可用性）后重新运行本脚本"
  pdk_ready "$ECC_PDK_DIR" && ok "PDK 就绪" || die "make unzip 后仍缺少文件，请检查上方日志"
}

# ----------------------------- 4. Yosys / OSS CAD Suite -----------------------------
step_tools() {
  msg "Yosys（综合器，含 slang 前端）"
  local ybin=""
  if ybin=$(pick_yosys); then
    ok "找到 yosys：$ybin（$("$ybin" -V 2>/dev/null | head -1)）"
    if slang_ok "$ybin"; then
      ok "slang 前端可用"
      return 0
    fi
    warn "该 yosys 无 slang 前端 → 安装 OSS CAD Suite 最新版（ecc 优先使用 CHIPCOMPILER_OSS_CAD_DIR）"
  else
    warn "未找到 yosys → 安装 OSS CAD Suite 最新版"
  fi

  local url tmpdir
  url=$(resolve_oss_cad_url) \
    || die "无法解析 OSS CAD Suite 最新版直链（GitHub API 限流或网络受限）。可 export OSS_CAD_URL=<直链> 后重试"
  msg "下载 $url（约 700+ MB，耐心等待）"
  tmpdir=$(mktemp -d)
  fetch "$url" "$tmpdir/oss-cad-suite.tgz" || { rm -rf "$tmpdir"; die "下载失败: $url"; }
  msg "解压并安装到 $ECC_OSS_CAD_DIR"
  tar -xzf "$tmpdir/oss-cad-suite.tgz" -C "$tmpdir"
  rm -rf "$ECC_OSS_CAD_DIR"
  mv "$tmpdir"/oss-cad-suite "$ECC_OSS_CAD_DIR"
  rm -rf "$tmpdir"
  ybin="$ECC_OSS_CAD_DIR/bin/yosys"
  [[ -x "$ybin" ]] || die "解压后未找到 $ybin"
  ok "安装完成：$("$ybin" -V 2>/dev/null | head -1)"
  slang_ok "$ybin" && ok "slang 前端可用" || die "OSS CAD Suite 的 yosys 仍无 slang 前端，请反馈给 ECC 维护者"
}

# ----------------------------- 5. 汇总自检 -----------------------------
step_verify() {
  msg "汇总自检"
  local pass=1

  if ecc_installed; then
    ok "ecc CLI   : $ECC_INSTALL_DIR/ecc ($("$ECC_INSTALL_DIR/ecc" --version 2>/dev/null || echo unknown))"
  else
    fail "ecc CLI   : 未安装"; pass=0
  fi

  if pdk_ready "$ECC_PDK_DIR"; then
    ok "PDK ics55 : $ECC_PDK_DIR（liberty/LEF/techLEF 齐备）"
  else
    fail "PDK ics55 : $ECC_PDK_DIR 不完整（缺 liberty 或 LEF）"; pass=0
  fi

  local ybin
  if ybin=$(pick_yosys); then
    if slang_ok "$ybin"; then
      ok "yosys     : $ybin（slang 前端可用）"
    else
      fail "yosys     : $ybin 无 slang 前端"; pass=0
    fi
  else
    fail "yosys     : 未找到"; pass=0
  fi

  # 组件级体检交给 CLI 内置的 doctor（官方旧版无此命令则跳过）
  if ecc_installed && "$ECC_INSTALL_DIR/ecc" doctor --help >/dev/null 2>&1; then
    if "$ECC_INSTALL_DIR/ecc" doctor >/dev/null 2>&1; then
      ok "ecc doctor: 组件体检通过（含捆绑组件）"
    else
      warn "ecc doctor: 存在必需组件未就绪，详查: $ECC_INSTALL_DIR/ecc doctor"
    fi
  fi

  echo
  if (( pass )); then
    msg "全部就绪。快速上手："
    cat <<EOF
      source "$ECC_ENV_FILE"          # 当前 shell 生效（新终端自动生效）
      ecc init gcd && cd gcd          # 建项目（ecc.toml 默认已用 CHIPCOMPILER_ICS55_PDK_ROOT）
      ecc check && ecc run            # 校验并运行 RTL-to-GDS
      ecc status && ecc log           # 查看进度与日志
EOF
  else
    warn "存在未就绪项（见上）。修复后重新运行本脚本即可增量补齐。"
    exit 1
  fi
}

# ----------------------------- 主流程 -----------------------------
main() {
  msg "ECC CLI 一键安装脚本（ecc=$ECC_VERSION, PDK=$ECC_PDK_URL）"
  step_preflight
  if (( CHECK_ONLY )); then
    step_verify
    return 0
  fi
  step_install_ecc
  (( SKIP_TOOLS )) || step_tools
  (( SKIP_PDK ))    || step_pdk
  step_setup_env
  step_verify
}

main "$@"
