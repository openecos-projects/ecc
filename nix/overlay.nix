final: prev: {
  ecc-tools = prev.callPackage ./ecc-tools { };
  chipcompiler = prev.callPackage ./chipcompiler { };
  cli = prev.callPackage ./cli { };
}
