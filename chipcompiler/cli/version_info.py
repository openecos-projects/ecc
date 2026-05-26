from importlib import metadata

UNKNOWN_VERSION = "unknown"
RUNTIME_LABEL = "ECC CLI"
VERSION_SCHEMA = 1

def distribution_version(distribution: str, fallback: str | None = None) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return fallback or UNKNOWN_VERSION


def ecc_version() -> str:
    try:
        from chipcompiler import __version__
    except ImportError:
        fallback = None
    else:
        fallback = __version__
    return distribution_version("ecc", fallback=fallback)


def version_payload() -> dict[str, int | str]:
    return {
        "schema_version": VERSION_SCHEMA,
        "runtime": RUNTIME_LABEL,
        "ecc": ecc_version(),
        "dreamplace": distribution_version("ecc-dreamplace"),
        "ecc_tools": distribution_version("ecc-tools"),
    }


def root_version_line() -> str:
    return f"ecc {ecc_version()}"


def version_text(payload: dict[str, int | str]) -> str:
    return "\n".join(
        (
            f"ecc {payload['ecc']}",
            f"dreamplace {payload['dreamplace']}",
            f"ecc_tools {payload['ecc_tools']}",
            f"runtime {payload['runtime']}",
        )
    )
