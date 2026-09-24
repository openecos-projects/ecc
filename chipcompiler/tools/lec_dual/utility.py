"""Engine availability probing and verdict merging for the dual LEC step."""

import json
from dataclasses import dataclass
from pathlib import Path

from chipcompiler.data import LECEngineEnum
from chipcompiler.tools.lec_result import netlist_fields
from chipcompiler.utility import json_read


def engine_availability(engine: LECEngineEnum) -> tuple[bool, str]:
    """(available, reason) for one physical engine — never raises."""
    if engine is LECEngineEnum.YOSYS_LEC:
        from chipcompiler.tools.yosys.utility import (
            get_yosys_command,
            get_yosys_not_found_error,
        )

        if get_yosys_command():
            return True, ""
        return False, get_yosys_not_found_error()
    if engine is LECEngineEnum.KEPLER_FORMAL:
        from chipcompiler.tools.kepler_formal.utility import (
            get_kepler_formal_command,
            get_kepler_formal_not_found_error,
        )

        if get_kepler_formal_command():
            return True, ""
        return False, get_kepler_formal_not_found_error()
    raise ValueError("lec_dual is a composite; probe its spawn engines instead")


def is_eda_exist() -> bool:
    """At least one physical engine must be available (degraded mode)."""
    probed = [engine_availability(engine) for engine in LECEngineEnum.DUAL.spawn_engines]
    if any(available for available, _reason in probed):
        return True
    missing = [reason for available, reason in probed if not available]
    raise RuntimeError("lec_dual needs at least one LEC engine: " + "; ".join(missing))


@dataclass
class EngineOutcome:
    """One physical engine's outcome inside a dual run."""

    engine: LECEngineEnum
    available: bool
    reason: str = ""  # why the engine could not run (unavailable only)
    succeeded: bool = False  # engine run_step returned True
    error: str = ""  # engine raised instead of returning
    result: dict | None = None  # parsed result JSON (None: missing/unparseable)

    @property
    def status(self) -> str:
        if not self.available:
            return "unavailable"
        if (
            self.succeeded
            and not self.error
            and isinstance(self.result, dict)
            and self.result.get("status") == "proven"
        ):
            return "proven"
        return "incomplete"

    def record(self) -> dict:
        """The engines-map entry for the aggregate result JSON."""
        if not self.available:
            return {"status": "unavailable", "reason": self.reason}
        entry = dict(self.result) if isinstance(self.result, dict) else {"status": "incomplete"}
        if self.error:
            entry["error"] = self.error
        return entry


def read_engine_result(path: Path | str | None) -> dict | None:
    """The parsed per-engine result JSON, or None when missing/unparseable.

    json_read collapses read/parse failures to ``{}``, so only a payload
    carrying the contract's ``status`` key counts as parseable evidence.
    """
    if not path or not Path(path).is_file():
        return None
    data = json_read(path)
    if not isinstance(data, dict) or "status" not in data:
        return None
    return data


def merge_outcomes(
    outcomes: list[EngineOutcome],
    *,
    golden_verilog: Path | str | None,
    gate_verilog: Path | str | None,
) -> dict:
    """The aggregate result payload over the shared logical inputs.

    Conservative: the aggregate is ``proven`` only when every engine
    proved; ``agreement`` is tri-state — None when any engine's result is
    missing or unparseable, else whether the two recorded status fields
    match. The top-level digest fields keep the single-engine result
    contract so freshness checks and the signoff gate read it unchanged.
    """
    golden = netlist_fields(golden_verilog)
    gate = netlist_fields(gate_verilog)
    proven = bool(outcomes) and all(outcome.status == "proven" for outcome in outcomes)
    if any(outcome.result is None for outcome in outcomes):
        agreement = None
    else:
        agreement = len({str(outcome.result.get("status")) for outcome in outcomes}) == 1
    payload = {
        "status": "proven" if proven else "incomplete",
        "golden_verilog": golden["path"],
        "gate_verilog": gate["path"],
        "golden_sha256": golden["sha256"],
        "gate_sha256": gate["sha256"],
        "golden_size_bytes": golden["size_bytes"],
        "gate_size_bytes": gate["size_bytes"],
        "engines": {outcome.engine.value: outcome.record() for outcome in outcomes},
        "agreement": agreement,
    }
    if agreement is False:
        # A disagreement usually means modeling differences, not a real
        # bug; the record states the prep difference so triage does not
        # restart from zero.
        payload["disagreement_note"] = (
            "The engines preprocess inputs differently: kepler_formal strips "
            "physical cells in netlist_prep while yosys_lec compares the raw "
            "netlists. Triage the verdict difference there first."
        )
    return payload


def write_aggregate_result(path: Path | str, payload: dict) -> None:
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
