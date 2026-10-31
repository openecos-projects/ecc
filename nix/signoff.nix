# flake-parts perSystem module: signoff lit packages/apps.
# Imported from flake.nix perSystem imports; no perSystem wrapper here.
# lit from nixpkgs; FileCheck from llvmPackages_21.libllvm (not PyPI).

{ pkgs, ... }:

let
  inherit (pkgs) lit jq python3 writeShellApplication symlinkJoin;

  filecheck = pkgs.llvmPackages_21.libllvm;

  exportCsvSh = ./scripts/export-signoff-csv.sh;
  signoffLitSh = ./scripts/signoff-lit.sh;

  signoff-lit = writeShellApplication {
    name = "signoff-lit";
    runtimeInputs = [
      lit
      filecheck
      jq
    ];
    text = ''
      root="''${ECC_REPO_ROOT:-$PWD}"
      export ECC_REPO_ROOT="$root"
      export ECC_EXPORT_SIGNOFF_CSV="''${ECC_EXPORT_SIGNOFF_CSV:-${exportCsvSh}}"
      export FILECHECK="''${FILECHECK:-FileCheck}"
      export LIT="''${LIT:-lit}"
      if [ -x "$root/.venv/bin/python" ]; then
        export PYTHON="$root/.venv/bin/python"
      fi
      exec bash ${signoffLitSh} "$@"
    '';
  };

  signoff-csv = writeShellApplication {
    name = "signoff-csv";
    runtimeInputs = [
      python3
    ];
    text = ''
      root="''${ECC_REPO_ROOT:-$PWD}"
      export ECC_REPO_ROOT="$root"
      export PYTHONPATH="$root/nix/scripts''${PYTHONPATH:+:$PYTHONPATH}"
      exec python3 -m signoff_csv.cli "$@"
    '';
  };

  signoff-tools = symlinkJoin {
    name = "ecc-signoff-tools";
    paths = [
      lit
      filecheck
      signoff-lit
      signoff-csv
      jq
    ];
    meta.description = "lit + FileCheck (llvmPackages_21); run via signoff-lit";
  };
in
{
  packages = {
    inherit filecheck lit signoff-csv signoff-lit signoff-tools;
  };

  apps.signoff-lit = {
    type = "app";
    program = "${signoff-lit}/bin/signoff-lit";
  };

  apps.signoff-csv = {
    type = "app";
    program = "${signoff-csv}/bin/signoff-csv";
  };
}
