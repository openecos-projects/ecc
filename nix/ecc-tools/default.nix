{
  lib,
  fetchpatch,
  callPackages,
  stdenv,
  cmake,
  ninja,
  flex,
  bison,
  zlib,
  tcl,
  boost,
  eigen,
  yaml-cpp,
  libunwind,
  glog,
  gtest,
  gflags,
  metis,
  gmp,
  python3,
  onnxruntime,
  gperftools,
  pkg-config,
  curl,
  tbb_2022,
}:

let
  rootSrc = stdenv.mkDerivation {
    pname = "ecc-tools";
    version = "0-unstable-2026-01-23";
    src = fetchGit {
      url = "git@github.com:openecos-projects/ecc-tools.git";
      rev = "07b6d4133f848ba6e54c0889c3b777a2b544d06b";
    };

    patches = [
      # This patch is to fix the build system to properly find and link against rust libraries.
      # Due to the way they organized the source code, it's hard to upstream this patch.
      # So we have to maintain this patch locally.
      (fetchpatch {
        url = "https://github.com/Emin017/iEDA/commit/e5f3ce024965df5e1d400b6a1d7f8b5b307a4bf3.patch";
        hash = "sha256-YJnY+r9A887WT0a/H/Zf++r1PpD7t567NpkesDmIsD0=";
      })
      ./fix.patch
    ];

    dontBuild = true;
    dontFixup = true;
    installPhase = ''
      cp -r . $out
    '';

  };

  rustpkgs = callPackages ./rustpkgs.nix { inherit rootSrc; };
in
stdenv.mkDerivation {
  inherit (rootSrc) pname version;

  src = rootSrc;

  nativeBuildInputs = [
    cmake
    ninja
    flex
    bison
    python3
    tcl
    pkg-config
  ];

  cmakeBuildType = "Release";

  cmakeFlags = [
    (lib.cmakeBool "CMD_BUILD" true)
    (lib.cmakeBool "SANITIZER" false)
    (lib.cmakeBool "BUILD_STATIC_LIB" false)
    (lib.cmakeBool "USE_PROFILER" false)
    (lib.cmakeBool "BUILD_PYTHON" true)
    (lib.cmakeBool "BUILD_ECOS" true)
  ];

  # Only build the Python bindings target
  buildTargets = [ "ecc_py" ];

  preConfigure = ''
    cmakeFlags+=" -DCMAKE_RUNTIME_OUTPUT_DIRECTORY:FILEPATH=$out/bin -DCMAKE_LIBRARY_OUTPUT_DIRECTORY:FILEPATH=$out/lib"
  '';

  postPatch = ''
    sed -i '1i find_package(Boost REQUIRED)' src/operation/iPA/test/CMakeLists.txt
    sed -i 's/boost_system/Boost::headers/g' src/operation/iPA/test/CMakeLists.txt
  '';

  buildInputs = [
    rustpkgs.iir-rust
    rustpkgs.sdf-parse
    rustpkgs.spef-parser
    rustpkgs.vcd-parser
    rustpkgs.verilog-parser
    rustpkgs.liberty-parser
    gtest
    glog
    gflags
    boost
    onnxruntime
    eigen
    yaml-cpp
    libunwind
    metis
    gmp
    tcl
    zlib
    gperftools
    curl
    tbb_2022
  ];

  postInstall = ''
    # Tests rely on hardcoded path, so they should not be included
    rm $out/bin/*test $out/bin/*Test $out/bin/test_* $out/bin/*_app
  '';

  enableParallelBuild = true;

  meta = {
    description = "Open-source EDA for ASIC design";
    homepage = "https://github.com/openecos-projects/ecc-tools";
    license = lib.licenses.mulan-psl2;
    platforms = lib.platforms.linux;
  };
}
