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
        bash "${ECC_TOOLS_ROOT}/build.sh" -i apt
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
    rustc -vV | grep host | cut -d' ' -f2
}
