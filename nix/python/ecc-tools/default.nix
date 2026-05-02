{
  lib,
  buildPythonPackage,
  fetchurl,
}:

buildPythonPackage {
  pname = "ecc-tools";
  version = "0.1.0a2";
  format = "wheel";

  src = fetchurl {
    url = "https://github.com/openecos-projects/ecc-tools/releases/download/v0.1.0-alpha.2/ecc_tools-0.1.0a2-py3-none-manylinux_2_34_x86_64.whl";
    hash = "sha256-NgqtSHQiiN69mqZm5afk/13jCugxyUVCa0WAUKQHyL4=";
  };

  doCheck = false;

  pythonImportsCheck = [ "ecc_tools_bin" ];

  meta = {
    description = "ECC tools Python wheel";
    homepage = "https://github.com/openecos-projects/ecc-tools";
    license = lib.licenses.mulan-psl2;
    platforms = [ "x86_64-linux" ];
  };
}
