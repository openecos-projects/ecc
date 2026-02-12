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
      edaOverlay = inputs.infra.overlays.default;
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
          _module.args.pkgs = import inputs.nixpkgs {
            inherit system;
            overlays = [
              overlay
              edaOverlay
            ];
          };
          # Use `nix develop -c python3 test/test_tools_yosys.py` to run tests in dev shell
          devShells = {
            default = pkgs.mkShell {
              inputsFrom = [ inputs'.infra.packages.iedaUnstable ];
              nativeBuildInputs =
                with pkgs;
                [
                  git
                  black
                  isort
                  uv
                  cargo
                ] ++ [
                  inputs'.infra.packages.yosysWithSlang
                ];
              shellHook = ''
                uv sync --frozen --all-groups --python 3.11
                source .venv/bin/activate
              '';
            };
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
