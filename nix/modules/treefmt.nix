{ pkgs, ... }:
{
  treefmt = {
    projectRootFile = "pyproject.toml";
    programs = {
      nixfmt.enable = true;
      nixfmt.package = pkgs.nixfmt-rfc-style;
    };
    flakeCheck = true;
  };
}
