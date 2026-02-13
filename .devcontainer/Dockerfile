# syntax=docker/dockerfile:1.7

FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04 AS base
SHELL ["/bin/bash", "-lc"]

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git \
    curl \
    ca-certificates \
    build-essential \
    pkg-config \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    libgtk-3-dev \
    libgtk-3-bin \
    libwebkit2gtk-4.1-dev \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf-2.0-dev \
    libglib2.0-dev \
    libglib2.0-bin \
    librsvg2-dev \
    cmake \
    ninja-build \
    tcl-dev \
    libgflags-dev \
    libgoogle-glog-dev \
    libboost-all-dev \
    libgtest-dev \
    flex \
    libeigen3-dev \
    libunwind-dev \
    libmetis-dev \
    libgmp-dev \
    bison \
    libhwloc-dev \
    libcurl4-openssl-dev \
    libtbb-dev \
    patchelf \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (LTS) and pnpm.
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs \
    && npm install -g pnpm \
    && rm -rf /var/lib/apt/lists/*

# Install Rust (for Tauri).
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

# Install uv (Python package manager used by project).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv

ENV PATH="/root/.cargo/bin:${PATH}"
ENV PKG_CONFIG_PATH="/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/lib/pkgconfig:/usr/share/pkgconfig"

FROM base AS devcontainer

FROM base AS runtime
# ENV GITHUB_PROXY_PREFIX="https://ghfast.top/"
# ENV GIT_PROXY_PREFIX="https://ghfast.top/"
# ENV UV_PYTHON_INSTALL_MIRROR="https://ghfast.top/https://github.com/astral-sh/python-build-standalone/releases/download"

WORKDIR /workspace
COPY . /workspace
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    rm -rf .venv \
    && uv sync --frozen --all-groups --python 3.11

RUN cd scripts \
    && source common.sh \
    && setup_project_vars \
    && cd - >/dev/null \
    && source .venv/bin/activate \
    && build_ecc_py \

RUN source .venv/bin/activate \
    && bash ./scripts/autopatch-ecc-py.sh

ENV VIRTUAL_ENV="/workspace/.venv"
ENV PATH="/workspace/.venv/bin:${PATH}"
ENV CHIPCOMPILER_OSS_CAD_DIR="/workspace/chipcompiler/thirdparty/oss-cad-suite"
ENV CHIPCOMPILER_ICS55_PDK_ROOT="/workspace/chip-compiler/chipcompiler/thirdparty/icsprout55-pdk"
RUN echo 'if [ -f /workspace/.venv/bin/activate ]; then source /workspace/.venv/bin/activate; fi' >> /root/.bashrc


# Build commands:
# docker build --target runtime -f .devcontainer/Dockerfile -t ecc:latest .
# docker build --target devcontainer -f .devcontainer/Dockerfile -t chipcompiler-dev .
