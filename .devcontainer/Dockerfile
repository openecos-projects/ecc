FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

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
    librsvg2-dev

# Install additional dependencies for ECC-Tools build
RUN apt-get install -y \
    build-essential \
    cmake \
    ninja-build \
    tcl-dev \
    libgflags-dev \
    libgoogle-glog-dev \
    libboost-all-dev \
    libgtest-dev \
    flex\
    libeigen3-dev \
    libunwind-dev \
    libmetis-dev \
    libgmp-dev \
    bison \
    rustc \
    cargo \
    libhwloc-dev \
    libcairo2-dev \
    libcurl4-openssl-dev \
    libtbb-dev

# Install Node.js (LTS) and pnpm
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs \
    && npm install -g pnpm \
    && rm -rf /var/lib/apt/lists/*

# Install Rust (for Tauri)
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y \
    && echo 'source $HOME/.cargo/env' >> /etc/profile.d/rust.sh

# Install uv (Python package manager used by project)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv

ENV PATH="/root/.cargo/bin:${PATH}"
ENV PKG_CONFIG_PATH="/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/lib/pkgconfig:/usr/share/pkgconfig"
