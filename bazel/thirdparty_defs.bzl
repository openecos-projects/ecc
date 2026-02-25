"""Third-party Bazel macros for ECC runtime build and packaging."""

load("@rules_shell//shell:sh_binary.bzl", "sh_binary")

def chipcompiler_ecc_py_build_artifacts(
        name,
        visibility = None,
        script = "//bazel/scripts:ecc_py_build_artifacts_script"):
    kwargs = {
        "name": name,
        "srcs": native.glob(
            [
                "ecc-tools/cmake/**/*.cmake",
                "ecc-tools/src/**/CMakeLists.txt",
                "ecc-tools/src/**/*.c",
                "ecc-tools/src/**/*.cc",
                "ecc-tools/src/**/*.cpp",
                "ecc-tools/src/**/*.cxx",
                "ecc-tools/src/**/*.h",
                "ecc-tools/src/**/*.hh",
                "ecc-tools/src/**/*.hpp",
                "ecc-tools/CMakeLists.txt",
            ],
            allow_empty = True,
        ) + [script],
        "outs": [
            "ecc_py_build/ecc_py.so",
            "ecc_py_build/runtime_roots.tar",
        ],
        "cmd": """
            set -euo pipefail

            bash "$(location {script})" \\
                --src-root "$$(dirname "$$(readlink -f "$(location ecc-tools/CMakeLists.txt)")")" \\
                --rule-out-root "$(RULEDIR)"
        """.format(
            script = script,
        ),
    }
    if visibility != None:
        kwargs["visibility"] = visibility

    native.genrule(**kwargs)

def chipcompiler_runtime_bundle(
        name,
        visibility = None,
        ecc_py_raw = ":ecc_py_raw",
        ecc_runtime_roots_tar = ":ecc_runtime_roots_tar",
        runtime_bundle_script = "//bazel/scripts:runtime_bundle_script",
        autopatch_script = "//bazel/scripts:autopatch_ecc_py_script",
        autopatch_runtime = "//bazel/scripts:autopatch_ecc_py"):
    kwargs = {
        "name": name,
        "srcs": [
            ecc_py_raw,
            ecc_runtime_roots_tar,
            runtime_bundle_script,
            autopatch_script,
            autopatch_runtime,
        ],
        "outs": ["runtime_bundle/runtime_bundle.tar"],
        "cmd": """
            set -euo pipefail

            bash "$(location {runtime_bundle_script})" \\
                --autopatch-script "$(location {autopatch_script})" \\
                --ecc-py "$(location {ecc_py_raw})" \\
                --runtime-roots-tar "$(location {ecc_runtime_roots_tar})" \\
                --out-tar "$@" \\
                --bundle-stage-dir "$(@D)/runtime_bundle_stage"
        """.format(
            runtime_bundle_script = runtime_bundle_script,
            autopatch_script = autopatch_script,
            ecc_py_raw = ecc_py_raw,
            ecc_runtime_roots_tar = ecc_runtime_roots_tar,
        ),
    }
    if visibility != None:
        kwargs["visibility"] = visibility

    native.genrule(**kwargs)

def chipcompiler_install_ecc_runtime(
        name,
        visibility = None,
        script = "//bazel/scripts:install-ecc-runtime.sh",
        ecc_py_raw = ":ecc_py_raw",
        ecc_runtime_roots_tar = ":ecc_runtime_roots_tar",
        autopatch_script = "//bazel/scripts:autopatch_ecc_py_script",
        autopatch_runtime = "//bazel/scripts:autopatch_ecc_py"):
    kwargs = {
        "name": name,
        "srcs": [script],
        "data": [
            ecc_py_raw,
            ecc_runtime_roots_tar,
            autopatch_script,
            autopatch_runtime,
        ],
        "args": [
            "--autopatch-script",
            "$(location {autopatch_script})".format(autopatch_script = autopatch_script),
            "--ecc-py",
            "$(location {ecc_py_raw})".format(ecc_py_raw = ecc_py_raw),
            "--runtime-roots-tar",
            "$(location {ecc_runtime_roots_tar})".format(ecc_runtime_roots_tar = ecc_runtime_roots_tar),
        ],
    }
    if visibility != None:
        kwargs["visibility"] = visibility

    sh_binary(**kwargs)
