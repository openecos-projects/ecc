{
  lib,
  stdenv,
  buildPythonPackage,
  fetchFromGitHub,
  cmake,
  ninja,
  flex,
  bison,
  python,
  pkg-config,
  zlib,
  boost,
  cairo,
  cairocffi,
  distutils,
  matplotlib,
  numpy,
  patool,
  pkgconfig,
  scipy,
  setuptools,
  shapely,
  torch,
  uv-build,
  wheel,
}:

let
  version = "0.1.0-alpha.2";

  rootSrc = fetchFromGitHub {
    owner = "openecos-projects";
    repo = "ecc-dreamplace";
    rev = "b8606d35455b3a6aae7cd0a5584f4ea389cc223a";
    hash = "sha256-+eFHxOyt6BwUYZ5MN1DHGu35f7NoL6f4PiAATj9nDrc=";
    fetchSubmodules = true;
  };

  nativeInputs = [
    cmake
    ninja
    flex
    bison
    python
    pkg-config
  ];

  runtimeInputs = [
    zlib
    boost
    cairo
    torch
  ];

  runtime = stdenv.mkDerivation {
    pname = "ecc-dreamplace-runtime";
    inherit version;
    src = rootSrc;

    nativeBuildInputs = nativeInputs;
    buildInputs = runtimeInputs;

    cmakeFlags = [
      (lib.cmakeFeature "CMAKE_POLICY_VERSION_MINIMUM" "3.5")
      (lib.cmakeFeature "CMAKE_CXX_ABI" "1")
      (lib.cmakeFeature "PYTHON_EXECUTABLE" python.interpreter)
      (lib.cmakeFeature "Python_EXECUTABLE" python.interpreter)
      (lib.cmakeFeature "TORCH_INSTALL_PREFIX" "${torch}/${python.sitePackages}/torch")
      (lib.cmakeFeature "TORCH_ENABLE_CUDA" "0")
      (lib.cmakeFeature "TORCH_VERSION" torch.version)
    ];

    postPatch = ''
      sed -i 's/^[[:space:]]*CMAKE_POLICY(SET CMP0048 OLD)/CMAKE_POLICY(SET CMP0048 NEW)/' thirdparty/Limbo/limbo/thirdparty/lemon/CMakeLists.txt
      sed -i 's/static void  thread_hold();/static void thread_hold(int sig);/; s/static void thread_hold ()/static void thread_hold(int sig)/' thirdparty/Limbo/limbo/thirdparty/CThreadPool/thpool.c
      sed -i 's/i1\.center() < i2\.center()/(i1.low() + i1.high()) < (i2.low() + i2.high())/' dreamplace/ops/place_io/src/Interval.h
      sed -i '/import stat/d; /nctugr_bin = "%s\/NCTUgr"/,+2d' dreamplace/ops/nctugr_binary/nctugr_binary.py
    '';

    installPhase = ''
      runHook preInstall
      cmake --install . --prefix "$out"
      runHook postInstall
    '';

    enableParallelBuild = true;
  };
in
buildPythonPackage {
  pname = "ecc-dreamplace";
  inherit version;
  pyproject = true;

  src = rootSrc;

  build-system = [ uv-build ];

  buildInputs = runtimeInputs;

  postPatch = ''
    substituteInPlace pyproject.toml \
      --replace-fail 'uv_build>=0.10.9,<0.12' 'uv_build>=0.10.0,<0.12'
  '';

  preBuild = ''
    cp -r ${runtime}/dreamplace/. dreamplace/
    rm -rf thirdparty
    cp -r ${runtime}/thirdparty thirdparty
    chmod +x thirdparty/NCTUgr.ICCAD2012/NCTUgr
  '';

  postInstall = ''
    site_packages="$out/${python.sitePackages}"
    rm -rf "$site_packages/thirdparty"
    cp -r ${runtime}/thirdparty "$site_packages/thirdparty"
    chmod +x "$site_packages/thirdparty/NCTUgr.ICCAD2012/NCTUgr"
  '';

  dependencies = [
    cairocffi
    distutils
    matplotlib
    numpy
    patool
    pkgconfig
    scipy
    setuptools
    shapely
    torch
    wheel
  ];

  pythonRemoveDeps = [
    "configspace"
    "pydoe2"
    "pygmo"
    "pyro4"
    "pyunpack"
    "shap"
    "statsmodels"
    "xgboost"
  ];

  doCheck = false;

  pythonImportsCheck = [
    "dreamplace"
    "dreamplace.Params"
  ];

  meta = {
    description = "ECC DreamPlace Python wheel";
    homepage = "https://github.com/openecos-projects/ecc-dreamplace";
    license = lib.licenses.asl20;
    platforms = [ "x86_64-linux" ];
  };
}
