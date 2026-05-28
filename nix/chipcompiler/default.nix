{
  lib,
  python3Packages,
  ecc-dreamplace-python,
  ecc-tools-python,
  makeWrapper,
}:

python3Packages.buildPythonPackage {
  pname = "chipcompiler";
  version = "0.1.0-alpha.3";
  pyproject = true;

  src =
    with lib.fileset;
    toSource {
      root = ./../..;
      fileset = unions [
        ./../../README.md
        ./../../uv.lock
        ./../../pyproject.toml
        ./../../chipcompiler
      ];
    };

  postInstall = ''
    site_packages="$out/${python3Packages.python.sitePackages}"

    for rel in \
      chipcompiler/tools/ecc/configs \
      chipcompiler/tools/yosys/configs \
      chipcompiler/tools/yosys/scripts
    do
      if [ -d "$rel" ]; then
        install -d "$site_packages/$rel"
        cp -r "$rel"/. "$site_packages/$rel/"
      fi
    done
  '';

  build-system = with python3Packages; [ uv-build ];

  dependencies = [
    ecc-dreamplace-python
    ecc-tools-python
  ]
  ++ (with python3Packages; [
    fastapi
    klayout
    matplotlib
    numpy
    pandas
    pydantic
    pyjson5
    pyyaml
    scipy
    torch
    tqdm
    typer
    uvicorn
    pip
  ]);

  nativeBuildInputs = [ makeWrapper ];

  # Skip tests for now (they require full environment setup)
  doCheck = false;

  env.MPLCONFIGDIR = ".";

  pythonImportsCheck = [
    "chipcompiler"
    "chipcompiler.cli"
    "chipcompiler.engine"
    "chipcompiler.rtl2gds"
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
