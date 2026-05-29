final: prev: {
  ecc-tools-python = prev.python3Packages.callPackage ./python/ecc-tools {
    gflags = prev.gflags;
  };
  ecc-dreamplace-python = prev.python3Packages.callPackage ./python/ecc-dreamplace { };
  chipcompiler = prev.callPackage ./chipcompiler { };
  cli = prev.callPackage ./cli { };
}
