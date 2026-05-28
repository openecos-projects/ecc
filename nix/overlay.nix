final: prev: {
  ecc-tools-python = prev.python3Packages.callPackage ./python/ecc-tools {
    callPackages = prev.callPackages;
    gflags = prev.gflags;
    onnxruntime = prev.onnxruntime;
  };
  ecc-dreamplace-python = prev.python3Packages.callPackage ./python/ecc-dreamplace { };
  chipcompiler = prev.callPackage ./chipcompiler { };
  cli = prev.callPackage ./cli { };
}
