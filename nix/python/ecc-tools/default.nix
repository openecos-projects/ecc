{
  lib,
  stdenv,
  buildPythonPackage,
  fetchFromGitHub,
  callPackages,
  cmake,
  ninja,
  flex,
  bison,
  python,
  patchelf,
  pkg-config,
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
  curl,
  onnxruntime,
  tbb_2022,
  uv-build,
}:

let
  version = "0.1.0-alpha.2";

  rootSrc = fetchFromGitHub {
    owner = "openecos-projects";
    repo = "ecc-tools";
    rev = "36160db0b30ccd627f2c2a06d9fa517d4cce4d49";
    hash = "sha256-/09acQVPB9l4EyWtKy3DGkIFsjsJkao2PW3VS2gmLLI=";
  };

  patchedSrc = stdenv.mkDerivation {
    pname = "ecc-tools-src";
    inherit version;
    src = rootSrc;

    patches = [
      ./use-nix-built-rust-libraries.patch
      ./fix-ino-output-summary-init.patch
    ];

    postPatch = ''
      substituteInPlace src/operation/iIR/source/iir-rust/CMakeLists.txt \
        --replace-fail 'ADD_EXTERNAL_PROJ(iir)' "" \
        --replace-fail 'target_link_libraries(iIR-Rust PRIVATE ''${RUST_LIB_PATH} dl)' 'target_link_libraries(iIR-Rust PRIVATE iir dl)'

      substituteInPlace src/operation/iSTA/CMakeLists.txt \
        --replace-fail 'link_directories(''${HOME_THIRDPARTY}/onnxruntime/)' 'link_libraries(${onnxruntime}/lib/libonnxruntime.so)'
    '';

    dontBuild = true;
    dontFixup = true;

    installPhase = ''
      runHook preInstall
      cp -r . "$out"
      runHook postInstall
    '';
  };

  rustpkgs = callPackages ./rustpkgs.nix { rootSrc = patchedSrc; };

  nativeInputs = [
    cmake
    ninja
    flex
    bison
    python
    patchelf
    pkg-config
  ];

  runtimeInputs = [
    rustpkgs.iir-rust
    rustpkgs.sdf_parse
    rustpkgs.spef-parser
    rustpkgs.vcd_parser
    rustpkgs.verilog-parser
    rustpkgs.liberty-parser
    stdenv.cc.cc.lib
    zlib
    tcl
    boost
    eigen
    yaml-cpp
    libunwind
    glog
    gtest
    gflags
    metis
    gmp
    curl
    onnxruntime
    tbb_2022
  ];

  runtime = stdenv.mkDerivation {
    pname = "ecc-tools-runtime";
    inherit version;
    src = patchedSrc;

    nativeBuildInputs = nativeInputs;
    buildInputs = runtimeInputs;
    cmakeGenerator = "Ninja";

    cmakeFlags = [
      (lib.cmakeBool "BUILD_ECOS" true)
      (lib.cmakeBool "BUILD_PYTHON" true)
      (lib.cmakeBool "BUILD_STATIC_LIB" false)
      (lib.cmakeBool "COMPATIBILITY_MODE" true)
      (lib.cmakeFeature "Python3_EXECUTABLE" python.interpreter)
      (lib.cmakeFeature "Python3_ROOT_DIR" "${python}")
    ];

    buildPhase = ''
      runHook preBuild
      cmake --build . --target ecc_py
      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall

      install -d "$out/ecc_tools_bin"
      for dir in . ../bin; do
        if [ -d "$dir" ]; then
          find "$dir" -type f -name '*.so*' -exec cp -f {} "$out/ecc_tools_bin/" \;
        fi
      done

      ecc_py_so="$(find "$out/ecc_tools_bin" -type f -name 'ecc_py*.so' -print -quit)"
      if [ -z "$ecc_py_so" ]; then
        echo "ERROR: ecc_py extension was not built" >&2
        exit 1
      fi

      for so in "$out"/ecc_tools_bin/*.so*; do
        [ -e "$so" ] || continue
        patchelf --set-rpath "\$ORIGIN:${lib.makeLibraryPath runtimeInputs}" "$so" || true
      done

      runHook postInstall
    '';

    enableParallelBuild = true;
  };
in
buildPythonPackage {
  pname = "ecc-tools";
  inherit version;
  pyproject = true;

  src = patchedSrc;

  buildInputs = runtimeInputs;

  build-system = [ uv-build ];
  nativeBuildInputs = [ patchelf ];

  preBuild = ''
    install -d ecc_tools_bin
    cp -f ${runtime}/ecc_tools_bin/*.so* ecc_tools_bin/
  '';

  postInstall = ''
    site_packages="$out/${python.sitePackages}"
    install -d "$site_packages/ecc_tools_bin"
    cp -f ${patchedSrc}/ecc_tools_bin/__init__.py "$site_packages/ecc_tools_bin/"
    cp -f ${runtime}/ecc_tools_bin/*.so* "$site_packages/ecc_tools_bin/"
  '';

  postFixup = ''
    for so in "$out/${python.sitePackages}"/ecc_tools_bin/*.so*; do
      [ -e "$so" ] || continue
      patchelf --set-rpath "\$ORIGIN:${lib.makeLibraryPath runtimeInputs}" "$so"
    done
  '';

  doCheck = false;

  pythonImportsCheck = [ "ecc_tools_bin.ecc_py" ];

  meta = {
    description = "ECC tools Python wheel";
    homepage = "https://github.com/openecos-projects/ecc-tools";
    license = lib.licenses.mulan-psl2;
    platforms = [ "x86_64-linux" ];
  };
}
