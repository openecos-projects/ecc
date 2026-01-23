#!/usr/bin/env bash

set -e

# 设置项目根目录
PROJECT_ROOT=$(cd "$(dirname "$0")";pwd)
CHIPCOMPILER_ROOT="${PROJECT_ROOT}/chipcompiler"
VENV_DIR="${PROJECT_ROOT}/.venv"
PYTHON_VERSION="3.10"

# 检查必要的命令是否可用
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "Error: $1 is not installed or not in PATH"
        exit 1
    fi
}

# 检查必要的命令
check_command uv
check_command curl
check_command grep
check_command tar
check_command cmake

# 创建虚拟环境并安装依赖（包括 dev 依赖）
echo "Setting up Python ${PYTHON_VERSION} environment with uv..."
uv sync --frozen --all-groups --python ${PYTHON_VERSION}

# 激活虚拟环境（用于后续脚本中的命令）
echo "Activating virtual environment..."
if [ -f "${VENV_DIR}/bin/activate" ]; then
    source "${VENV_DIR}/bin/activate"
else
    echo "Error: Virtual environment activation script not found at ${VENV_DIR}/bin/activate"
    exit 1
fi

# 下载 OSS CAD SUITE BUILD (如果不存在)
OSS_CAD_DIR="${CHIPCOMPILER_ROOT}/thirdparty/oss-cad-suite"
echo "==============================="
if [ -d "${OSS_CAD_DIR}" ] && [ -f "${OSS_CAD_DIR}/bin/yosys" ]; then
    echo "OSS CAD Suite already exists at ${OSS_CAD_DIR}, skipping download..."
else
    echo "Downloading OSS CAD SUITE BUILD..."
    # 获取最新版本标签
    LATEST_TAG=$(curl -s "https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
    if [ -z "${LATEST_TAG}" ]; then
        echo "Error: Failed to get latest OSS CAD Suite tag"
        exit 1
    fi
    
    # 构建下载URL
    OSS_CAD_URL="https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${LATEST_TAG}/oss-cad-suite-linux-x64-${LATEST_TAG//-/}.tgz"
    echo "Downloading from ${OSS_CAD_URL}..."
    
    # 创建目录
    mkdir -p "${OSS_CAD_DIR}"
    
    # 创建临时目录
    TMP_DIR=$(mktemp -d)
    if [ -z "${TMP_DIR}" ]; then
        echo "Error: Failed to create temporary directory"
        exit 1
    fi
    
    # 下载文件
    if ! curl -fL "${OSS_CAD_URL}" -o "${TMP_DIR}/oss-cad-suite.tgz"; then
        echo "Error: Failed to download OSS CAD Suite"
        rm -rf "${TMP_DIR}"
        exit 1
    fi
    
    # 解压文件
    if ! tar -xzf "${TMP_DIR}/oss-cad-suite.tgz" -C "${OSS_CAD_DIR}" --strip-components=1; then
        echo "Error: Failed to extract OSS CAD Suite"
        rm -rf "${TMP_DIR}"
        exit 1
    fi
    
    # 清理临时文件和目录
    rm -rf "${TMP_DIR}"
    echo "OSS CAD Suite downloaded and extracted successfully!"
fi
echo "OSS CAD Suite is set up at ${OSS_CAD_DIR}, please remember to add it to your PATH:"
echo -e "\033[1;33mexport PATH=\"${OSS_CAD_DIR}/bin:\$PATH\"\033[0m"
echo "==============================="
echo " "

# 构建ieda_py
echo "Building ieda_py..."

# 创建build目录（如果不存在）
BUILD_DIR="${PROJECT_ROOT}/build"
if [ ! -d "${BUILD_DIR}" ]; then
    echo "Creating build directory at ${BUILD_DIR}..."
    mkdir -p "${BUILD_DIR}"
else
    # 如果构建目录已存在，清理现有的CMake缓存和文件，以便可以使用不同的生成器
    echo "Cleaning existing build files at ${BUILD_DIR}..."
    rm -rf "${BUILD_DIR}/CMakeCache.txt" "${BUILD_DIR}/CMakeFiles" "${BUILD_DIR}/build.ninja" "${BUILD_DIR}/Makefile"
fi

# 进入build目录并运行cmake和make
cd "${BUILD_DIR}" || exit 1

# 配置项目
echo "Configuring project with CMake..."
# 检查是否安装了ninja，如果安装了则使用ninja生成器
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

# 构建项目
echo "Building project..."
# 检查是否安装了ninja
if command -v ninja &> /dev/null; then
    echo "Using ninja build system..."
    ninja ieda_py
else
    echo "Using make build system..."
    # 检查make是否可用
    check_command make
    make -j$(nproc) ieda_py  # 使用所有可用的CPU核心构建ieda_py目标
fi
if [ $? -ne 0 ]; then
    echo "Error: Build failed"
    exit 1
fi

echo "ieda_py build completed successfully!"
echo "Environment setup completed successfully!"
echo "To activate the virtual environment in future sessions, run:"
echo "source ${VENV_DIR}/bin/activate"

if [ "$1" == "--release" ]; then
    echo "Starting executable build process..."
    export PYINSTALLER_ONEFILE=1
    # Clean previous builds
    echo "Cleaning previous builds..."
    # 使用绝对路径清理
    rm -rf "${PROJECT_ROOT}/build" "${PROJECT_ROOT}/dist"
    
    # 检查pyinstaller是否可用
    if ! command -v pyinstaller &> /dev/null; then
        echo "Error: pyinstaller is not installed or not in PATH"
        exit 1
    fi
    
    # 检查spec文件是否存在
    if [ ! -f "${PROJECT_ROOT}/chipcompiler.spec" ]; then
        echo "Error: chipcompiler.spec not found at ${PROJECT_ROOT}/chipcompiler.spec"
        exit 1
    fi
    
    # Run pyinstaller via uv
    cd "${PROJECT_ROOT}" || exit 1
    uv run pyinstaller chipcompiler.spec
    if [ $? -ne 0 ]; then
        echo "Error: pyinstaller failed"
        exit 1
    fi
fi