from importlib import metadata

UNKNOWN_VERSION = "unknown"
RUNTIME_LABEL = "ECC CLI"
VERSION_SCHEMA = 2
CLI_CONTRACT = 1


def distribution_version(distribution: str, fallback: str | None = None) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return fallback or UNKNOWN_VERSION


def build_identity() -> tuple[str | None, str | None]:
    """Return the (commit, yyyymmdd) pair CI stamps into packaged bundles.

    Source and editable installs have no stamp, so both values are None there.
    """
    try:
        from chipcompiler import _build_info
    except ImportError:
        return None, None
    return _build_info.BUILD_COMMIT, _build_info.BUILD_DATE


def ecc_version() -> str:
    try:
        from chipcompiler import __version__
    except ImportError:
        fallback = None
    else:
        fallback = __version__
    return distribution_version("ecc", fallback=fallback)


def version_payload() -> dict[str, int | str | None]:
    build_commit, build_date = build_identity()
    return {
        "schema_version": VERSION_SCHEMA,
        "runtime": RUNTIME_LABEL,
        "ecc": ecc_version(),
        "dreamplace": distribution_version("ecc-dreamplace"),
        "ecc_tools": distribution_version("ecc-tools-bin"),
        "cli_contract": CLI_CONTRACT,
        "build_commit": build_commit,
        "build_date": build_date,
    }


def root_version_line() -> str:
    return f"ecc {ecc_version()}"


def version_text(payload: dict[str, int | str | None], tools: dict[str, str]) -> str:
    tool_lines = tuple(f"{name} {version}" for name, version in tools.items())
    return "\n".join(
        (
            f"ecc {payload['ecc']}",
            f"dreamplace {payload['dreamplace']}",
            f"ecc_tools {payload['ecc_tools']}",
            f"runtime {payload['runtime']}",
            *tool_lines,
        )
    )
