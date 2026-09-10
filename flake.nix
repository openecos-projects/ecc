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

    # slang (naja's SystemVerilog frontend) requires fmt 12.2 through
    # FetchContent with a find_package fallback; the pinned nixpkgs fmt is
    # older, and the nix sandbox has no network, so hand FetchContent an
    # offline source tree instead of letting it clone at configure time.
    fmtSource12 = { fetchFromGitHub }: fetchFromGitHub {
      owner = "fmtlib";
      repo = "fmt";
      rev = "12.2.0";
      hash = "sha256-Tc7PmNxUv7ajw6GaHPGEEtrD/fl6is7RB8TPestJa1o=";
    };

    # Same offline treatment for slang's header-only tomlplusplus (3.4).
    tomlplusplusSource = { fetchFromGitHub }: fetchFromGitHub {
      owner = "marzer";
      repo = "tomlplusplus";
      rev = "v3.4.0";
      hash = "sha256-h5tbO0Rv2tZezY58yUbyRVpsfRjY3i+5TPkkxr6La8M=";
    };

    # kepler-formal, the GPL-3.0-only LEC engine for the lec/postRouteLec
    # steps. Built from source for local development only: ECOS ships
    # Apache-2.0 and does not redistribute kepler-formal binaries, so the
    # derivation stays on the developer's machine (no distribution, no GPL
    # conveyance obligations). The ECC runtime resolves it through
    # CHIPCOMPILER_KEPLER_FORMAL_ROOT. First build takes a while (naja and
    # its submodules compile in the nix sandbox).
    keplerFormal = {
      autoPatchelfHook,
      boost,
      bison,
      capnproto,
      cmake,
      fetchgit,
      flex,
      fmt,
      fmtSource12,
      lib,
      ninja,
      pkg-config,
      python3,
      spdlog,
      stdenv,
      tomlplusplusSource,
      tbb_2022,
      zlib,
    }: stdenv.mkDerivation rec {
      pname = "kepler-formal";
      version = "1.0.0";

      src = fetchgit {
        url = "https://github.com/keplertech/kepler-formal";
        rev = "11d8ac4e44d69bcb4cc53ef8ccb60d99999cb975";
        hash = "sha256-LbGpW2bvRns4RAIRUk0zTQqM1TwVpJ++UiVIhaC0OHc=";
        fetchSubmodules = true;
      };

      # naja's CMake requires the oneTBB package config.
      buildInputs = [ boost capnproto fmt spdlog tbb_2022 zlib ];

      nativeBuildInputs = [
        autoPatchelfHook
        bison
        cmake
        flex
        ninja
        pkg-config
        # naja's CMake unconditionally find_package(Python3 ...) even with
        # the kepler Python interface disabled.
        python3
      ];

      cmakeFlags = [
        "-DCMAKE_BUILD_TYPE=Release"
        "-DPYTHON_INTERFACE=OFF"
        "-DENABLE_UNIT_TESTS=OFF"
        "-DFETCHCONTENT_SOURCE_DIR_FMT=${fmtSource12}"
        "-DFETCHCONTENT_SOURCE_DIR_TOMLPLUSPLUS=${tomlplusplusSource}"
        # slang defaults mimalloc on and would FetchContent it too; the
        # default allocator is fine for kepler-formal.
        "-DSLANG_USE_MIMALLOC=OFF"
        # No build-tree rpaths: autoPatchelf owns the final RUNPATH.
        "-DCMAKE_SKIP_BUILD_RPATH=ON"
      ];

      # Upstream installs only the kepler-formal executable; stage the
      # layout the ECC CLI expects under CHIPCOMPILER_KEPLER_FORMAL_ROOT
      # (bin/kepler-formal plus the bundled naja libraries in lib/).
      # Locate artifacts by search: the stdenv cmake hook decides where
      # the build tree lands.
      installPhase = ''
        runHook preInstall
        mkdir -p $out/bin $out/lib
        kepler_bin="$(find . -type f -name kepler-formal -perm -u+x | head -n1)"
        [ -n "$kepler_bin" ] || { echo "kepler-formal binary not found" >&2; exit 1; }
        install -Dm755 "$kepler_bin" $out/bin/kepler-formal
        install -Dm755 "$(dirname "$kepler_bin")/naja.so" $out/bin/naja.so
        find . -type f -name 'libnaja_*.so' -exec cp {} $out/lib/ \;
        # Drop the build-tree rpaths; autoPatchelf rewrites them to store
        # paths during fixup. naja.so carries an explicit BUILD_RPATH
        # (CMAKE_SKIP_BUILD_RPATH does not cover it), so replace it with the
        # installed layout instead of just removing it.
        patchelf --set-rpath '$ORIGIN/../lib' $out/bin/naja.so
        for elf in $out/bin/kepler-formal $out/lib/*.so*; do
          patchelf --remove-rpath "$elf" || true
        done
        runHook postInstall
      '';

      # Sanity check that the packaged binary starts.
      postInstallCheck = ''
        $out/bin/kepler-formal --help > /dev/null
      '';

      meta = {
        description = "Equivalence checking engine (GPL-3.0-only, local dev build)";
        homepage = "https://github.com/keplertech/kepler-formal";
        license = lib.licenses.gpl3Only;
      };
    };

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
        fmtSource12 = pkgs.callPackage fmtSource12 {};
        tomlplusplusSource = pkgs.callPackage tomlplusplusSource {};
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
