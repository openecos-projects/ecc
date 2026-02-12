final: prev: {
  ecc-tools = prev.callPackage ./ecc-tools { };
  chipcompiler = prev.callPackage ./chipcompiler { };
  ecos-studio = final.callPackage ./ecos-studio { };
}
