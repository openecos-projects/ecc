"""Root-level Bazel macros for ChipCompiler packaging targets."""

def chipcompiler_api_server_bundle(
        name,
        visibility = None,
        runtime_bundle = "//chipcompiler/thirdparty:ecc_bundle",
        pyinstaller = "//bazel:pyinstaller"):
    kwargs = {
        "name": name,
        "srcs": [
            "README.md",
            "pyproject.toml",
            "uv.lock",
            "requirements_lock.txt",
            "ecc.spec",
            "//chipcompiler:chipcompiler_python_sources",
            "//chipcompiler:chipcompiler_runtime_data",
            runtime_bundle,
        ],
        "tools": [pyinstaller],
        "outs": ["api_server_bundle/chipcompiler"],
        # Use local execution for PyInstaller's introspection needs
        "tags": ["local", "no-sandbox"],
        "cmd": """
            set -euo pipefail

            # Find workspace root from a known source file
            WORKSPACE_ROOT=$$(dirname $$(realpath $(location pyproject.toml)))

            tar -xf $(location {runtime_bundle}) -C .
            $(location {pyinstaller}) $(location ecc.spec) \
                --clean \
                --noconfirm \
                --distpath "$(@D)/api_server_bundle" \
                --workpath "$(@D)/api_server_bundle_work"

            if [ ! -f "$@" ]; then
                echo "ERROR: expected output not found at $@" >&2
                find "$(@D)/api_server_bundle" -maxdepth 3 -type f | sort >&2
                exit 1
            fi
        """.format(
            runtime_bundle = runtime_bundle,
            pyinstaller = pyinstaller,
        ),
    }
    if visibility != None:
        kwargs["visibility"] = visibility

    native.genrule(**kwargs)

def chipcompiler_tauri_bundle(
        name,
        visibility = None,
        api_server_bundle = ":api_server_bundle",
        rust_sources = "//gui/src-tauri:tauri_rust_sources",
        appimagetool_bin = "@appimagetool_x86_64_linux//file",
        oss_cad_files = "@oss_cad_suite//:all_files",
        oss_cad_yosys_bin = "@oss_cad_suite//:yosys_bin",
        script = "//bazel/scripts:build_tauri_bundle_script"):
    kwargs = {
        "name": name,
        "srcs": native.glob([
            "gui/src/**/*",
            "gui/public/**/*",
            "gui/index.html",
            "gui/package.json",
            "gui/pnpm-lock.yaml",
            "gui/tsconfig*.json",
            "gui/vite.config.ts",
            "gui/tailwind.config.ts",
        ]) + [
            rust_sources,
            api_server_bundle,
            appimagetool_bin,
            oss_cad_files,
            oss_cad_yosys_bin,
            script,
        ],
        "outs": ["tauri_bundle/tauri_bundle.tar"],
        "cmd": """
            set -euo pipefail

            bash "$(location {script})" \\
                --gui-src-dir "$$(dirname $(location gui/package.json))" \\
                --api-server-bin "$(location {api_server_bundle})" \\
                --appimagetool-bin "$(location {appimagetool_bin})" \\
                --oss-cad-bin "$(location {oss_cad_yosys_bin})" \\
                --out-tar "$@" \\
                --work-root "$(@D)/tauri_bundle_work"
        """.format(
            api_server_bundle = api_server_bundle,
            appimagetool_bin = appimagetool_bin,
            oss_cad_yosys_bin = oss_cad_yosys_bin,
            script = script,
        ),
    }
    if visibility != None:
        kwargs["visibility"] = visibility

    native.genrule(**kwargs)
