#!/usr/bin/env bash
# Install Bazel-built deps into workspace. Called by bazel run //bazel/scripts:install_dev.
set -euo pipefail

WS="${BUILD_WORKSPACE_DIRECTORY:?Must run via: bazel run //bazel/scripts:install_dev}"
RF="${RUNFILES_DIR:-${BASH_SOURCE[0]}.runfiles}"

ecc_bundle="$RF/$1"

tar -xf "$ecc_bundle" -C "$WS" --keep-directory-symlink
echo "Installed ECC runtime -> chipcompiler/tools/ecc/bin/"

if [ -n "${2:-}" ]; then
    oss_cad_yosys="$RF/$2"
    oss_src="$(cd "$(dirname "$(dirname "$oss_cad_yosys")")" && pwd)"
    ln -sfnT "$oss_src" "$WS/chipcompiler/thirdparty/oss-cad-suite"
    echo "Linked OSS CAD Suite -> $oss_src"
fi

if [ -n "${3:-}" ]; then
    pdk_marker="$RF/$3"
    pdk_src="$(cd "$(dirname "$pdk_marker")" && pwd)"
    ln -sfnT "$pdk_src" "$WS/chipcompiler/thirdparty/icsprout55-pdk"
    echo "Linked icsprout55 PDK -> $pdk_src"
fi
