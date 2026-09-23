#!/usr/bin/env python
"""The engine-neutral LEC result contract.

Every LEC engine (yosys_lec, kepler_formal, and the lec_dual aggregate)
writes the same result JSON: a ``status`` verdict plus the golden/gate
netlist identities (path, sha256, size). Freshness re-verifies the
recorded identities against the files on disk, so a stale proof can never
pass as current — shared here by the engines and the signoff/analysis
consumers instead of living inside one engine's package.
"""

from pathlib import Path

from chipcompiler.utility import file_digest, json_read

__all__ = [
    "lec_result_is_proven",
    "lec_result_status",
    "netlist_fields",
]


def netlist_fields(path: Path | str | None) -> dict:
    """The result-contract identity fields for one netlist file."""
    digest = file_digest(path)
    return {
        "path": str(path or ""),
        "sha256": digest[0] if digest else "",
        "size_bytes": digest[1] if digest else 0,
    }


def lec_result_status(
    path: Path | str | None,
    *,
    golden_verilog: Path | str | None = None,
    gate_verilog: Path | str | None = None,
) -> str:
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
    if not recorded_path or not recorded_sha or type(recorded_size) is not int:
        return False
    if expected_path and not _same_path(recorded_path, expected_path):
        return False
    digest = file_digest(recorded_path)
    if digest is None:
        return False
    sha256, size_bytes = digest
    return sha256 == recorded_sha and recorded_size == size_bytes


def _same_path(left: Path | str, right: Path | str) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return False
