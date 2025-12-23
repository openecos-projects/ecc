#!/bin/bash

# 设置项目根目录
PROJECT_ROOT=$(cd "$(dirname "$0")";pwd)
VENV_DIR="${PROJECT_ROOT}/.venv"
PYTHON_VERSION="3.10"

# 检查Python 3.10是否可用
if ! command -v python${PYTHON_VERSION} &> /dev/null; then
    echo "Error: Python ${PYTHON_VERSION} is not installed or not in PATH"
    exit 1
fi

# 创建虚拟环境（如果不存在）
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Python ${PYTHON_VERSION} virtual environment at ${VENV_DIR}..."
    python${PYTHON_VERSION} -m venv "${VENV_DIR}"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment"
        exit 1
    fi
    echo "Virtual environment created successfully!"
else
    echo "Virtual environment already exists at ${VENV_DIR}"
fi

# 激活虚拟环境
echo "Activating virtual environment..."
source "${VENV_DIR}/bin/activate"

# 升级pip
echo "Upgrading pip..."
pip install --upgrade pip

# 安装项目依赖
echo "Installing project dependencies..."
# 安装基本依赖
pip install numpy pandas matplotlib scipy

# 安装可能需要的其他依赖
pip install pyjson5 pyyaml

# 如果项目有setup.py，可以使用下面的命令安装项目本身
# pip install -e .

echo "Environment setup completed successfully!"
echo "To activate the virtual environment in future sessions, run:"
echo "source ${VENV_DIR}/bin/activate"
