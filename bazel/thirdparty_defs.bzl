"""Third-party Bazel macros for ECC runtime build and packaging."""

load("@rules_shell//shell:sh_binary.bzl", "sh_binary")

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
