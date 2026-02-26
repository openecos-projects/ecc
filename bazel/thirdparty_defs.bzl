"""Third-party Bazel macros for ECC runtime build and packaging."""

load("@rules_shell//shell:sh_binary.bzl", "sh_binary")

def chipcompiler_runtime_bundle(
        name,
        visibility = None,
        ecc_py_cmake = ":ecc_py_cmake",
        autopatch_script = "//bazel/scripts:autopatch_ecc_py_script",
        auto_patchelf_bin = "//bazel/scripts/auto-patchelf:auto_patchelf",
        patchelf = "@patchelf//:bin/patchelf"):
    kwargs = {
        "name": name,
        "srcs": [ecc_py_cmake, autopatch_script, auto_patchelf_bin, patchelf],
        "outs": ["runtime_bundle/runtime_bundle.tar"],
        "tags": ["local", "no-sandbox"],
        "cmd": """
            set -euo pipefail

            BUNDLE="$(@D)/runtime_bundle_stage/chipcompiler/tools/ecc/bin"
            mkdir -p "$$BUNDLE/lib"

            # Derive cmake output root from first location (include/ or lib/ under ecc_py_cmake/)
            for _loc in $(locations {ecc_py_cmake}); do CMAKE_DIR=$$(dirname "$$_loc"); break; done

            # Copy ecc_py .so from cmake output lib/ dir
            find "$$CMAKE_DIR/lib" -name 'ecc_py*.so' -exec cp -f {{}} "$$BUNDLE/" \\;
            chmod u+w "$$BUNDLE"/ecc_py*.so

            # Run autopatch to bundle dependencies and fix RPATHs
            export CHIPCOMPILER_PROJECT_ROOT="$(@D)/runtime_bundle_stage"
            export PATH="$$(dirname $(location {patchelf})):$$PATH"
            export AUTO_PATCHELF_BIN="$(location {auto_patchelf_bin})"
            mkdir -p "$$CHIPCOMPILER_PROJECT_ROOT/chipcompiler/tools/ecc/bin"
            cp -r "$$BUNDLE"/* "$$CHIPCOMPILER_PROJECT_ROOT/chipcompiler/tools/ecc/bin/"
            bash $(location {autopatch_script}) --ecc-py "$$BUNDLE"

            tar -cf $@ -C "$(@D)/runtime_bundle_stage" .
        """.format(
            ecc_py_cmake = ecc_py_cmake,
            autopatch_script = autopatch_script,
            auto_patchelf_bin = auto_patchelf_bin,
            patchelf = patchelf,
        ),
    }
    if visibility != None:
        kwargs["visibility"] = visibility

    native.genrule(**kwargs)

def chipcompiler_install_ecc_runtime(
        name,
        visibility = None,
        script = "//bazel/scripts:install-ecc-runtime.sh",
        ecc_py_cmake = ":ecc_py_cmake",
        autopatch_script = "//bazel/scripts:autopatch_ecc_py_script",
        auto_patchelf_bin = "//bazel/scripts/auto-patchelf:auto_patchelf",
        patchelf = "@patchelf//:bin/patchelf"):
    kwargs = {
        "name": name,
        "srcs": [script],
        "data": [
            ecc_py_cmake,
            autopatch_script,
            auto_patchelf_bin,
            patchelf,
        ],
        "args": [
            "--autopatch-script",
            "$(location {autopatch_script})".format(autopatch_script = autopatch_script),
            "--ecc-py-cmake",
            "$(locations {ecc_py_cmake})".format(ecc_py_cmake = ecc_py_cmake),
            "--auto-patchelf-bin",
            "$(location {auto_patchelf_bin})".format(auto_patchelf_bin = auto_patchelf_bin),
            "--patchelf",
            "$(location {patchelf})".format(patchelf = patchelf),
        ],
    }
    if visibility != None:
        kwargs["visibility"] = visibility

    sh_binary(**kwargs)
