#!/usr/bin/env python
from pathlib import Path

from chipcompiler.tools.yosys.utility import is_eda_exist

__all__ = ["is_eda_exist", "lec_result_is_proven"]


def lec_result_is_proven(path: Path | str | None) -> bool:
    from chipcompiler.utility import json_read

    if not path:
        return False
    data = json_read(path)
    return isinstance(data, dict) and data.get("status") == "proven"
