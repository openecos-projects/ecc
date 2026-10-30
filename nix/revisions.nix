{
  lib,
  writeShellApplication,
  jq,
}:

let
  manifest = builtins.fromTOML (builtins.readFile ../.github/revision.toml);

  required = {
    oss_cad_suite = [
      "version"
      "sha256"
    ];
    sizer = [
      "repo"
      "workflow"
      "run_id"
      "git_commit"
      "artifact"
      "archive"
      "root_marker"
      "sha256"
    ];
    kepler-formal = [
      "repo"
      "workflow"
      "version"
      "run_id"
      "git_commit"
      "artifact"
      "archive"
      "root_marker"
      "sha256"
    ];
    pdk = [
      "repo"
      "release"
      "git_commit"
    ];
  };

  missing = lib.flatten (
    map (
      section:
      if !(builtins.hasAttr section manifest) then
        [ section ]
      else
        map (field: "${section}.${field}") (
          lib.filter (field: !(builtins.hasAttr field manifest.${section})) required.${section}
        )
    ) (builtins.attrNames required)
  );

  unexpected = lib.flatten (
    map (
      section:
      if !(builtins.hasAttr section manifest) then
        [ ]
      else
        map (field: "${section}.${field}") (
          lib.filter (field: !(lib.elem field required.${section})) (builtins.attrNames manifest.${section})
        )
    ) (builtins.attrNames required)
  );

  unknownSections = lib.filter (section: !(builtins.hasAttr section required)) (
    builtins.attrNames manifest
  );

  shaSections = [
    "oss_cad_suite"
    "sizer"
    "kepler-formal"
  ];
  badSha = lib.filter (
    section: builtins.match "[0-9a-f]{64}" manifest.${section}.sha256 == null
  ) shaSections;

  commitSections = [
    "sizer"
    "kepler-formal"
    "pdk"
  ];
  badCommits = lib.filter (
    section: builtins.match "[0-9a-f]{40}" manifest.${section}.git_commit == null
  ) commitSections;

  badRunIds =
    lib.filter
      (section: !(builtins.isInt manifest.${section}.run_id) || manifest.${section}.run_id <= 0)
      [
        "sizer"
        "kepler-formal"
      ];

  checked =
    if missing != [ ] then
      throw "revision.toml missing required fields: ${lib.concatStringsSep ", " missing}"
    else if unexpected != [ ] then
      throw "revision.toml contains unsupported fields: ${lib.concatStringsSep ", " unexpected}"
    else if unknownSections != [ ] then
      throw "revision.toml contains unknown sections: ${lib.concatStringsSep ", " unknownSections}"
    else if badSha != [ ] then
      throw "revision.toml has invalid SHA-256 values in: ${lib.concatStringsSep ", " badSha}"
    else if badCommits != [ ] then
      throw "revision.toml has invalid Git commits in: ${lib.concatStringsSep ", " badCommits}"
    else if badRunIds != [ ] then
      throw "revision.toml has invalid run IDs in: ${lib.concatStringsSep ", " badRunIds}"
    else
      manifest;

  sanitize = value: builtins.replaceStrings [ "-" ] [ "_" ] value;
  flat = lib.foldlAttrs (
    acc: section: values:
    acc
    // lib.mapAttrs' (name: value: {
      name = "${sanitize section}_${name}";
      value = toString value;
    }) values
  ) { } checked;
in
writeShellApplication {
  name = "list-versions";
  runtimeInputs = [ jq ];
  text = ''
    format=json
    while (( $# > 0 )); do
      case "$1" in
        --format)
          (( $# >= 2 )) || { printf 'missing value for --format\n' >&2; exit 2; }
          format=$2
          shift 2
          ;;
        -h|--help)
          printf 'usage: list-versions [--format json|github|env]\n'
          exit 0
          ;;
        *)
          printf 'unknown argument: %s\n' "$1" >&2
          exit 2
          ;;
      esac
    done

    revisions_json=${lib.escapeShellArg (builtins.toJSON checked)}
    flat_json=${lib.escapeShellArg (builtins.toJSON flat)}

    case "$format" in
      json)
        jq . <<<"$revisions_json"
        ;;
      github)
        jq -r 'to_entries[] | "\(.key)=\(.value)"' <<<"$flat_json"
        ;;
      env)
        jq -r 'to_entries[] | "export REVISIONS_\(.key | ascii_upcase)=\(.value | @sh)"' <<<"$flat_json"
        ;;
      *)
        printf 'unsupported format: %s\n' "$format" >&2
        exit 2
        ;;
    esac
  '';
}
