{
  imports =
    let
      modules = builtins.readDir ./modules;
      subDirNames = builtins.attrNames modules;
    in
    map (name: ./modules/${name}) subDirNames;
}
