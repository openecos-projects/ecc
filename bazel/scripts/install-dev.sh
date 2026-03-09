#!/usr/bin/env bash
# Install Bazel-built deps into workspace. Called by bazel run //bazel/scripts:install_dev.
set -euo pipefail

WS="${BUILD_WORKSPACE_DIRECTORY:?Must run via: bazel run //bazel/scripts:install_dev}"
RF="${RUNFILES_DIR:-${BASH_SOURCE[0]}.runfiles}"

ecc_bundle="$RF/$1"

tar -xf "$ecc_bundle" -C "$WS" --keep-directory-symlink --no-same-owner
echo "Installed ECC runtime -> chipcompiler/tools/ecc/bin/"
