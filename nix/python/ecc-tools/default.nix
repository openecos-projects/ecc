{
  lib,
  stdenv,
  buildPythonPackage,
  fetchFromGitHub,
  rustPlatform,
  cargo,
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
  tbb_2022,
  uv-build,
  autoPatchelfHook,
}:

let
  version = "0.1.0-alpha.4";

  src = fetchFromGitHub {
    owner = "openecos-projects";
    repo = "ecc-tools";
    rev = "af793d33efe91c37f42bfe00eb737427de43715a";
    hash = "sha256-wD3mGge2vhGoXDIpanyRZGl1tTRmQJodDOmp8Lw2aC0=";
  };

  installDeps =
    lib.pipe
      {
        sdf_parser = "src/database/manager/parser/sdf/sdf_parse";
        vcd_parser = "src/database/manager/parser/vcd/vcd_parser";
        verilog-parser = "src/database/manager/parser/verilog/verilog-rust/verilog-parser";
      }
      [
        (lib.mapAttrsToList (
          name: path: ''
            mkdir -p ${path}/.cargo
            cat <<EOF > ${path}/.cargo/config.toml
            [source."crates-io"]
            "replace-with" = "vendored-sources"

            [source."vendored-sources"]
            "directory" = "${
              rustPlatform.importCargoLock {
                lockFile = "${src}/${path}/Cargo.lock";
                extraRegistries = {
                  # See: https://github.com/NixOS/nixpkgs/pull/524985
                  "https://github.com/rust-lang/crates.io-index" = "https://static.crates.io/crates";
                };
              }
            }"
            EOF
          ''
        ))
        (lib.concatStringsSep "\n")
      ];

  runtime = stdenv.mkDerivation {
    pname = "ecc-tools-runtime";
    inherit version src;

    nativeBuildInputs = [
      cmake
      ninja
      flex
      bison
      python
      patchelf
      pkg-config
      cargo
      autoPatchelfHook
    ];

    buildInputs = [
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
      tbb_2022
    ];

    cmakeFlags = [
      (lib.cmakeBool "BUILD_ECOS" true)
      (lib.cmakeBool "BUILD_PYTHON" true)
      (lib.cmakeBool "BUILD_STATIC_LIB" false)
      (lib.cmakeBool "COMPATIBILITY_MODE" true)
      (lib.cmakeFeature "Python3_EXECUTABLE" python.interpreter)
      (lib.cmakeFeature "Python3_ROOT_DIR" "${python}")
      "-GNinja"
    ];

    postPatch = installDeps;

    buildPhase = ''
      runHook preBuild
      cmake --build . --target ecc_py
      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall

      pushd ..
      mkdir -p $out/ecc_tools_bin
      find . -type f -executable -name '*.so*' -exec cp -f {} "$out/ecc_tools_bin/" \;

      for so in "$out"/ecc_tools_bin/*; do
        patchelf --set-rpath "" "$so" || true
      done
      popd

      runHook postInstall
    '';

    enableParallelBuilding = false;
  };
in
buildPythonPackage {
  pname = "ecc-tools";
  inherit version src;
  pyproject = true;

  build-system = [ uv-build ];

  postInstall = ''
    site_packages="$out/${python.sitePackages}"
    mkdir -p "$site_packages/ecc_tools_bin"
    cp -f ${src}/ecc_tools_bin/__init__.py "$site_packages/ecc_tools_bin/"
    ln -s ${runtime}/ecc_tools_bin/ecc_py.*.so "$site_packages/ecc_tools_bin/"
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
