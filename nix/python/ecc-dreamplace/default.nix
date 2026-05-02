{
  lib,
  buildPythonPackage,
  fetchurl,
  cairocffi,
  distutils,
  matplotlib,
  numpy,
  patool,
  pkgconfig,
  scipy,
  setuptools,
  shapely,
  wheel,
}:

buildPythonPackage {
  pname = "ecc-dreamplace";
  version = "0.1.0a1";
  format = "wheel";

  src = fetchurl {
    url = "https://github.com/openecos-projects/ecc-dreamplace/releases/download/v0.1.0-alpha.1/ecc_dreamplace-0.1.0a1-py3-none-manylinux_2_34_x86_64.whl";
    hash = "sha256-ISE5xD+CVJiWjtoQMJlZuZzZOuwHRNGCoXu100tTFF4=";
  };

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
    "torch"
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
