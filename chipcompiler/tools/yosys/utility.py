#!/usr/bin/env python
import logging
import os
import shutil
import subprocess
from pathlib import Path


def _sanitize_loader_env(env: dict[str, str]) -> dict[str, str]:
    """Remove loader-related env vars that can break bundled yosys launcher."""
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    return env


def _build_oss_cad_env(oss_path: Path,
                       base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build subprocess environment variables for OSS CAD Suite."""
    env = dict(base_env) if base_env is not None else os.environ.copy()

    bin_dir = str(oss_path / "bin")
    current_path = env.get("PATH", "")
    if bin_dir not in current_path.split(os.pathsep):
        env["PATH"] = f"{bin_dir}{os.pathsep}{current_path}".rstrip(os.pathsep)

    share_dir = oss_path / "share" / "yosys"
    if (share_dir / "plugins").exists():
        env.setdefault("YOSYS_PLUGINPATH", str(share_dir / "plugins"))
    if (share_dir / "techlibs").exists():
        env.setdefault("YOSYS_DATDIR", str(share_dir))

    return env


def _is_oss_cad_runtime_usable(oss_path: Path) -> bool:
    """Check whether bundled OSS CAD runtime is usable for yosys."""
    if os.name == "nt":
        return True

    # Linux/macOS bundles use a launcher script that depends on runtime files.
    if not (oss_path / "libexec" / "yosys").exists():
        return False

    return (oss_path / "lib").exists()


def _resolve_yosys_command() -> tuple[list[str], Path | None]:
    """
    Resolve yosys executable from bundled runtime first, then system PATH.

    Returns:
        (command, oss_path):
            - command: list containing executable command or empty list if unavailable
            - oss_path: OSS CAD root path if bundled yosys is selected, else None
    """
    if oss_cad_dir := os.environ.get("CHIPCOMPILER_OSS_CAD_DIR"):
        oss_path = Path(oss_cad_dir)
        yosys_bin = oss_path / "bin" / ("yosys.exe" if os.name == "nt" else "yosys")
        if yosys_bin.exists():
            return [str(yosys_bin)], oss_path

    if shutil.which("yosys"):
        return ["yosys"], None

    return [], None


def get_yosys_command() -> list[str]:
    """
    Get the yosys command to use.

    Checks bundled runtime first, then PATH.
    This function is side-effect free and never mutates os.environ.
    """
    command, _ = _resolve_yosys_command()
    return command


def get_yosys_runtime() -> tuple[list[str], dict[str, str]]:
    """
    Get yosys command and subprocess environment.

    Environment variables are only prepared for the subprocess and never
    written to global os.environ.
    """
    command, oss_path = _resolve_yosys_command()
    env = _sanitize_loader_env(os.environ.copy())
    if oss_path is not None:
        env = _build_oss_cad_env(oss_path=oss_path, base_env=env)
    return command, env


def check_slang_plugin(yosys_cmd: list[str],
                       cwd_dir: str,
                       yosys_env: dict[str, str],
                       log_file,
                       timeout: int = 60) -> bool:
    """
    Run a lightweight slang plugin availability check.
    """
    slang_check_cmd = yosys_cmd + ["-p", "plugin -i slang"]
    slang_check_result = subprocess.run(
        slang_check_cmd,
        cwd=cwd_dir,
        env=yosys_env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        timeout=timeout
    )
    if slang_check_result.returncode == 0:
        return True

    error_msg = (
        "Error: yosys slang plugin check failed. "
        "Please use a yosys build with slang plugin support."
    )
    log_file.write(error_msg + "\n")
    print(error_msg)
    return False


def is_eda_exist() -> bool:
    """
    Check if yosys is available via bundled runtime or PATH.
    """
    return bool(get_yosys_command())
