# Signoff CI helpers: lit / filecheck version pins + script wrappers.
#
# Bump `filecheckVersion` / `litVersion` here when upgrading. Prefer this over
# pyproject.dev-dependencies so Nix, local shells, and CI share one pin.
#
# CSV export/check entrypoints are shell scripts under .github/scripts/:
#   export_signoff_csv.sh  — write csv/ + metrics.check.txt
#   check_signoff_csv.sh   — FileCheck the projection

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
  exportCsvSh = ../.github/scripts/export_signoff_csv.sh;
  checkCsvSh = ../.github/scripts/check_signoff_csv.sh;

  ci-run-ics55-gcd = writeShellApplication {
    name = "ci-run-ics55-gcd";
    runtimeInputs = [ python3Packages.python ];
    text = ''
      exec ${python3Packages.python.interpreter} ${ciRunScript} "$@"
    '';
  };

  # Shell entry: export CSV + projection. Needs checkout Python (.venv) + chipcompiler.
  ci-export-signoff-csv = writeShellApplication {
    name = "ci-export-signoff-csv";
    runtimeInputs = [ python3Packages.python ];
    text = ''
      root="''${ECC_REPO_ROOT:-$PWD}"
      export ECC_REPO_ROOT="$root"
      if [ -x "$root/.venv/bin/python" ]; then
        export PYTHON="$root/.venv/bin/python"
      else
        export PYTHON="${python3Packages.python.interpreter}"
      fi
      exec bash ${exportCsvSh} "$@"
    '';
  };

  # Shell entry: FileCheck consume/verify of metrics.check.txt.
  ci-check-signoff-csv = writeShellApplication {
    name = "ci-check-signoff-csv";
    runtimeInputs = [ filecheck ];
    text = ''
      export FILECHECK="''${FILECHECK:-filecheck}"
      exec bash ${checkCsvSh} "$@"
    '';
  };

  signoff-tools = symlinkJoin {
    name = "ecc-signoff-tools";
    paths = [
      filecheck
      lit
      ci-export-signoff-csv
      ci-check-signoff-csv
    ];
    meta.description = "Pinned lit ${litVersion} + filecheck ${filecheckVersion} + signoff CSV sh";
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
    ci-check-signoff-csv
    signoff-tools
    ;
}
