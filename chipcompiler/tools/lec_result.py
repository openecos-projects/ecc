#!/usr/bin/env python
"""The engine-neutral LEC step mechanics.

Every LEC engine (yosys_lec, kepler_formal, and the lec_dual aggregate)
shares the same netlist identity rules, result JSON contract, and
step-space layout: a ``status`` verdict plus the golden/gate netlist
identities (path, sha256, size). Freshness re-verifies the recorded
identities against the files on disk, so a stale proof can never pass as
current — shared here by the engines and the signoff/analysis consumers
instead of living inside one engine's package.
"""

import json
from pathlib import Path

from chipcompiler.utility import file_digest, json_read

__all__ = [
    "build_lec_step_space",
    "derive_golden_path",
    "lec_result_is_proven",
    "lec_result_status",
    "netlist_fields",
    "optional_path",
    "write_step_result",
]


def optional_path(path: Path | str | None) -> Path | None:
    return Path(path) if path else None


def derive_golden_path(gate_verilog: Path | str | None) -> Path | None:
    """The golden netlist path derived from the gate's ``*_golden`` naming."""
    if not gate_verilog:
        return None
    gate = Path(gate_verilog)
    return gate.with_name(f"{gate.stem}_golden{gate.suffix or '.v'}")


def netlist_fields(path: Path | str | None) -> dict:
    """The result-contract identity fields for one netlist file."""
    digest = file_digest(path)
    return {
        "path": str(path or ""),
        "sha256": digest[0] if digest else "",
        "size_bytes": digest[1] if digest else 0,
    }


def write_step_result(step, *, proven: bool) -> None:
    """Write the engine-neutral LEC result JSON for one engine step."""
    if not step.output.json:
        return
    golden = netlist_fields(step.input.golden_verilog)
    gate = netlist_fields(step.input.gate_verilog)
    payload = {
        "status": "proven" if proven else "incomplete",
        "golden_verilog": golden["path"],
        "gate_verilog": gate["path"],
        "golden_sha256": golden["sha256"],
        "gate_sha256": gate["sha256"],
        "golden_size_bytes": golden["size_bytes"],
        "gate_size_bytes": gate["size_bytes"],
        "equiv_status": str(getattr(step.report, "equiv_status", None) or ""),
        "status_report": str(getattr(step.report, "status", None) or ""),
    }
    Path(step.output.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_lec_step_space(step) -> None:
    """Create every declared directory group of an LEC step."""
    step_directory = Path(step.directory)
    step_directory.mkdir(parents=True, exist_ok=True)
    for group in (step.output, step.data, step.report, step.log, step.script, step.analysis):
        directory = getattr(group, "dir", None)
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)


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
