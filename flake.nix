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
    # nix-eda's packaging needs its own (much newer) nixpkgs — do NOT make
    # it follow the root pin (onetbb and the newer fmt only exist there).
    nix-eda.url = "github:fossi-foundation/nix-eda/93b4808044ee1d92eb088f02e90bc9ae0b2bcf46";
  };
  outputs = inputs@{
    self, nixpkgs, flake-parts, ecc-dreamplace, ecc-tools, infra, nix-eda,
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

      # Pinned nixpkgs ships uv-build 0.8.14, which falls outside the
      # dependabot-managed version window in RosettaKit's pyproject.toml.
      # rosettakit is pure Python, so any uv-build works.
      postPatch = ''
        substituteInPlace pyproject.toml \
          --replace-fail 'uv-build>=0.10.0,<0.11.24' 'uv-build'
      '';

      build-system = with python3Packages; [ uv-build ];

      pythonImportsCheck = [ "rosettakit" ];
    };

    # kepler-formal, the GPL-3.0-only LEC engine for the lec/postRouteLec
    # steps: nix-eda's packaging with src pointed at the Emin017 fork.
    # Built from source for local development only: ECOS ships Apache-2.0
    # and does not redistribute kepler-formal binaries, so the derivation
    # stays on the developer's machine (no distribution, no GPL conveyance
    # obligations). The ECC runtime resolves it through
    # CHIPCOMPILER_KEPLER_FORMAL_ROOT. First build takes a while (naja and
    # its submodules compile in the nix sandbox).
    keplerFormal = {
      fetchgit,
      lib,
      nix-eda,
      system,
    }: nix-eda.packages.${system}.kepler-formal.overrideAttrs (old: {
      version = "0-unstable-2026-09-22";
      src = fetchgit {
        url = "https://github.com/Emin017/kepler-formal";
        rev = "c2e6a070bb32a4035d3e672776695403cd9781b0";
        hash = "sha256-mcUeZVaklQv/E0tkxCjh4Sb8jazu6pA+ovqhz0r2mOE=";
        fetchSubmodules = true;
      };
      meta = old.meta // {
        description = "Equivalence checking engine (GPL-3.0-only, local dev build)";
        homepage = "https://github.com/Emin017/kepler-formal";
        license = lib.licenses.gpl3Only;
      };
    });

    # Not in the pinned nixpkgs; required by chipcompiler's runtime server.
    # Use the wheel: the sdist's bundled versioneer is incompatible with
    # Python 3.13 (configparser.SafeConfigParser was removed).
    oslash = {
      fetchPypi,
      python3Packages,
    }: python3Packages.buildPythonPackage rec {
      pname = "OSlash";
      version = "0.6.3";
      format = "wheel";

      src = fetchPypi {
        inherit pname version format;
        dist = "py3";
        python = "py3";
        hash = "sha256-ibl4RDt9s6wmZhBr3DaArdPIhqbY/N0C/QYq+G0pSU8=";
      };

      dependencies = [ python3Packages.typing-extensions ];

      pythonImportsCheck = [ "oslash" ];
    };

    jsonrpcserver = {
      fetchPypi,
      oslash,
      python3Packages,
    }: python3Packages.buildPythonPackage rec {
      pname = "jsonrpcserver";
      version = "5.0.9";
      pyproject = true;

      src = fetchPypi {
        inherit pname version;
        hash = "sha256-px+yz6GFQcgJNfYJh/knVdlNdBQSSMdDiEe5bu5cRII=";
      };

      build-system = with python3Packages; [ setuptools ];

      dependencies = [ python3Packages.jsonschema oslash ];

      pythonImportsCheck = [ "jsonrpcserver" ];
    };

    chipcompiler = {
      ecc-dreamplace,
      ecc-tools,
      jsonrpcserver,
      keplerFormal,
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
        jsonrpcserver
        klayout
        matplotlib
        numpy
        pandas
        pydantic
        pyjson5
        pyyaml
        pyarrow
        rosettakit
        scipy
        torch
        tomli-w
        tqdm
        typer
        uvicorn
        pip
      ];

      nativeBuildInputs = [ makeWrapper ];

      postFixup = ''
        wrapProgram "$out/bin/ecc" \
          --set CHIPCOMPILER_OSS_CAD_DIR "${yosysWithSlang}" \
          --set CHIPCOMPILER_KEPLER_FORMAL_ROOT "${keplerFormal}" \
          --prefix PATH : "${yosysWithSlang}/bin"
      '';

      pythonImportsCheck = [
        "chipcompiler"
        "chipcompiler.engine"
        "chipcompiler.tools"
        "chipcompiler.cli"
      ];

      meta.mainProgram = "ecc";
    };
  in flake-parts.lib.mkFlake { inherit inputs; } {
    systems = [ "x86_64-linux" ];
    perSystem = { self', pkgs, system, ... }: {
      packages.keplerFormal = pkgs.callPackage keplerFormal {
        inherit nix-eda system;
      };
      packages.default = pkgs.callPackage chipcompiler {
        ecc-dreamplace = ecc-dreamplace.packages.${system}.default;
        ecc-tools = ecc-tools.packages.${system}.default;
        jsonrpcserver = pkgs.callPackage jsonrpcserver { oslash = pkgs.callPackage oslash {}; };
        keplerFormal = self'.packages.keplerFormal;
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
        CHIPCOMPILER_KEPLER_FORMAL_ROOT = "${self'.packages.keplerFormal}";
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
