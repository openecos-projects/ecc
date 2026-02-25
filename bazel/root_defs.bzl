"""Root-level Bazel macros for ChipCompiler packaging targets."""

def chipcompiler_api_server_bundle(
        name,
        visibility = None,
        runtime_bundle = "//chipcompiler/thirdparty:runtime_bundle",
        script = "//bazel/scripts:api_server_bundle_script"):
    kwargs = {
        "name": name,
        "srcs": [
            "README.md",
            "pyproject.toml",
            "uv.lock",
            "requirements_lock.txt",
            "chipcompiler.spec",
            "//chipcompiler:chipcompiler_python_sources",
            "//chipcompiler:chipcompiler_runtime_data",
            runtime_bundle,
            script,
        ],
        "outs": ["api_server_bundle/chipcompiler"],
        "cmd": """
            set -euo pipefail

            bash "$(location {script})" \\
                --spec-file "$(location chipcompiler.spec)" \\
                --project-dir "$$(dirname "$(location pyproject.toml)")" \\
                --runtime-bundle-tar "$(location {runtime_bundle})" \\
                --out-bin "$@" \\
                --work-dir "$(@D)/api_server_bundle_work"
        """.format(
            runtime_bundle = runtime_bundle,
            script = script,
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
            script,
        ],
        "outs": ["tauri_bundle/tauri_bundle.tar"],
        "cmd": """
            set -euo pipefail

            bash "$(location {script})" \\
                --gui-src-dir "$$(dirname $(location gui/package.json))" \\
                --api-server-bin "$(location {api_server_bundle})" \\
                --out-tar "$@" \\
                --work-root "$(@D)/tauri_bundle_work"
        """.format(
            api_server_bundle = api_server_bundle,
            script = script,
        ),
    }
    if visibility != None:
        kwargs["visibility"] = visibility

    native.genrule(**kwargs)
