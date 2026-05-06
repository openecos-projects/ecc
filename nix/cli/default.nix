{
  lib,
  python3Packages,
  ecc-dreamplace-python,
  ecc-tools-python,
  yosysWithSlang,
  makeWrapper,
}:

python3Packages.buildPythonPackage {
  pname = "chipcompiler-cli";
  version = "0.1.0.0-alpha.2";
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

    # This package should expose only the dedicated `ecc` entrypoint.
    rm -f "$out/bin/chipcompiler"
  '';

  postFixup = ''
    wrapProgram "$out/bin/ecc" \
      --set CHIPCOMPILER_OSS_CAD_DIR "${yosysWithSlang}" \
      --prefix PATH : "${yosysWithSlang}/bin"
    if [ -e "$out/bin/cli" ]; then
      wrapProgram "$out/bin/cli" \
        --set CHIPCOMPILER_OSS_CAD_DIR "${yosysWithSlang}" \
        --prefix PATH : "${yosysWithSlang}/bin"
    fi
  '';

  build-system = with python3Packages; [ uv-build ];

  dependencies = [
    ecc-dreamplace-python
    ecc-tools-python
  ] ++ (with python3Packages; [
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
    uvicorn
    pip
  ]);

  nativeBuildInputs = [ makeWrapper ];

  # Skip tests for now (they require full environment setup)
  doCheck = false;

  pythonImportsCheck = [
    "chipcompiler"
    "chipcompiler.engine"
    "chipcompiler.tools"
    "chipcompiler.cli"
  ];

  meta = {
    description = "CLI interface for ECOS chip design automation solution";
    homepage = "https://github.com/openecos-projects/ecc";
    license = lib.licenses.mulan-psl2;
    platforms = lib.platforms.linux;
    maintainers = [ ];
    mainProgram = "ecc";
  };
}
