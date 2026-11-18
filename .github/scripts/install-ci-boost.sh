#!/usr/bin/env bash
# Match ecc-tools' pinned, headers-only Boost installation for native builds.
set -euo pipefail

boost_prefix="$1"
boost_version="1.91.0"
boost_archive="boost_1_91_0.tar.bz2"
boost_sha256="de5e6b0e4913395c6bdfa90537febd9028ea4c0735d2cdb0cd9b45d5f51264f5"
boost_build_dir="$(mktemp -d)"

cd "$boost_build_dir"
curl --fail --location --retry 3 --output "$boost_archive" \
  "https://archives.boost.io/release/${boost_version}/source/${boost_archive}"
echo "${boost_sha256}  ${boost_archive}" | sha256sum --check --strict
tar -xf "$boost_archive"
cd boost_1_91_0
./bootstrap.sh --prefix="$boost_prefix"
./b2 -j"$(nproc)" --with-headers install
