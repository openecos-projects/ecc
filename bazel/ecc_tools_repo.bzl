"""Repository rule to import ecc-tools sources without conflicting BUILD/WORKSPACE files.

ecc-tools/src/third_party contains vendored libraries (abseil-cpp, yaml-cpp, etc.)
that ship their own BUILD.bazel and WORKSPACE files. These conflict with the main
workspace, so they are listed in .bazelignore — which also prevents Bazel's glob
from seeing the source files that rules_foreign_cc cmake() needs.

This rule copies the source tree while stripping BUILD/WORKSPACE files, producing
a clean repository that cmake() can consume via lib_source.
"""

def _ecc_tools_sources_impl(ctx):
    workspace_root = ctx.path(Label("@//:MODULE.bazel")).dirname
    src = ctx.path(str(workspace_root) + "/" + ctx.attr.path)
    ctx.execute(
        ["bash", "-c", """
            set -euo pipefail
            cp -a "{src}/." .
            find . -type f \\( \
                -name BUILD \
                -o -name BUILD.bazel \
                -o -name WORKSPACE \
                -o -name WORKSPACE.bazel \
            \\) -delete
            # Remove files with non-printable chars in names (Bazel label restriction).
            find . -type f | LC_ALL=C grep '[^[:print:]/]' | while IFS= read -r f; do
                rm -f "$f"
            done
        """.format(src = str(src))],
        quiet = False,
    )
    ctx.template(
        "BUILD.bazel",
        Label("//bazel:ecc_tools_repo.BUILD.bazel"),
        substitutions = {},
    )

ecc_tools_sources = repository_rule(
    implementation = _ecc_tools_sources_impl,
    attrs = {
        "path": attr.string(
            mandatory = True,
            doc = "Workspace-relative path to the ecc-tools directory.",
        ),
    },
    local = True,
    doc = "Imports ecc-tools sources, stripping BUILD/WORKSPACE files for cmake() compatibility.",
)
