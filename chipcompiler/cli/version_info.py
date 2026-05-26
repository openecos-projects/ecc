from importlib import metadata

UNKNOWN_VERSION = "unknown"


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


def root_version_line() -> str:
    return f"ecc {ecc_version()}"
