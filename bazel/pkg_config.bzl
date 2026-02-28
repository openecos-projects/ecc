"""Detect system pkg-config search paths at repo phase."""

def _pkg_config_path_repo_impl(repository_ctx):
    result = repository_ctx.execute(["pkg-config", "--variable", "pc_path", "pkg-config"])
    path = result.stdout.strip() if result.return_code == 0 else ""
    repository_ctx.file("BUILD.bazel", "")
    repository_ctx.file("defs.bzl", 'PKG_CONFIG_PATH = "%s"' % path)

_pkg_config_path_repo = repository_rule(
    implementation = _pkg_config_path_repo_impl,
)

def _pkg_config_ext_impl(module_ctx):
    _pkg_config_path_repo(name = "pkg_config_path")

pkg_config = module_extension(
    implementation = _pkg_config_ext_impl,
)
