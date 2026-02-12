{
  nixConfig = {
    extra-trusted-substituters = [
      "https://serve.eminrepo.cc/"
    ];
    extra-trusted-public-keys = [ "serve.eminrepo.cc:fgdTGDMn75Z0NOvTmus/Z9Fyh6ExgoqddNVkaYVi5qk=" ];
  };

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    parts.url = "github:hercules-ci/flake-parts";
    treefmt-nix.url = "github:numtide/treefmt-nix";
    treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
    infra.url = "github:Emin017/ieda-infra";
  };

  outputs =
    inputs@{
      nixpkgs,
      parts,
      treefmt-nix,
      infra,
      ...
    }:
    let
      overlay = import ./nix/overlay.nix;
      infraOverlay = inputs.infra.overlays.default;
    in
    parts.lib.mkFlake { inherit inputs; } {
      imports = [
        treefmt-nix.flakeModule
      ];
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      flake.overlays.default = overlay;
      perSystem =
        {
          inputs',
          self',
          config,
          pkgs,
          system,
          ...
        }:
        {
          imports = [
            ./nix
          ];
          _module.args.pkgs = import inputs.nixpkgs {
            inherit system;
            overlays = [
              overlay
              infraOverlay
            ];
          };
          packages = {
            inherit (pkgs)
              ecc-tools
              chipcompiler
              ecos-studio
              ;
          };
        };
    };
}
