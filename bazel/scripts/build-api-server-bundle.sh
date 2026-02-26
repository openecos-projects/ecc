#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --spec-file <path> --project-dir <path> --runtime-bundle-tar <path> --out-bin <path> --work-dir <path> [--python-bin <path>]
EOF
}

SPEC_FILE=""
PROJECT_DIR=""
RUNTIME_BUNDLE_TAR=""
OUT_BIN=""
WORK_DIR=""
PYTHON_BIN=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --spec-file)
            SPEC_FILE="$2"
            shift 2
            ;;
        --project-dir)
            PROJECT_DIR="$2"
            shift 2
            ;;
        --runtime-bundle-tar)
            RUNTIME_BUNDLE_TAR="$2"
            shift 2
            ;;
        --out-bin)
            OUT_BIN="$2"
            shift 2
            ;;
        --work-dir)
            WORK_DIR="$2"
            shift 2
            ;;
        --python-bin)
            PYTHON_BIN="$2"
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

if [[ -z "$SPEC_FILE" || -z "$PROJECT_DIR" || -z "$RUNTIME_BUNDLE_TAR" || -z "$OUT_BIN" || -z "$WORK_DIR" ]]; then
    echo "ERROR: missing required arguments" >&2
    usage >&2
    exit 1
fi

if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="${CHIPCOMPILER_PYTHON:-$(command -v python3 || true)}"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python interpreter not found. Set CHIPCOMPILER_PYTHON or pass --python-bin." >&2
    exit 1
fi

OUT_DIR="$(dirname "$OUT_BIN")"
mkdir -p "$OUT_DIR" "$WORK_DIR"

tar -xf "$RUNTIME_BUNDLE_TAR" -C .

if "$PYTHON_BIN" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "INFO: using PyInstaller from $PYTHON_BIN"
    "$PYTHON_BIN" -m PyInstaller "$SPEC_FILE" \
        --clean \
        --noconfirm \
        --distpath "$OUT_DIR" \
        --workpath "$WORK_DIR/build"
elif command -v uv >/dev/null 2>&1; then
    echo "INFO: PyInstaller is not installed in $PYTHON_BIN, falling back to uv run"
    uv run --project "$PROJECT_DIR" --group dev --locked --python "$PYTHON_BIN" pyinstaller "$SPEC_FILE" \
        --clean \
        --noconfirm \
        --distpath "$OUT_DIR" \
        --workpath "$WORK_DIR/build"
else
    echo "ERROR: PyInstaller not found in $PYTHON_BIN and uv is unavailable." >&2
    exit 1
fi

if [[ ! -f "$OUT_BIN" ]]; then
    echo "ERROR: expected output not found at $OUT_BIN" >&2
    echo "Files under $OUT_DIR:" >&2
    find "$OUT_DIR" -maxdepth 3 -type f | sort >&2
    exit 1
fi
