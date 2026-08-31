#!/usr/bin/env python
from pathlib import Path

from chipcompiler.tools.yosys.utility import is_eda_exist
from chipcompiler.utility import file_digest

__all__ = [
    "is_eda_exist",
    "lec_result_is_proven",
    "lec_result_status",
]


def lec_result_status(
    path: Path | str | None,
    *,
    golden_verilog: Path | str | None = None,
    gate_verilog: Path | str | None = None,
) -> str:
    from chipcompiler.utility import json_read

    if not path or not Path(path).is_file():
        return "missing"
    data = json_read(path)
    if not isinstance(data, dict) or data.get("status") != "proven":
        return "incomplete"
    if not _netlist_is_current(data, "golden", golden_verilog):
        return "stale"
    if not _netlist_is_current(data, "gate", gate_verilog):
        return "stale"
    return "proven"


def lec_result_is_proven(
    path: Path | str | None,
    *,
    golden_verilog: Path | str | None = None,
    gate_verilog: Path | str | None = None,
) -> bool:
    return (
        lec_result_status(
            path,
            golden_verilog=golden_verilog,
            gate_verilog=gate_verilog,
        )
        == "proven"
    )


def _netlist_is_current(
    data: dict,
    role: str,
    expected_path: Path | str | None,
) -> bool:
    recorded_path = data.get(f"{role}_verilog")
    recorded_sha = data.get(f"{role}_sha256")
    recorded_size = data.get(f"{role}_size_bytes")
    if not recorded_path or not recorded_sha:
        return False
    if expected_path and not _same_path(recorded_path, expected_path):
        return False
    digest = file_digest(recorded_path)
    if digest is None:
        return False
    sha256, size_bytes = digest
    if sha256 != recorded_sha:
        return False
    return recorded_size is None or recorded_size == size_bytes


def _same_path(left: Path | str, right: Path | str) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return False
