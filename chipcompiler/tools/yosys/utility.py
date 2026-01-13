#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import subprocess
import shutil


def get_yosys_command() -> list[str]:
    """
    Get the yosys command to use.

    First tries 'nix run github:Emin017/ieda-infra#yosysWithSlang',
    falls back to 'yosys' from PATH.
    """
    try:
        result = subprocess.run(
            ["nix", "run", "github:Emin017/ieda-infra#yosysWithSlang", "--", "--version"],
            capture_output=True,
            timeout=600
        )
        if result.returncode == 0:
            return ["nix", "run", "github:Emin017/ieda-infra#yosysWithSlang", "--"]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    if shutil.which("yosys"):
        return ["yosys"]

    return []


def is_eda_exist() -> bool:
    """
    Check if yosys with slang plugin is available.

    First tries 'nix run github:Emin017/ieda-infra#yosysWithSlang -- --version',
    falls back to checking if yosys is in PATH.
    """
    return bool(get_yosys_command())
