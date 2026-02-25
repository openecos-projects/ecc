#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 [--versions-json <path>]
EOF
}

append_proxy_prefix() {
    local url="$1"
    local prefix="${2:-}"
    local github_only="${3:-false}"

    if [[ -z "$prefix" ]]; then
        echo "$url"
        return 0
    fi
    if [[ "$github_only" == "true" ]]; then
        case "$url" in
            https://github.com|https://github.com/*)
                ;;
            *)
                echo "$url"
                return 0
                ;;
        esac
    fi
    if [[ "$prefix" != */ ]]; then
        prefix="${prefix}/"
    fi
    echo "${prefix}${url}"
}

compute_sha256() {
    local file_path="$1"

    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file_path" | awk '{print $1}'
        return 0
    fi
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$file_path" | awk '{print $1}'
        return 0
    fi

    echo "ERROR: no SHA-256 tool found (need sha256sum or shasum)." >&2
    return 1
}

get_json_value() {
    local json_path="$1"
    local key_path="$2"
    jq -er --arg key_path "$key_path" 'getpath(($key_path | split(".")))' "$json_path"
}

get_json_value_optional() {
    local json_path="$1"
    local key_path="$2"
    jq -r --arg key_path "$key_path" 'try (getpath(($key_path | split("."))) // "") catch ""' "$json_path"
}

VERSIONS_JSON=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --versions-json)
            VERSIONS_JSON="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

WORKSPACE_DIR="${BUILD_WORKSPACE_DIRECTORY:-$PWD}"
if [[ -z "$VERSIONS_JSON" ]]; then
    VERSIONS_JSON="$WORKSPACE_DIR/bazel/scripts/versions.json"
fi

if [[ ! -f "$VERSIONS_JSON" ]]; then
    echo "ERROR: versions file not found at $VERSIONS_JSON" >&2
    exit 1
fi
for cmd in jq git make; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    }
done

SOURCE_TYPE="$(get_json_value "$VERSIONS_JSON" "icsprout55.type")"
if [[ "$SOURCE_TYPE" != "git" ]]; then
    echo "ERROR: unsupported icsprout55.type: $SOURCE_TYPE (only 'git' is supported)." >&2
    exit 1
fi

REPO_URL="$(get_json_value "$VERSIONS_JSON" "icsprout55.url")"
REV="$(get_json_value "$VERSIONS_JSON" "icsprout55.rev")"
SOURCE_SHA256="$(get_json_value_optional "$VERSIONS_JSON" "icsprout55.sha256")"

TARGET_DIR="$WORKSPACE_DIR/chipcompiler/thirdparty/icsprout55-pdk"
PROXY_PREFIX="${GIT_PROXY_PREFIX:-${GITHUB_PROXY_PREFIX:-}}"
CLONE_URL="$(append_proxy_prefix "$REPO_URL" "$PROXY_PREFIX" "true")"

mkdir -p "$(dirname "$TARGET_DIR")"
if [[ -d "$TARGET_DIR/.git" ]]; then
    git -C "$TARGET_DIR" remote set-url origin "$CLONE_URL"
else
    rm -rf "$TARGET_DIR"
    git clone "$CLONE_URL" "$TARGET_DIR"
fi

if ! git -C "$TARGET_DIR" cat-file -e "${REV}^{commit}" 2>/dev/null; then
    git -C "$TARGET_DIR" fetch --tags --prune origin
fi
git -C "$TARGET_DIR" checkout --detach "$REV"

ACTUAL_REV="$(git -C "$TARGET_DIR" rev-parse HEAD)"
if [[ "$ACTUAL_REV" != "$REV" ]]; then
    echo "ERROR: failed to checkout ${REPO_URL} at ${REV}. Current HEAD: ${ACTUAL_REV}" >&2
    exit 1
fi

if [[ -n "$SOURCE_SHA256" ]]; then
    TMP_DIR="$(mktemp -d)"
    ARCHIVE_PATH="$TMP_DIR/repo.tar"
    (cd "$TARGET_DIR" && git archive --format=tar "$REV" > "$ARCHIVE_PATH")
    ACTUAL_SHA256="$(compute_sha256 "$ARCHIVE_PATH")"
    rm -rf "$TMP_DIR"

    if [[ "$ACTUAL_SHA256" != "$SOURCE_SHA256" ]]; then
        echo "ERROR: git source sha256 mismatch for ${TARGET_DIR}." >&2
        echo "  expected: ${SOURCE_SHA256}" >&2
        echo "  actual:   ${ACTUAL_SHA256}" >&2
        exit 1
    fi
fi

(cd "$TARGET_DIR" && make unzip)
echo "ICS55 PDK ready at: $TARGET_DIR"
