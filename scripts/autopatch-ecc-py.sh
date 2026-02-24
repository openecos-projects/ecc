#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")" && pwd)"
if [[ -n "${CHIPCOMPILER_PROJECT_ROOT:-}" ]]; then
    PROJECT_ROOT="$(realpath "${CHIPCOMPILER_PROJECT_ROOT}")"
else
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# Add local auto-patchelf to PATH if not already available
if ! command -v auto-patchelf >/dev/null 2>&1; then
    export PATH="${SCRIPT_DIR}/auto-patchelf:${PATH}"
fi

ECC_PY_DST="${PROJECT_ROOT}/chipcompiler/tools/ecc/bin"
ECC_LIB_DST="${ECC_PY_DST}/lib"

ecc_py_inputs=()
runtime_lib_inputs=()
runtime_roots_tar_inputs=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --ecc-py <path>           Path to ecc_py*.so file or directory containing it
  --runtime-lib-path <path> Additional directory to search for .so dependencies (repeatable)
                            Use this when ecc_py.so and build/ are in different locations
  --runtime-roots-tar <path>
                            Tarball that contains runtime search roots (repeatable)
                            This is the preferred input for Bazel-built artifacts
  -h, --help                Show this help message

Examples:
  # Auto-detect from default location
  $0

  # Specify ecc_py.so location
  $0 --ecc-py /path/to/bin/ecc_py.so

  # Separated ecc_py.so and build directory
  $0 --ecc-py /install/bin/ecc_py.so --runtime-lib-path /source/build

  # Bazel artifact with runtime roots tarball
  $0 --ecc-py /path/to/ecc_py.so --runtime-roots-tar /path/to/runtime_roots.tar

  # Multiple runtime library paths
  $0 --runtime-lib-path /path/to/build --runtime-lib-path /path/to/extra/libs
EOF
            exit 0
            ;;
        --ecc-py) ecc_py_inputs+=("$2"); shift 2 ;;
        --runtime-lib-path) runtime_lib_inputs+=("$2"); shift 2 ;;
        --runtime-roots-tar) runtime_roots_tar_inputs+=("$2"); shift 2 ;;
        *) echo "ERROR: unsupported argument: $1" >&2; exit 1 ;;
    esac
done

die() { echo "ERROR: $1" >&2; exit 1; }
find_so() { find "$1" -maxdepth "${2:-999}" -type f \( -name "*.so" -o -name "*.so.*" \) 2>/dev/null | sort; }

for cmd in auto-patchelf patchelf readelf ldd sha256sum tar; do
    command -v "$cmd" >/dev/null || die "required command not found: $cmd"
done

runtime_roots_tmp=""
cleanup() {
    if [[ -n "$runtime_roots_tmp" && -d "$runtime_roots_tmp" ]]; then
        rm -rf "$runtime_roots_tmp"
    fi
}
trap cleanup EXIT

