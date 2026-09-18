# Flake-facing signoff CI surface. flake.nix imports this and merges outputs.
#
# Tool pins and script wrappers live in ./signoff-tools.nix; bump versions there.

{ pkgs }:

let
  tools = pkgs.callPackage ./signoff-tools.nix { };
in
{
  packages = {
    filecheck = tools.filecheck;
    lit = tools.lit;
    signoff-tools = tools.signoff-tools;
    ci-run-ics55-gcd = tools.ci-run-ics55-gcd;
    ci-export-signoff-csv = tools.ci-export-signoff-csv;
    ci-check-signoff-csv = tools.ci-check-signoff-csv;
  };

  apps = {
    ci-run-ics55-gcd = {
      type = "app";
      program = "${tools.ci-run-ics55-gcd}/bin/ci-run-ics55-gcd";
    };
    ci-export-signoff-csv = {
      type = "app";
      program = "${tools.ci-export-signoff-csv}/bin/ci-export-signoff-csv";
    };
    ci-check-signoff-csv = {
      type = "app";
      program = "${tools.ci-check-signoff-csv}/bin/ci-check-signoff-csv";
    };
    filecheck = {
      type = "app";
      program = "${tools.filecheck}/bin/filecheck";
    };
  };

  # Append to devShells.default.nativeBuildInputs
  nativeBuildInputs = [
    tools.signoff-tools
    tools.ci-run-ics55-gcd
    tools.ci-export-signoff-csv
    tools.ci-check-signoff-csv
  ];

  # Append to devShells.default.shellHook
  shellHook = ''
    export ECC_REPO_ROOT="$PWD"
  '';
}
