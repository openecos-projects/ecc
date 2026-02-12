final: prev:
{
  ecc-tools = prev.callPackage ./ecc-tools/ecc-tools.nix {};
  chipcompiler = prev.callPackage ./chipcompiler.nix {};
  ecos-studio = final.callPackage ./ecos-studio.nix {};
}
