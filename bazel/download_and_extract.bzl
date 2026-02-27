"""Generic repository rule for downloading archives and running post-setup commands.

This rule simplifies external dependency management by:
- Downloading and extracting archives (tar.gz, tar.bz2, tgz, zip, etc.)
- Running optional post-setup commands (e.g., make, configure)
- Generating BUILD files from templates or inline content

Example usage:
    # Simple download with inline BUILD
    download_and_extract(
        name = "patchelf",
        urls = ["https://github.com/.../patchelf-0.18.0.tar.gz"],
        sha256 = "ce84f244...",
        build_file_content = '''exports_files(["bin/patchelf"])''',
    )

    # With post-setup and BUILD template
    download_and_extract(
        name = "icsprout55_pdk",
        urls = ["https://github.com/.../icsprout55-pdk.tar.gz"],
        strip_prefix = "icsprout55-pdk-abc123",
        sha256 = "87f31b0d...",
        post_setup_cmds = ["make unzip"],
        environment = {"TOOL": "curl"},
        build_file_template = "//bazel:pdk.BUILD.bazel",
    )
"""

def _download_and_extract_impl(ctx):
    # Download and extract
    ctx.download_and_extract(
        url = ctx.attr.urls,
        sha256 = ctx.attr.sha256,
        stripPrefix = ctx.attr.strip_prefix,
    )

    # Run post-setup commands if provided
    for cmd in ctx.attr.post_setup_cmds:
        result = ctx.execute(["bash", "-c", cmd], environment = ctx.attr.environment)
        if result.return_code != 0:
            fail("Command failed: {}\n{}".format(cmd, result.stderr))

    # Create BUILD file
    if ctx.attr.build_file_template:
        ctx.template("BUILD.bazel", ctx.attr.build_file_template, substitutions = {})
    elif ctx.attr.build_file_content:
        ctx.file("BUILD.bazel", ctx.attr.build_file_content)

download_and_extract = repository_rule(
    implementation = _download_and_extract_impl,
    attrs = {
        "urls": attr.string_list(
            mandatory = True,
            doc = "List of mirror URLs to download the archive from.",
        ),
        "sha256": attr.string(
            mandatory = True,
            doc = "Expected SHA256 checksum of the archive.",
        ),
        "strip_prefix": attr.string(
            default = "",
            doc = "Directory prefix to strip after extraction (e.g., 'pkg-1.0.0').",
        ),
        "post_setup_cmds": attr.string_list(
            default = [],
            doc = "Shell commands to run after extraction (e.g., ['make unzip']).",
        ),
        "environment": attr.string_dict(
            default = {},
            doc = "Environment variables for post-setup commands.",
        ),
        "build_file_template": attr.label(
            doc = "Label to BUILD.bazel template file.",
        ),
        "build_file_content": attr.string(
            doc = "Inline BUILD.bazel content (alternative to build_file_template).",
        ),
    },
    doc = "Downloads and extracts an archive, optionally runs setup commands, and creates a BUILD file.",
)
