{
  inputs = {
    self.submodules = true;
    nixpkgs.url = "github:NixOS/nixpkgs/f4b140d5b253f5e2a1ff4e5506edbf8267724bde";
    ecc-dreamplace = {
      url = "./chipcompiler/thirdparty/ecc-dreamplace";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    ecc-tools = {
      url = "./chipcompiler/thirdparty/ecc-tools";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    infra.url = "github:Emin017/ieda-infra";
  };
  outputs = inputs@{
    self, nixpkgs, flake-parts, ecc-dreamplace, ecc-tools, infra,
  }: let
    rosettakit = {
      fetchFromGitHub,
      python3Packages,
    }: python3Packages.buildPythonPackage {
      name = "rosettakit";
      format = "pyproject";

      src = fetchFromGitHub {
        owner = "Emin017";
        repo = "RosettaKit";
        rev = "5750390b80e84c05e9f30c58df44e2a153f4c39e";
        hash = "sha256-hyDKWsQnfPVuxxBNxjdGR6AsGa/1NkdflBmwiK3Eqz0=";
      };

      build-system = with python3Packages; [ uv-build ];

      pythonImportsCheck = [ "rosettakit" ];
    };

    chipcompiler = {
      ecc-dreamplace,
      ecc-tools,
      rosettakit,
      yosysWithSlang,
      lib,
      makeWrapper,
      python3Packages,
    }: python3Packages.buildPythonPackage {
      name = "chipcompiler";
      format = "pyproject";

      src = with lib.fileset; toSource {
        root = ./.;
        fileset = unions [
          ./README.md
          ./chipcompiler
          ./pyproject.toml
          ./uv.lock
        ];
      };

      build-system = with python3Packages; [ uv-build ];

      dependencies = with python3Packages; [
        ecc-dreamplace
        ecc-tools
        fastapi
        klayout
        matplotlib
        numpy
        pandas
        pydantic
        pyjson5
        pyyaml
        rosettakit
        scipy
        torch
        tqdm
        typer
        uvicorn
        pip
      ];

      nativeBuildInputs = [ makeWrapper ];

      postFixup = ''
        wrapProgram "$out/bin/ecc" \
          --set CHIPCOMPILER_OSS_CAD_DIR "${yosysWithSlang}" \
          --prefix PATH : "${yosysWithSlang}/bin"
      '';

      pythonImportsCheck = [
        "chipcompiler"
        "chipcompiler.engine"
        "chipcompiler.tools"
        "chipcompiler.cli"
      ];
    };
  in flake-parts.lib.mkFlake { inherit inputs; } {
    systems = [ "x86_64-linux" ];
    perSystem = { self', pkgs, system, ... }: {
      packages.default = pkgs.callPackage chipcompiler {
        ecc-dreamplace = ecc-dreamplace.packages.${system}.default;
        ecc-tools = ecc-tools.packages.${system}.default;
        rosettakit = pkgs.callPackage rosettakit {};
        yosysWithSlang = infra.packages.${system}.yosysWithSlang;
      };
      devShells.default = pkgs.mkShell.override {
        stdenv = pkgs.ccacheStdenv;
      } {
        NIX_LD = pkgs.lib.fileContents "${pkgs.stdenv.cc}/nix-support/dynamic-linker";
        NIX_LD_LIBRARY_PATH = "${pkgs.lib.makeLibraryPath (with pkgs; [
          stdenv.cc.cc.lib
          zlib
          expat
          cairo
        ])}";
        CHIPCOMPILER_OSS_CAD_DIR = "${infra.packages.${system}.yosysWithSlang}";
        # inputsFrom will add python3.13 to the environment. Using rawBuildInputs and rawNativeBuildInputs to avoid that.
        buildInputs = ecc-dreamplace.packages.${system}.default.rawBuildInputs ++
          ecc-tools.packages.${system}.default.rawBuildInputs;
        nativeBuildInputs = ecc-dreamplace.packages.${system}.default.rawNativeBuildInputs ++
          ecc-tools.packages.${system}.default.rawNativeBuildInputs ++ (with pkgs; [
            uv
          ]);
        shellHook = ''
          export CCACHE_DIR="$PWD/.ccache"
        '';
      };
    };
  };
}
