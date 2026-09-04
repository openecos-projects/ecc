"""Resolved environment tool versions for `ecc version`.

Unlike the bundle versions in :mod:`chipcompiler.cli.core.version_info`
(pure package metadata), these helpers resolve each tool the way the flow
does and query the binary, so the output reflects the environment actually
in use. Tools that cannot report a version still report their presence.
"""

import subprocess

NOT_INSTALLED = "not installed"
UNKNOWN = "unknown"
VERSION_QUERY_TIMEOUT = 5


def _query(
    command: list[str], env: dict[str, str] | None = None, *, tolerate_exit: bool = False
) -> str:
    """Run a version query; return its trimmed output, or "" on any failure.

    tolerate_exit keeps the output of a tool that prints its version and then
    exits non-zero (ecc-sizer's OpenROAD binary prints a usage error after
    "OpenROAD vX" with exit code 1).
    """
    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=VERSION_QUERY_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0 and not tolerate_exit:
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


def yosys_version() -> str:
    from chipcompiler.tools.yosys.utility import get_yosys_command, get_yosys_runtime

    if not get_yosys_command():
        return NOT_INSTALLED
    yosys_cmd, yosys_env = get_yosys_runtime()
    output = _query(yosys_cmd + ["-V"], yosys_env)
    if not output:
        return UNKNOWN
    # "Yosys 0.68+132 (git sha1 ...)" -> "0.68+132"
    parts = output.split()
    if parts[0] == "Yosys" and len(parts) > 1:
        return parts[1]
    return output


def sizer_version() -> str:
    from chipcompiler.tools.ecc_sizer.utility import get_sizer_command

    command = get_sizer_command()
    if not command:
        return NOT_INSTALLED
    # Best-effort: ecc-sizer has no committed version protocol. The OpenROAD
    # binary prints "OpenROAD vX.Y.Z" followed by a usage error (exit 1), so
    # the exit code is tolerated and the version line is parsed out.
    output = _query(command + ["--version"], tolerate_exit=True)
    if not output:
        return UNKNOWN
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("OpenROAD v"):
            version = stripped.removeprefix("OpenROAD v").strip()
            if version:
                return version
    return output.splitlines()[0].strip()


def klayout_version() -> str:
    from chipcompiler.cli.core.version_info import distribution_version
    from chipcompiler.tools.klayout_tool.utility import is_eda_exist

    if not is_eda_exist():
        return NOT_INSTALLED
    return distribution_version("klayout")


def tool_versions() -> dict[str, str]:
    return {
        "yosys": yosys_version(),
        "sizer": sizer_version(),
        "klayout": klayout_version(),
    }