# Collect ecc_py source files
ecc_py_src=()
[[ ${#ecc_py_inputs[@]} -eq 0 ]] && ecc_py_inputs=("${PROJECT_ROOT}/chipcompiler/thirdparty/ecc-tools/bin")
for input in "${ecc_py_inputs[@]}"; do
    if [[ -d "$input" ]]; then
        mapfile -t -O ${#ecc_py_src[@]} ecc_py_src < <(find "$input" -maxdepth 1 -type f -name "ecc_py*.so" | sort)
    elif [[ -f "$input" ]]; then
        [[ "$(basename "$input")" == ecc_py*.so ]] || die "--ecc-py file must match ecc_py*.so: $input"
        ecc_py_src+=("$(realpath "$input")")
    else
        die "--ecc-py path does not exist: $input"
    fi
done
[[ ${#ecc_py_src[@]} -gt 0 ]] || die "no ecc_py shared object found"

# Collect runtime library candidates
runtime_candidates=()
onnx_needed_names=()
declare -A onnx_needed_seen=()
for f in "${ecc_py_src[@]}"; do
    dir="$(dirname "$f")"
    [[ "$(basename "$dir")" == "bin" ]] || continue
    root="$(dirname "$dir")"
    for d in "$root/build"; do
        [[ -d "$d" ]] && mapfile -t -O ${#runtime_candidates[@]} runtime_candidates < <(find_so "$d")
    done
    while IFS= read -r needed_name; do
        [[ -z "$needed_name" ]] && continue
        if [[ ! -v onnx_needed_seen["$needed_name"] ]]; then
            onnx_needed_seen["$needed_name"]=1
            onnx_needed_names+=("$needed_name")
        fi
    done < <(
        readelf -d "$f" 2>/dev/null \
            | sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p' \
            | grep 'onnxruntime' || true
    )
done

if [[ ${#runtime_roots_tar_inputs[@]} -gt 0 ]]; then
    runtime_roots_tmp="$(mktemp -d "${TMPDIR:-/tmp}/ecc-runtime-roots.XXXXXX")"
    root_idx=0
    for input in "${runtime_roots_tar_inputs[@]}"; do
        [[ -f "$input" ]] || die "--runtime-roots-tar path does not exist: $input"
        root_idx=$((root_idx + 1))
        extracted_root="$runtime_roots_tmp/root_$root_idx"
        mkdir -p "$extracted_root"
        tar -xf "$input" -C "$extracted_root"
        runtime_lib_inputs+=("$extracted_root")
    done
fi

for input in "${runtime_lib_inputs[@]}"; do
    if [[ -d "$input" ]]; then
        mapfile -t -O ${#runtime_candidates[@]} runtime_candidates < <(find_so "$input")
    elif [[ -f "$input" ]]; then
        base="$(basename "$input")"
        if [[ "$base" == *.so || "$base" == *.so.* ]]; then
            runtime_candidates+=("$(realpath "$input")")
        else
            die "--runtime-lib-path file must be a .so/.so.*: $input"
        fi
    else
        die "--runtime-lib-path does not exist: $input"
    fi
done

if [[ ${#onnx_needed_names[@]} -gt 0 ]]; then
    has_onnx_candidate=0
    for src in "${runtime_candidates[@]}"; do
        if [[ "$(basename "$src")" == *onnxruntime* ]]; then
            has_onnx_candidate=1
            break
        fi
    done

    if [[ $has_onnx_candidate -eq 0 ]]; then
        echo "[bundle] ecc_py needs onnxruntime; probing system library paths"
        system_onnx_candidates=()
        declare -A seen_system_onnx=()

        if command -v ldconfig >/dev/null 2>&1; then
            while IFS= read -r p; do
                [[ -f "$p" ]] || continue
                if [[ ! -v seen_system_onnx["$p"] ]]; then
                    seen_system_onnx["$p"]=1
                    system_onnx_candidates+=("$p")
                fi
            done < <(ldconfig -p 2>/dev/null | awk '/onnxruntime/ {print $NF}' | sort -u)
        fi

        if [[ ${#system_onnx_candidates[@]} -eq 0 ]]; then
            for d in /lib /lib64 /usr/lib /usr/lib64 /usr/local/lib /usr/local/lib64 /lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu; do
                [[ -d "$d" ]] || continue
                while IFS= read -r p; do
                    [[ -f "$p" ]] || continue
                    if [[ ! -v seen_system_onnx["$p"] ]]; then
                        seen_system_onnx["$p"]=1
                        system_onnx_candidates+=("$p")
                    fi
                done < <(find "$d" -maxdepth 2 -type f -name 'libonnxruntime*.so*' 2>/dev/null | sort)
            done
        fi

        if [[ ${#system_onnx_candidates[@]} -eq 0 ]]; then
            die "ecc_py requires onnxruntime (${onnx_needed_names[*]}) but no system onnxruntime libraries were found"
        fi

        mapfile -t -O ${#runtime_candidates[@]} runtime_candidates < <(printf '%s\n' "${system_onnx_candidates[@]}")
    fi
fi

if [[ ${#runtime_candidates[@]} -eq 0 ]]; then
    echo "WARN: no extra runtime .so candidates found; relying on system library paths" >&2
fi

mkdir -p "$ECC_PY_DST" "$ECC_LIB_DST"

echo "[bundle] copying ecc_py modules"
cp -f "${ecc_py_src[@]}" "$ECC_PY_DST/"

echo "[bundle] collecting runtime libraries"
declare -A seen=()
copied=0
for src in "${runtime_candidates[@]}"; do
    base="$(basename "$src")"
    [[ "$base" != ecc_py*.so ]] || continue
    hash="$(sha256sum "$src" | cut -d' ' -f1)"
    if [[ -v seen["$base"] ]]; then
        [[ "${seen["$base"]}" == "$hash" ]] || die "library conflict: $base"
        continue
    fi
    cp -f "$src" "$ECC_LIB_DST/"
    seen["$base"]="$hash"
    copied=$((copied + 1))
done

if [[ ${#onnx_needed_names[@]} -gt 0 ]]; then
    missing_onnx=()
    for needed_name in "${onnx_needed_names[@]}"; do
        [[ -e "$ECC_LIB_DST/$needed_name" ]] || missing_onnx+=("$needed_name")
    done
    if [[ ${#missing_onnx[@]} -gt 0 ]]; then
        die "missing required onnxruntime libraries after bundling: ${missing_onnx[*]}"
    fi
fi

# Build search paths for auto-patchelf
search_paths=("$ECC_LIB_DST")
for f in "${ecc_py_src[@]}"; do
    dir="$(dirname "$f")"
    [[ "$(basename "$dir")" == "bin" ]] || continue
    lib="$(dirname "$dir")/lib"
    [[ -d "$lib" ]] && search_paths+=("$lib")
done
for d in /lib /lib64 /usr/lib /usr/lib64 /usr/local/lib /usr/local/lib64 /lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu; do
    [[ -d "$d" ]] && search_paths+=("$d")
done

mapfile -t ecc_py_dst < <(find "$ECC_PY_DST" -maxdepth 1 -type f -name "ecc_py*.so" | sort)

echo "[bundle] running auto-patchelf"
auto-patchelf --no-recurse --ignore-missing --paths "${ecc_py_dst[@]}" "$ECC_LIB_DST" --libs "${search_paths[@]}"

echo "[bundle] setting RUNPATH"
for f in "${ecc_py_dst[@]}"; do patchelf --set-rpath '$ORIGIN:$ORIGIN/lib' "$f"; done
for f in $(find_so "$ECC_LIB_DST" 1); do
    readelf -h "$f" &>/dev/null && patchelf --set-rpath '$ORIGIN' "$f" || echo "WARN: skip non-ELF: $f" >&2
done

echo "[bundle] verifying dependencies"
for f in "${ecc_py_dst[@]}"; do
    ldd "$f" | grep -q "not found" && { echo "ERROR: unresolved deps in $f" >&2; ldd "$f" >&2; exit 1; }
done

echo "[bundle] done: ${#ecc_py_dst[@]} ecc_py files, $copied runtime libs in $ECC_LIB_DST"
