{
  lib,
  python3,
  python3Packages,
  ecc-tools,
  makeWrapper,
}:

python3Packages.buildPythonPackage {
  pname = "chipcompiler";
  version = "0.1.0";
  pyproject = true;

  src = with lib.fileset;
  toSource {
    root = ./..;
    fileset = unions [
      ./../README.md
      ./../uv.lock
      ./../pyproject.toml
      ./../chipcompiler
    ];
  };

  postPatch = ''
    mkdir -p thirdparty/ecc-tools/bin
    install -m 755 ${ecc-tools}/bin/*.cpython-*.so thirdparty/ecc-tools/bin/
    install -m 755 ${ecc-tools}/bin/*.cpython-*.so chipcompiler/tools/ecc/bin/
  '';

  build-system = with python3Packages; [ uv-build ];

  dependencies = with python3Packages; [
    fastapi
    klayout
    matplotlib
    numpy
    pandas
    pydantic
    pyjson5
    pyyaml
    scipy
    tqdm
    uvicorn
  ];

  nativeBuildInputs = [ makeWrapper ];

  # Copy ecc_py.so to the correct location
  postInstall = ''
    # mkdir -p $out/${python3.sitePackages}/chipcompiler/tools/ecc/bin
    # cp ${ecc-tools}/bin/ecc_py*.so $out/${python3.sitePackages}/chipcompiler/tools/ecc/bin/
  '';

  # Skip tests for now (they require full environment setup)
  doCheck = false;

  pythonImportsCheck = [
    "chipcompiler"
    "chipcompiler.server"
    "chipcompiler.engine"
    "chipcompiler.tools"
  ];

  meta = {
    description = "ECOS chip design automation solution for RTL-to-GDS synthesis";
    homepage = "https://github.com/openecos-projects/ecc";
    license = lib.licenses.mulan-psl2;
    platforms = lib.platforms.linux;
    maintainers = [ ];
    mainProgram = "chipcompiler";
  };
}
