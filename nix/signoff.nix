# flake-parts perSystem module: signoff lit packages/apps.
# Imported from flake.nix perSystem imports; no perSystem wrapper here.

{ pkgs, ... }:

let
  tools = pkgs.callPackage ./signoff-tools.nix {
    inherit (pkgs) llvmPackages_23;
  };
in
{
  packages = {
    inherit (tools) filecheck lit signoff-tools signoff-lit;
  };

  apps.signoff-lit = {
    type = "app";
    program = "${tools.signoff-lit}/bin/signoff-lit";
  };
}
