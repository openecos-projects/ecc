#!/usr/bin/env bash

set -e

# Setup Project Variables
PROJECT_ROOT=$(cd "$(dirname "$0")";pwd)
CHIPCOMPILER_ROOT="${PROJECT_ROOT}/chipcompiler"
ECC_TOOLS_ROOT="${CHIPCOMPILER_ROOT}/thirdparty/ecc-tools"
VENV_DIR="${PROJECT_ROOT}/.venv"
PYTHON_VERSION="3.10"
ENABLE_OSS_CAD_SUITE=${ENABLE_OSS_CAD_SUITE:-true}

# Check for uv installation
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed or not in PATH"
    echo "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Create virtual environment if it doesn't exist
echo "Setting up Python ${PYTHON_VERSION} environment with uv..."
uv sync --frozen --all-groups --python ${PYTHON_VERSION}

# Activate virtual environment (for subsequent commands in the script)
echo "Activating virtual environment..."
source "${VENV_DIR}/bin/activate"

# Download and set up OSS CAD Suite if enabled
if [ "$ENABLE_OSS_CAD_SUITE" == "true" ]; then
    OSS_CAD_DIR="${CHIPCOMPILER_ROOT}/thirdparty/oss-cad-suite"
    echo "==============================="
    if [ -d "${OSS_CAD_DIR}" ] && [ -f "${OSS_CAD_DIR}/bin/yosys" ]; then
        echo "OSS CAD Suite already exists at ${OSS_CAD_DIR}, skipping download..."
    else
        LATEST_TAG=$(curl -s "https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
        OSS_CAD_URL="https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${LATEST_TAG}/oss-cad-suite-linux-x64-${LATEST_TAG//-/}.tgz"
        mkdir -p "${OSS_CAD_DIR}"
        TMP_DIR=$(mktemp -d)
        echo "Downloading OSS CAD SUITE BUILD from ${OSS_CAD_URL} to ${TMP_DIR}..."
        curl -fL "${OSS_CAD_URL}" -o "${TMP_DIR}/oss-cad-suite.tgz"
        tar -xzf "${TMP_DIR}/oss-cad-suite.tgz" -C "${OSS_CAD_DIR}" --strip-components=1
        rm -rf "${TMP_DIR}/oss-cad-suite.tgz"
    fi
    echo "OSS CAD Suite is set up at ${OSS_CAD_DIR}, please remember to add it to your PATH:"
    echo -e "\033[1;33mexport PATH=\"${OSS_CAD_DIR}/bin:\$PATH\"\033[0m"
    echo "==============================="
    echo " "
    echo "export PATH=\"${OSS_CAD_DIR}/bin:\$PATH\"" >> "${VENV_DIR}/bin/activate"

    exit 0
fi

git submodule update --init --recursive

# Build ecc_py
echo "Building ecc_py..."

BUILD_DIR="${ECC_TOOLS_ROOT}/build"
if [ ! -d "${BUILD_DIR}" ]; then
    echo "Creating build directory at ${BUILD_DIR}..."
    mkdir -p "${BUILD_DIR}"
else
    echo "Cleaning existing build files at ${BUILD_DIR}..."
    rm -rf "${BUILD_DIR}/CMakeCache.txt" "${BUILD_DIR}/CMakeFiles" "${BUILD_DIR}/build.ninja" "${BUILD_DIR}/Makefile"
fi

cd "${BUILD_DIR}" || exit 1

echo "Configuring project with CMake..."
if command -v cmake &> /dev/null; then
    echo "CMake found: $(cmake --version | head -n 1)"
else
    echo "Error: CMake is not installed or not in PATH"
    bash "${ECC_TOOLS_ROOT}/build.sh" -i apt
fi

# Prefer Ninja if available
if command -v ninja &> /dev/null; then
    echo "Using Ninja generator..."
    cmake -G Ninja -DBUILD_AIEDA=ON ..
else
    echo "Using default generator..."
    cmake -DBUILD_AIEDA=ON ..
fi
if [ $? -ne 0 ]; then
    echo "Error: CMake configuration failed"
    exit 1
fi

echo "Building project..."
if command -v ninja &> /dev/null; then
    echo "Using ninja build system..."
    ninja ecc_py
else
    echo "Using make build system..."
    make -j$(nproc) ecc_py
fi
if [ $? -ne 0 ]; then
    echo "Error: Build failed"
    exit 1
fi

echo "ecc_py build completed successfully!"
echo "Environment setup completed successfully!"
echo "To activate the virtual environment in future sessions, run:"
echo "source ${VENV_DIR}/bin/activate"

if [ "$1" == "--release" ]; then
    echo "Starting executable build process..."
    export PYINSTALLER_ONEFILE=1
    # Clean previous builds
    echo "Cleaning previous builds..."
    rm -rf build/ dist/

    # Run pyinstaller via uv
    uv run pyinstaller chipcompiler.spec
fi