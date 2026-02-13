# GUI Development Guide

This document explains the development environment setup and workflows for the ECOS Studio desktop GUI.

## Overview

ECOS Studio is a high-performance desktop application built with **Tauri + Vue 3 + TypeScript**. It combines Rust's native performance with modern frontend frameworks to provide a smooth chip design experience.

## Tech Stack

- **Desktop Framework**: [Tauri 1.5](https://tauri.app/) (Rust backend)
- **Frontend Framework**: [Vue 3](https://vuejs.org/) (Composition API)
- **Graphics Engine**: [PixiJS 8](https://pixijs.com/) (High-performance WebGL/WebGPU rendering)
- **UI Components**: [PrimeVue 4](https://primevue.org/) (Aura theme)
- **Styling**: [Tailwind CSS v4](https://tailwindcss.com/)
- **Icons**: [Remixicon](https://remixicon.com/) & [PrimeIcons](https://primevue.org/icons)
- **Build Tool**: [Vite 7](https://vitejs.dev/)

## Environment Setup

### 1. Install Node.js and pnpm
- Recommended: [Node.js](https://nodejs.org/) LTS version
- Install [pnpm](https://pnpm.io/): `npm install -g pnpm`

### 2. Install Rust (Required for Tauri)

**macOS/Linux:**
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

**Windows:**
Download `rustup-init.exe` from [rustup.rs](https://rustup.rs/) and run it.

Verify installation: `rustc --version`

### 3. System Dependencies (Required for Tauri)

**macOS:**
```bash
xcode-select --install
```

**Windows:**
- Install [Visual Studio Build Tools 2022](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with "Desktop development with C++"
- Install [WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) (usually pre-installed on Windows 10/11)

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install libwebkit2gtk-4.0-dev build-essential curl wget file libssl-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev
```

## Quick Start

### Install Dependencies
```bash
cd gui
pnpm install
```

### Development
```bash
# Run frontend and Tauri backend (recommended)
pnpm run tauri:dev

# Run frontend only in browser
pnpm run dev
```

### Build
```bash
# Generate platform-specific installers (dmg, exe, deb, AppImage, etc.)
pnpm run tauri:build
```

## Project Structure

```text
gui/
├── src/                    # Frontend code (Vue/TypeScript)
│   ├── applications/       # Core application logic (Editor, PixiJS rendering)
│   ├── components/         # UI components
│   ├── composables/        # Composition functions (Workspace, EDA, Menu)
│   ├── stores/             # Pinia state management
│   └── styles/             # Global styles (Tailwind)
├── src-tauri/              # Backend code (Rust)
│   ├── src/                # Rust source code
│   └── tauri.conf.json     # Tauri configuration
├── public/                 # Static assets (images, thumbnails)
├── index.html              # Entry file
└── package.json            # Dependencies
```

## Core Features

- **High-Performance Canvas** - PixiJS-based drawing workspace with rulers
- **Layout Management** - Thumbnail gallery display
- **Theme Support** - Modern UI with Aura theme
- **Project Management** - Create, open projects, and track recent projects

## Development Guide

### Using Components (PrimeVue)
```vue
<script setup lang="ts">
import Button from 'primevue/button'
</script>

<template>
  <Button label="Confirm" icon="pi pi-check" />
</template>
```

### Using Icons
- **PrimeIcons**: `<i class="pi pi-search"></i>`
- **Remixicon**: `<i class="ri-settings-line"></i>`

### State Management
- Use **Pinia** for global state management (see `src/stores/`)
- Business logic encapsulated in `src/composables/`

### Backend Communication
The GUI communicates with the ChipCompiler Python backend via REST API (default port 8765):
- API endpoints defined in `chipcompiler/services/routers/`
- CORS configured for Tauri dev server (port 1420) and Vite dev server (port 5173)
- API can be spawned by Tauri at application startup

### Hot Reload
- Frontend changes hot-reload automatically in dev mode
- Backend changes require restart (or use `chipcompiler --reload`)

## Building for Distribution

### AppImage (Linux)
```bash
pnpm run tauri:build
```
Output: `src-tauri/target/release/bundle/appimage/`

### Other Platforms
- **macOS**: Generates `.dmg` and `.app`
- **Windows**: Generates `.exe` and `.msi`
- **Linux**: Generates `.deb`, `.rpm`, and `.AppImage`

## Related Documentation

- [Architecture](architecture.md) - System design and patterns
- [Development Guide](development.md) - Complete development setup
- [API Guide](api-guide.md) - REST API reference
