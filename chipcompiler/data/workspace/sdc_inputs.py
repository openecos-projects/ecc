"""Parse the five user timing inputs without evaluating user Tcl in Python."""

import math
import re
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class PrimaryClock:
    target: str
    frequency_mhz: float

    @property
    def name(self) -> str:
        target = self.target
        if "/" in target:
            target = re.sub(r"[/\[.]", "_", target).replace("]", "")
        return f"CLK_{target}"


@dataclass(frozen=True)
class SdcInputs:
    clock_list: str = ""
    generated_clock_txt: str = ""
    clk_group_txt: str = ""
    io_constraint_txt: str = ""
    timing_exception_txt: str = ""

    @classmethod
    def from_parameters(cls, parameters: dict) -> "SdcInputs":
        raw = parameters.get("sdc", {})
        if not isinstance(raw, dict):
            raise ValueError("SDC inputs must be a table")
        values = {field.name: raw.get(field.name, "") for field in fields(cls)}
        for name, value in values.items():
            if not isinstance(value, str):
                raise ValueError(f"sdc.{name} must be a string")
        return cls(**values)

    @property
    def has_clock_inputs(self) -> bool:
        return bool(
            parse_clock_list(self.clock_list)
            or self.has_generated_clocks
            or _has_commands(self.clk_group_txt)
        )

    @property
    def has_generated_clocks(self) -> bool:
        return _has_commands(self.generated_clock_txt)

    def clocks(self, parameters: dict, corner: str) -> tuple[PrimaryClock, ...]:
        definitions = parse_clock_list(self.clock_list)
        if not definitions:
            target = parameters.get("clock", "")
            return (
                (PrimaryClock(target, clock_frequency(parameters.get("frequency_max", 100))),)
                if target
                else ()
            )
        clocks = []
        for target, frequencies in definitions.items():
            if corner not in frequencies:
                raise ValueError(f"sdc.clock_list: {target!r} has no frequency for corner {corner}")
            clocks.append(PrimaryClock(target, frequencies[corner]))
        names = [clock.name for clock in clocks]
        if len(set(names)) != len(names):
            raise ValueError("sdc.clock_list: targets produce duplicate clock names")
        return tuple(clocks)


def _has_commands(text: str) -> bool:
    return any(line.strip() and not line.lstrip().startswith("#") for line in text.splitlines())


def clock_frequency(value: object) -> float:
    message = f"Clock frequency must be finite and positive (MHz): {value!r}"
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(message)
    try:
        frequency = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if not math.isfinite(frequency) or frequency <= 0:
        raise ValueError(message)
    return frequency


def parse_clock_list(text: str) -> dict[str, dict[str, float]]:
    """Parse literal port/pin names and complete corner:MHz maps, including decimals."""
    clocks = {}
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.partition("#")[0].strip().rstrip(";").strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"sdc.clock_list line {line_number}: expected target corner:MHz ...")
        target, assignments = parts
        if target in clocks:
            raise ValueError(f"sdc.clock_list line {line_number}: duplicate target {target!r}")
        frequencies = {}
        end = 0
        for match in re.finditer(r"([A-Za-z_]\w*)\s*:\s*([^\s]+)", assignments):
            if assignments[end : match.start()].strip():
                raise ValueError(f"sdc.clock_list line {line_number}: invalid corner:MHz pair")
            corner, value = match.groups()
            if corner in frequencies:
                raise ValueError(f"sdc.clock_list line {line_number}: duplicate corner {corner}")
            frequencies[corner] = clock_frequency(value)
            end = match.end()
        if not frequencies or assignments[end:].strip():
            raise ValueError(f"sdc.clock_list line {line_number}: invalid corner:MHz pair")
        clocks[target] = frequencies
    return clocks
