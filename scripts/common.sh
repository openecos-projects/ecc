#!/usr/bin/env bash
#
# Common functions and variables for ChipCompiler build scripts
#

# Setup Project Variables
setup_project_vars() {
    export PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)}"
    export CHIPCOMPILER_ROOT="${PROJECT_ROOT}/chipcompiler"
    export ECC_TOOLS_ROOT="${CHIPCOMPILER_ROOT}/thirdparty/ecc-tools"
    export ICS55_PDK_ROOT="${CHIPCOMPILER_ROOT}/thirdparty/icsprout55-pdk"
    export OSS_CAD_DIR="${CHIPCOMPILER_ROOT}/thirdparty/oss-cad-suite"
    export VENV_DIR="${PROJECT_ROOT}/.venv"
    export PYTHON_VERSION="${PYTHON_VERSION:-3.10}"
    export ENABLE_OSS_CAD_SUITE="${ENABLE_OSS_CAD_SUITE:-true}"
    export ECC_PY_GLOB="${ECC_TOOLS_ROOT}/bin/ecc_py*.so"
    export CMAKE_EXTRA_OPTIONS="${CMAKE_EXTRA_OPTIONS:-}"
}

# Check and setup uv environment
setup_uv_env() {
    if ! command -v uv &> /dev/null; then
        echo "Error: uv is not installed or not in PATH"
        echo "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        return 1
    fi

    echo "Setting up Python ${PYTHON_VERSION} environment with uv..."
    uv sync --frozen --all-groups --python "${PYTHON_VERSION}"

    echo "Activating virtual environment..."
    source "${VENV_DIR}/bin/activate"
}

