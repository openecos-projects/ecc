# lit + FileCheck from llvmPackages_23.libllvm. Caller must pass llvmPackages_23.

{
  lit,
  llvmPackages_23,
  writeShellApplication,
  symlinkJoin,
  jq,
}:

let
  # Review pin: llvmPackages_23.libllvm (provides FileCheck).
  llvm = llvmPackages_23.libllvm;

  filecheck = writeShellApplication {
    name = "filecheck";
    runtimeInputs = [ llvm ];
    text = ''
      exec FileCheck "$@"
    '';
  };

  exportCsvSh = ./scripts/export_signoff_csv.sh;
  materializeSh = ./scripts/materialize_signoff_workspace.sh;
  signoffLitSh = ./scripts/signoff_lit.sh;

  signoff-lit = writeShellApplication {
    name = "signoff-lit";
    runtimeInputs = [
      lit
      filecheck
      jq
    ];
    text = ''
      root="''${ECC_REPO_ROOT:-$PWD}"
      export ECC_REPO_ROOT="$root"
      export ECC_EXPORT_SIGNOFF_CSV="''${ECC_EXPORT_SIGNOFF_CSV:-${exportCsvSh}}"
      export ECC_MATERIALIZE_READY="''${ECC_MATERIALIZE_READY:-${materializeSh}}"
      export FILECHECK="''${FILECHECK:-filecheck}"
      export LIT="''${LIT:-lit}"
      if [ -x "$root/.venv/bin/python" ]; then
        export PYTHON="$root/.venv/bin/python"
      fi
      exec bash ${signoffLitSh} "$@"
    '';
  };

  signoff-tools = symlinkJoin {
    name = "ecc-signoff-tools";
    paths = [
      lit
      filecheck
      signoff-lit
      jq
    ];
    meta.description = "lit + FileCheck (llvmPackages_23); run via signoff-lit";
  };
in
{
  inherit
    filecheck
    lit
    signoff-lit
    signoff-tools
    ;
}
