{ pkgs, inputs', ... }:
{
  devShells = {
    default = pkgs.mkShell {
      inputsFrom = [
        inputs'.infra.packages.iedaUnstable
        pkgs.ecc-tools
        pkgs.chipcompiler
        pkgs.ecos-studio
      ];
      nativeBuildInputs = with pkgs; [ uv bazel_8 ];
      shellHook = ''
        uv sync --frozen --all-groups --python 3.11
        source .venv/bin/activate
      '';
    };
  };
}