# Download and setup OSS CAD Suite
setup_oss_cad_suite() {
    [[ "$ENABLE_OSS_CAD_SUITE" != "true" ]] && return 0

    echo "==============================="
    if [[ -d "${OSS_CAD_DIR}" && -f "${OSS_CAD_DIR}/bin/yosys" ]]; then
        echo "OSS CAD Suite already exists at ${OSS_CAD_DIR}, skipping download..."
    else
        local latest_tag
        latest_tag=$(curl -s "https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
        local oss_cad_url="https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${latest_tag}/oss-cad-suite-linux-x64-${latest_tag//-/}.tgz"

        mkdir -p "${OSS_CAD_DIR}"
        local tmp_dir
        tmp_dir=$(mktemp -d)
        echo "Downloading OSS CAD Suite from ${oss_cad_url}..."
        curl -fL "${oss_cad_url}" -o "${tmp_dir}/oss-cad-suite.tgz"
        tar -xzf "${tmp_dir}/oss-cad-suite.tgz" -C "${OSS_CAD_DIR}" --strip-components=1
        rm -rf "${tmp_dir}"
    fi

    export PATH="${OSS_CAD_DIR}/bin:$PATH"
    echo "OSS CAD Suite is set up at ${OSS_CAD_DIR}"
    echo -e "\033[1;33mexport PATH=\"${OSS_CAD_DIR}/bin:\$PATH\"\033[0m"
    echo "==============================="
}

_oss_cad_keep_path() {
    local root="$1"
    local abs_path="$2"
    local keep_file="$3"

    if [[ ! -e "$abs_path" ]]; then
        return 0
    fi
    if [[ "$abs_path" != "$root/"* ]]; then
        return 0
    fi

    local rel_path="${abs_path#"$root"/}"
    if ! grep -Fxq "$rel_path" "$keep_file"; then
        echo "$rel_path" >> "$keep_file"
    fi

    if [[ -L "$abs_path" ]]; then
        local real_path
        real_path=$(readlink -f "$abs_path" 2>/dev/null || true)
        if [[ -n "$real_path" && "$real_path" == "$root/"* ]]; then
            local real_rel="${real_path#"$root"/}"
            if ! grep -Fxq "$real_rel" "$keep_file"; then
                echo "$real_rel" >> "$keep_file"
            fi
        fi
    fi
}

_oss_cad_collect_elf_closure() {
    local root="$1"
    local seed="$2"
    local keep_file="$3"
    local seen_file="$4"

    [[ -e "$seed" ]] || return 0

    local queue=("$seed")
    while ((${#queue[@]} > 0)); do
        local current="${queue[0]}"
        queue=("${queue[@]:1}")

        _oss_cad_keep_path "$root" "$current" "$keep_file"

        if grep -Fxq "$current" "$seen_file"; then
            continue
        fi
        echo "$current" >> "$seen_file"

        while IFS= read -r dep; do
            [[ -n "$dep" ]] || continue
            if [[ "$dep" == "$root/"* ]]; then
                _oss_cad_keep_path "$root" "$dep" "$keep_file"
                if ! grep -Fxq "$dep" "$seen_file"; then
                    queue+=("$dep")
                fi
            fi
        done < <(ldd "$current" 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i ~ /^\//) print $i}')
    done
}

prune_oss_cad_runtime() {
    local oss_cad_bundle_dir="$1"
    local target="$2"

    if [[ "$target" != *"linux"* ]]; then
        return 0
    fi
    if ! command -v ldd >/dev/null 2>&1; then
        echo "Warning: ldd not found, skipping OSS CAD runtime pruning."
        return 0
    fi

    local keep_file
    local seen_file
    keep_file=$(mktemp)
    seen_file=$(mktemp)

    # Keep known runtime libs required by yosys launcher/executable in AppImage.
    # ldd can resolve to host paths during build-time and miss bundled libs, so
    # we keep a conservative minimal set explicitly.
    local required_lib_patterns=(
        "ld-linux*"
        "libc.so*"
        "libm.so*"
        "libz.so*"
        "libgcc_s.so*"
        "libstdc++.so*"
        "libffi.so*"
        "libreadline.so*"
        "libtcl8.6.so*"
        "libtinfo.so*"
    )
    local pat
    for pat in "${required_lib_patterns[@]}"; do
        for f in "$oss_cad_bundle_dir/lib"/$pat; do
            [[ -e "$f" ]] || continue
            _oss_cad_keep_path "$oss_cad_bundle_dir" "$f" "$keep_file"
        done
    done

    # Keep loader path used by bin/yosys wrapper.
    for interp in "$oss_cad_bundle_dir"/lib/ld-linux* "$oss_cad_bundle_dir"/lib64/ld-linux*; do
        [[ -e "$interp" ]] || continue
        _oss_cad_keep_path "$oss_cad_bundle_dir" "$interp" "$keep_file"
    done

    # Yosys Tcl runtime scripts (set by wrapper env vars).
    if [[ -d "$oss_cad_bundle_dir/lib/tcl8.6" ]]; then
        find "$oss_cad_bundle_dir/lib/tcl8.6" \( -type f -o -type l \) | while IFS= read -r f; do
            _oss_cad_keep_path "$oss_cad_bundle_dir" "$f" "$keep_file"
        done
    fi
    if [[ -d "$oss_cad_bundle_dir/lib/tk8.6" ]]; then
        find "$oss_cad_bundle_dir/lib/tk8.6" \( -type f -o -type l \) | while IFS= read -r f; do
            _oss_cad_keep_path "$oss_cad_bundle_dir" "$f" "$keep_file"
        done
    fi

    local elf_seeds=(
        "$oss_cad_bundle_dir/libexec/yosys"
        "$oss_cad_bundle_dir/bin/yosys-abc"
        "$oss_cad_bundle_dir/bin/abc"
        "$oss_cad_bundle_dir/share/yosys/plugins/slang.so"
    )

    local seed
    for seed in "${elf_seeds[@]}"; do
        _oss_cad_collect_elf_closure "$oss_cad_bundle_dir" "$seed" "$keep_file" "$seen_file"
    done

    if [[ -d "$oss_cad_bundle_dir/lib" ]]; then
        find "$oss_cad_bundle_dir/lib" \( -type f -o -type l \) | while IFS= read -r f; do
            local rel="${f#"$oss_cad_bundle_dir"/}"
            if ! grep -Fxq "$rel" "$keep_file"; then
                rm -f "$f"
            fi
        done
        find "$oss_cad_bundle_dir/lib" -depth -type d -empty -delete
    fi

    if [[ -d "$oss_cad_bundle_dir/libexec" ]]; then
        find "$oss_cad_bundle_dir/libexec" \( -type f -o -type l \) | while IFS= read -r f; do
            local rel="${f#"$oss_cad_bundle_dir"/}"
            if ! grep -Fxq "$rel" "$keep_file"; then
                rm -f "$f"
            fi
        done
        find "$oss_cad_bundle_dir/libexec" -depth -type d -empty -delete
    fi

    rm -f "$keep_file" "$seen_file"
}

# Stage OSS CAD Suite into Tauri resources
stage_oss_cad_suite() {
    local tauri_resources_dir="$1"
    local oss_cad_bundle_dir="$2"
    local target="$3"

    mkdir -p "$tauri_resources_dir"
    if [[ "$ENABLE_OSS_CAD_SUITE" != "true" ]]; then
        mkdir -p "$oss_cad_bundle_dir"
        return 0
    fi

    if [[ ! -d "${OSS_CAD_DIR}" || ! -f "${OSS_CAD_DIR}/bin/yosys" ]]; then
        echo "ERROR: OSS CAD Suite not found at ${OSS_CAD_DIR}."
        return 1
    fi

    rm -rf "$oss_cad_bundle_dir"
    mkdir -p "$oss_cad_bundle_dir"

    local yosys_bin_src="$OSS_CAD_DIR/bin/yosys"
    if [[ "$target" == *"windows"* ]]; then
        yosys_bin_src="$OSS_CAD_DIR/bin/yosys.exe"
    fi

    if [ ! -f "$yosys_bin_src" ]; then
        echo "ERROR: yosys binary not found at $yosys_bin_src"
        return 1
    fi

    local slang_src
    slang_src=$(ls "$OSS_CAD_DIR/share/yosys/plugins"/slang.* 2>/dev/null | head -1)
    if [ -z "$slang_src" ]; then
        echo "ERROR: slang plugin not found under $OSS_CAD_DIR/share/yosys/plugins"
        return 1
    fi

    cp -a "$OSS_CAD_DIR/." "$oss_cad_bundle_dir/"
    if [ -d "$oss_cad_bundle_dir/bin" ]; then
        find "$oss_cad_bundle_dir/bin" -maxdepth 1 -type f ! -name 'yosys' ! -name 'yosys*' ! -name 'abc' -print0 | xargs -0 -r rm -f
    fi
    prune_oss_cad_runtime "$oss_cad_bundle_dir" "$target"
    if [ -d "$oss_cad_bundle_dir/examples" ]; then
        rm -rf "$oss_cad_bundle_dir/examples"
    fi
    if [ -d "$oss_cad_bundle_dir/py3bin" ]; then
        rm -rf "$oss_cad_bundle_dir/py3bin"
    fi
    if [ -d "$oss_cad_bundle_dir/super_prove" ]; then
        rm -rf "$oss_cad_bundle_dir/super_prove"
    fi
    if [ -d "$oss_cad_bundle_dir/share" ]; then
        find "$oss_cad_bundle_dir/share" -mindepth 1 -maxdepth 1 -print0 | \
            xargs -0 -r -I {} bash -c 'if [ "$(basename "{}")" != "yosys" ]; then rm -rf "{}"; fi'
    fi
    if [ -d "$oss_cad_bundle_dir/share/yosys" ]; then
        # Keep top-level files under share/yosys (e.g. techmap.v), and only prune
        # unnecessary subdirectories.
        find "$oss_cad_bundle_dir/share/yosys" -mindepth 1 -maxdepth 1 -type d -print0 | \
            xargs -0 -r -I {} bash -c 'name=$(basename "{}"); case "$name" in plugins|techlibs|scripts) ;; *) rm -rf "{}" ;; esac'
        if [ -d "$oss_cad_bundle_dir/share/yosys/plugins" ]; then
            find "$oss_cad_bundle_dir/share/yosys/plugins" -type f ! -name 'slang.so' -print0 | xargs -0 -r rm -f
        fi
    fi
    chmod +x "$oss_cad_bundle_dir/bin/$(basename "$yosys_bin_src")"
}

# Append OSS CAD path to venv activate script
append_oss_cad_to_venv() {
    if [[ "$ENABLE_OSS_CAD_SUITE" == "true" ]]; then
        echo "export PATH=\"${OSS_CAD_DIR}/bin:\$PATH\"" >> "${VENV_DIR}/bin/activate"
    fi
}

# Initialize git submodules
setup_submodules() {
    echo "Setting up third-party submodules..."
    git submodule update --init --recursive
}

# Setup ICS55 PDK
setup_ics55_pdk() {
    if [[ -d "${ICS55_PDK_ROOT}" ]]; then
        echo "Setting up ICS55 PDK..."
        (cd "${ICS55_PDK_ROOT}" && make unzip)
    fi
}

# Ensure yosys is available
ensure_yosys() {
    if command -v yosys &> /dev/null; then
        echo "yosys found: $(command -v yosys)"
        return 0
    fi

    if [[ "$ENABLE_OSS_CAD_SUITE" == "true" ]]; then
        setup_oss_cad_suite
        if command -v yosys &> /dev/null; then
            echo "yosys installed: $(command -v yosys)"
            return 0
        fi
    fi

    echo "ERROR: yosys not found"
    return 1
}

# Build ecc_py
build_ecc_py() {
    local force="${1:-false}"

    if [[ "$force" != "true" ]] && ls ${ECC_PY_GLOB} >/dev/null 2>&1; then
        echo "ecc_py already exists in ${ECC_TOOLS_ROOT}/bin."
        return 0
    fi

    echo "Building ecc_py..."

    if [[ ! -d "${ECC_TOOLS_ROOT}" ]]; then
        echo "ERROR: ecc-tools submodule not found. Run: git submodule update --init --recursive"
        return 1
    fi

    local build_dir="${ECC_TOOLS_ROOT}/build"
    mkdir -p "${build_dir}"
    rm -rf "${build_dir}/CMakeCache.txt" "${build_dir}/CMakeFiles" "${build_dir}/build.ninja" "${build_dir}/Makefile"

    cd "${build_dir}" || return 1

    if ! command -v cmake &> /dev/null; then
        echo "Error: CMake is not installed or not in PATH"
        sudo bash "${ECC_TOOLS_ROOT}/build.sh" -i apt
    fi

    echo "Configuring project with CMake..."
    local cmake_opts=("-DBUILD_AIEDA=ON")
    local cmake_gen=""
    if command -v ninja &> /dev/null; then
        echo "Using Ninja generator..."
        cmake_gen="-G Ninja"
    else
        echo "Using default generator..."
    fi

    local cmake_cmd="cmake ${cmake_gen} ${cmake_opts[*]}"
    if [[ -n "${CMAKE_EXTRA_OPTIONS}" ]]; then
        cmake_cmd+=" ${CMAKE_EXTRA_OPTIONS}"
    fi
    cmake_cmd+=" .."
    eval "${cmake_cmd}"

    if [[ $? -ne 0 ]]; then
        echo "Error: CMake configuration failed"
        return 1
    fi

    echo "Building project..."
    if command -v ninja &> /dev/null; then
        ninja ecc_py
    else
        make -j"$(nproc)" ecc_py
    fi

    if [[ $? -ne 0 ]]; then
        echo "Error: Build failed"
        return 1
    fi

    if ! ls ${ECC_PY_GLOB} >/dev/null 2>&1; then
        echo "ERROR: ecc_py build failed (ecc_py*.so not found)."
        return 1
    fi

    echo "ecc_py build completed successfully!"
    cd "${PROJECT_ROOT}" || return 1
}

# Copy ecc_py.so to tools/ecc/bin directory
install_ecc_py() {
    echo "Copying ecc_py.so to tools/ecc/bin directory..."
    local ecc_py_bin_dir="${CHIPCOMPILER_ROOT}/tools/ecc/bin"
    local ecc_tools_bin_dir="${ECC_TOOLS_ROOT}/bin"

    mkdir -p "${ecc_py_bin_dir}"

    local ecc_py_file
    ecc_py_file=$(find "${ecc_tools_bin_dir}" -name "ecc_py*.so" | head -1)

    if [[ -f "${ecc_py_file}" ]]; then
        echo "Found ecc_py file: ${ecc_py_file}"
        cp "${ecc_py_file}" "${ecc_py_bin_dir}/"
        echo "Successfully copied ecc_py.so to ${ecc_py_bin_dir}/"
    else
        echo "Warning: ecc_py.so file not found in ${ecc_tools_bin_dir}"
    fi
}

# Get target platform for Tauri
get_target_platform() {
    if ! command -v rustc >/dev/null 2>&1; then
        echo "ERROR: rustc is not installed or not in PATH." >&2
        return 1
    fi

    local target
    target="$(rustc -vV 2>/dev/null | sed -n 's/^host: //p' | head -n 1)"

    if [[ -z "$target" ]]; then
        echo "ERROR: failed to detect Rust target triple from 'rustc -vV'." >&2
        return 1
    fi

    echo "$target"
}

# Inject OSS CAD Suite into an existing AppImage via extract-copy-repack.
inject_oss_cad_into_appimage() {
    local appimage_path="$1"
    local oss_cad_source="$2"

    if [[ "$ENABLE_OSS_CAD_SUITE" != "true" ]]; then
        return 0
    fi
    if [[ ! -f "$appimage_path" || ! -d "$oss_cad_source" ]]; then
        echo "ERROR: AppImage or OSS CAD source not found"
        return 1
    fi

    local appimage_abs
    appimage_abs=$(readlink -f "$appimage_path")
    local work_dir
    work_dir=$(mktemp -d)

    echo "[inject] Extracting AppImage: $appimage_abs"
    (cd "$work_dir" && APPIMAGE_EXTRACT_AND_RUN=1 "$appimage_abs" --appimage-extract >/dev/null) || {
        echo "ERROR: failed to extract AppImage"
        rm -rf "$work_dir"
        return 1
    }

    local target_dir="$work_dir/squashfs-root/usr/lib/ECC/resources/oss-cad-suite"
    rm -rf "$target_dir"
    cp -a "$oss_cad_source" "$target_dir"

    local appimagetool="${APPIMAGETOOL_PATH:-}"
    if [[ -z "$appimagetool" ]]; then
        if command -v appimagetool >/dev/null 2>&1; then
            appimagetool="appimagetool"
        else
            appimagetool="$work_dir/appimagetool-x86_64.AppImage"
            echo "[inject] Downloading appimagetool..."
            curl -fL "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -o "$appimagetool"
            chmod +x "$appimagetool"
        fi
    fi
    echo "[inject] Repacking AppImage"
    if ! APPIMAGE_EXTRACT_AND_RUN=1 "$appimagetool" "$work_dir/squashfs-root" "$appimage_abs" >/dev/null; then
        echo "ERROR: appimagetool repack failed"
        rm -rf "$work_dir"
        return 1
    fi

    chmod +x "$appimage_abs"
    rm -rf "$work_dir"
    echo "[inject] AppImage post-injected: $appimage_abs"
}

# Build Tauri bundles and copy the API server binary into release dir.
# On Linux, build deb with embedded OSS CAD and appimage with post-injection.
build_tauri_bundle() {
    local gui_dir="$1"
    local tauri_dir="$2"
    local oss_cad_bundle_dir="$3"
    local binaries_dir="$4"
    local binary_name="$5"

    local target
    target=$(get_target_platform) || return 1
    local tauri_resources_dir
    tauri_resources_dir="$(dirname "$oss_cad_bundle_dir")"

    if [ -d "$HOME/.local/bin" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
    export RUST_BACKTRACE=1

    echo "=== Step 8: Building Tauri application ==="

    if [[ "$target" == *"linux"* ]]; then
        # Build deb with full OSS CAD suite embedded
        stage_oss_cad_suite "$tauri_resources_dir" "$oss_cad_bundle_dir" "$target" || return 1
        (cd "$gui_dir" && pnpm exec tauri build --bundles deb --verbose) || return 1

        # Save staged payload, replace with placeholder for appimage
        local payload_dir
        payload_dir=$(mktemp -d)
        mv "$oss_cad_bundle_dir" "$payload_dir/oss-cad-suite"
        mkdir -p "$oss_cad_bundle_dir"
        echo "Placeholder" > "$oss_cad_bundle_dir/README"

        # Build appimage without OSS CAD suite
        (cd "$gui_dir" && pnpm exec tauri build --bundles appimage --verbose) || {
            rm -rf "$payload_dir"; return 1
        }

        # Post-inject OSS CAD suite into AppImage
        local appimage_path
        appimage_path=$(find "$tauri_dir/target/release/bundle" -type f -name "*.AppImage" 2>/dev/null | sort | tail -1)
        if [[ -n "$appimage_path" && -d "$payload_dir/oss-cad-suite" ]]; then
            inject_oss_cad_into_appimage "$appimage_path" "$payload_dir/oss-cad-suite" || {
                rm -rf "$payload_dir"; return 1
            }
        fi

        # Restore staged resources
        rm -rf "$oss_cad_bundle_dir"
        mv "$payload_dir/oss-cad-suite" "$oss_cad_bundle_dir" 2>/dev/null || true
        rm -rf "$payload_dir"
    else
        stage_oss_cad_suite "$tauri_resources_dir" "$oss_cad_bundle_dir" "$target" || return 1
        if ! (cd "$gui_dir" && pnpm exec tauri build --verbose); then
            echo "ERROR: Tauri build failed"
            return 1
        fi
    fi

    echo "=== Step 9: Copying API Server to release directory ==="
    local release_dir="$tauri_dir/target/release"
    if [ -d "$release_dir" ]; then
        cp "$binaries_dir/$binary_name" "$release_dir/$binary_name"
        chmod +x "$release_dir/$binary_name"
        echo "Copied: $release_dir/$binary_name"
    else
        echo "Warning: Release directory not found, skipping copy"
    fi
    echo ""

    if [ -d "$tauri_dir/target/release/bundle" ]; then
        echo "Generated packages:"
        find "$tauri_dir/target/release/bundle" -type f \( -name "*.dmg" -o -name "*.app" -o -name "*.deb" -o -name "*.rpm" -o -name "*.AppImage" -o -name "*.msi" -o -name "*.exe" \) 2>/dev/null | while read f; do
            echo "  - $f"
        done
    fi
}
