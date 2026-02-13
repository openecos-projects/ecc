#!/usr/bin/env python
import os
import shutil
import subprocess
from pathlib import Path


def _sanitize_loader_env(env: dict[str, str]) -> dict[str, str]:
    """Remove loader-related env vars that can break bundled yosys launcher."""
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    return env


def _build_oss_cad_env(oss_path: Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build subprocess environment variables for OSS CAD Suite."""
    # TODO: Useless in nix build, consider remove this?
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


def _resolve_oss_yosys_paths() -> tuple[str, Path | None, Path | None]:
    """
    Resolve OSS CAD root and expected yosys binary path from environment.
    """
    oss_cad_dir = os.environ.get("CHIPCOMPILER_OSS_CAD_DIR", "").strip()
    if not oss_cad_dir:
        return "", None, None

    oss_path = Path(oss_cad_dir)
    yosys_bin = oss_path / "bin" / ("yosys.exe" if os.name == "nt" else "yosys")
    return oss_cad_dir, oss_path, yosys_bin


def _resolve_yosys_command() -> tuple[list[str], Path | None]:
    """
    Resolve yosys executable from bundled runtime first, then system PATH.

    Returns:
        (command, oss_path):
            - command: list containing executable command or empty list if unavailable
            - oss_path: OSS CAD root path if bundled yosys is selected, else None
    """
    _, oss_path, yosys_bin = _resolve_oss_yosys_paths()
    if oss_path is not None and yosys_bin is not None and yosys_bin.exists():
        return [str(yosys_bin)], oss_path

    if shutil.which("yosys"):
        return ["yosys"], None

    return [], None


def get_yosys_not_found_error() -> str:
    """
    Build a clear error message when yosys cannot be resolved.
    """
    oss_cad_dir, _, yosys_bin = _resolve_oss_yosys_paths()
    if oss_cad_dir and yosys_bin is not None:
        return (
            "Yosys executable not found. "
            f"Checked CHIPCOMPILER_OSS_CAD_DIR='{oss_cad_dir}' "
            f"(expected binary at '{yosys_bin}') and system PATH. "
            "Please install yosys or fix CHIPCOMPILER_OSS_CAD_DIR."
        )

    return (
        "Yosys executable not found in system PATH, and CHIPCOMPILER_OSS_CAD_DIR "
        "is not set. Please install yosys or set CHIPCOMPILER_OSS_CAD_DIR "
        "to the OSS CAD Suite root directory."
    )


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


def check_slang_plugin(
    yosys_cmd: list[str], cwd_dir: str, yosys_env: dict[str, str], log_file, timeout: int = 60
) -> bool:
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
        timeout=timeout,
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
    if get_yosys_command():
        return True

    raise RuntimeError(get_yosys_not_found_error())
