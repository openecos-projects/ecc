{
  lib,
  python3Packages,
  ecc-tools,
  yosysWithSlang,
  makeWrapper,
}:

python3Packages.buildPythonPackage {
  pname = "chipcompiler-cli";
  version = "0.1.0";
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

  postPatch = ''
    mkdir -p thirdparty/ecc-tools/bin
    install -m 755 ${ecc-tools}/bin/*.cpython-*.so thirdparty/ecc-tools/bin/
    install -m 755 ${ecc-tools}/bin/*.cpython-*.so chipcompiler/tools/ecc/bin/
  '';

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

    # This package should expose only the dedicated `cli` entrypoint.
    rm -f "$out/bin/chipcompiler"
  '';

  postFixup = ''
    wrapProgram "$out/bin/cli" \
      --set CHIPCOMPILER_OSS_CAD_DIR "${yosysWithSlang}" \
      --prefix PATH : "${yosysWithSlang}/bin"
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

  # Skip tests for now (they require full environment setup)
  doCheck = false;

  pythonImportsCheck = [
    "chipcompiler"
    "chipcompiler.server"
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
    mainProgram = "cli";
  };
}
