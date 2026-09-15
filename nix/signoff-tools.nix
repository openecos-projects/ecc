# Signoff CI helpers: lit / filecheck version pins + script wrappers.
#
# Bump `filecheckVersion` / `litVersion` here when upgrading. Prefer this over
# pyproject.dev-dependencies so Nix, local shells, and CI share one pin.

{
  lib,
  python3Packages,
  writeShellApplication,
  symlinkJoin,
}:

let
  filecheckVersion = "1.0.6";
  filecheck = python3Packages.buildPythonPackage rec {
    pname = "filecheck";
    version = filecheckVersion;
    pyproject = true;

    src = python3Packages.fetchPypi {
      inherit pname version;
      hash = "sha256-xBxR9zOwv9rmcY3KS5T7C99y+rcPNfxo1iv4rGDWRC0=";
    };

    build-system = [ python3Packages.poetry-core ];

    pythonImportsCheck = [ "filecheck" ];

    meta = {
      description = "Python-native clone of LLVM FileCheck";
      mainProgram = "filecheck";
      homepage = "https://github.com/AntonLydike/filecheck";
      license = lib.licenses.asl20;
    };
  };

  litVersion = "18.1.8";
  lit = python3Packages.buildPythonPackage rec {
    pname = "lit";
    version = litVersion;
    pyproject = true;

    src = python3Packages.fetchPypi {
      inherit pname version;
      hash = "sha256-R8F0oYaUGugw8E3tdqNERgC+Z9Xl+4KCw3g/umccTts=";
    };

    build-system = [ python3Packages.setuptools ];
    doCheck = false;

    meta = {
      description = "LLVM Integrated Tester";
      mainProgram = "lit";
      homepage = "https://llvm.org/docs/CommandGuide/lit.html";
      license = lib.licenses.ncsa;
    };
  };

  ciRunScript = ../.github/scripts/ci_run_ics55_gcd.py;
  ciExportScript = ../.github/scripts/ci_export_signoff_csv.py;

  ci-run-ics55-gcd = writeShellApplication {
    name = "ci-run-ics55-gcd";
    runtimeInputs = [ python3Packages.python ];
    text = ''
      exec ${python3Packages.python.interpreter} ${ciRunScript} "$@"
    '';
  };

  # Resolve chipcompiler from the caller's checkout (.venv after uv sync).
  # Override with ECC_REPO_ROOT when not invoked from the repo root.
  ci-export-signoff-csv = writeShellApplication {
    name = "ci-export-signoff-csv";
    runtimeInputs = [ python3Packages.python ];
    text = ''
      root="''${ECC_REPO_ROOT:-$PWD}"
      if [ -x "$root/.venv/bin/python" ]; then
        py="$root/.venv/bin/python"
      else
        py="${python3Packages.python.interpreter}"
      fi
      export PYTHONPATH="$root/test''${PYTHONPATH:+:$PYTHONPATH}"
      exec "$py" ${ciExportScript} "$@"
    '';
  };

  signoff-tools = symlinkJoin {
    name = "ecc-signoff-tools";
    paths = [
      filecheck
      lit
    ];
    meta.description = "Pinned lit ${litVersion} + filecheck ${filecheckVersion} for ECC signoff CI";
  };
in
{
  inherit
    filecheck
    filecheckVersion
    lit
    litVersion
    ci-run-ics55-gcd
    ci-export-signoff-csv
    signoff-tools
    ;
}
