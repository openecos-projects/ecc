#!/usr/bin/env python
import shutil


def get_yosys_command() -> list[str]:
    """
    Get the yosys command to use.

    Checks if 'yosys' is available in PATH (from nix develop, OSS CAD Suite, or system install).
    """
    if shutil.which("yosys"):
        return ["yosys"]

    return []


def is_eda_exist() -> bool:
    """
    Check if yosys is available in PATH.
    """
    return bool(get_yosys_command())
