"""Parse the five user timing inputs without evaluating user Tcl in Python."""

import math
import re
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .primary_clocks import PrimaryClock, parse_primary_clocks

# Internal workspace parameter: design.frequency_mhz was set explicitly when the
# workspace was created (ecc.toml [params] or --set), on top of the clock list.
EXPLICIT_FREQUENCY_KEY = "_explicit_frequency"
_FREQUENCY_PARAM = "design.frequency_mhz"

# Public file names map to frozen workspace fields at this boundary. Existing
# workspace snapshots still use the old names and corner:MHz clock rows.
_FILE_FIELDS = {
    "primary_clocks": "primary_clocks",
    "generated_clocks": "generated_clock_txt",
    "clock_groups": "clk_group_txt",
    "io_constraints": "io_constraint_txt",
    "timing_exceptions": "timing_exception_txt",
}


@dataclass(frozen=True)
class SdcInputs:
    primary_clocks: str = ""
    clock_list: str = ""
    generated_clock_txt: str = ""
    clk_group_txt: str = ""
    io_constraint_txt: str = ""
    timing_exception_txt: str = ""

    @classmethod
    def from_file(cls, path: str | Path) -> "SdcInputs":
        """Read the five top-level TOML strings; never execute an input as Tcl."""
        path = Path(path)
        required = set(_FILE_FIELDS)
        try:
            with path.open("rb") as stream:
                values = tomllib.load(stream)
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(
                f"Invalid timing input {path}: expected five TOML string fields, not a full "
                "SDC/Tcl script. Put commands in primary_clocks, generated_clocks, clock_groups, "
                "io_constraints and timing_exceptions."
            ) from exc
        if set(values) != required:
            missing = sorted(required - values.keys())
            unknown = sorted(values.keys() - required)
            raise ValueError(
                f"Invalid timing input {path}: expected the five fields at the file root "
                f"(no [params.sdc] table); missing={missing}, unknown={unknown}"
            )
        for name, value in values.items():
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
        inputs = cls(**{_FILE_FIELDS[name]: value for name, value in values.items()})
        inputs.primary_clock()
        return inputs

    def primary_clock(self) -> PrimaryClock:
        clocks = self.clocks({}, "TYP")
        if not clocks:
            raise ValueError("Timing input primary_clocks requires an uncommented create_clock")
        return clocks[0]

    def parameters(self) -> dict:
        """Workspace snapshot and legacy single-clock metadata from one source."""
        primary = self.primary_clock()
        return {
            "sdc": asdict(self),
            "clock": primary.target,
            "frequency_max": primary.frequency_mhz,
        }

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
    def has_primary_clocks(self) -> bool:
        return _has_commands(self.primary_clocks)

    @property
    def has_clock_inputs(self) -> bool:
        return bool(
            self.has_primary_clocks
            or parse_clock_list(self.clock_list)
            or self.has_generated_clocks
            or _has_commands(self.clk_group_txt)
        )

    @property
    def has_generated_clocks(self) -> bool:
        return _has_commands(self.generated_clock_txt)

    def clocks(self, parameters: dict, corner: str) -> tuple[PrimaryClock, ...]:
        if self.has_primary_clocks:
            if parse_clock_list(self.clock_list):
                raise ValueError("Use primary_clocks or legacy clock_list, not both")
            return parse_primary_clocks(self.primary_clocks)
        definitions = parse_clock_list(self.clock_list)
        if not definitions:
            target = parameters.get("clock", "")
            return (
                (PrimaryClock(target, clock_frequency(parameters.get("frequency_max", 100))),)
                if target
                else ()
            )
        clocks = []
        for index, (target, frequencies) in enumerate(definitions.items()):
            if corner not in frequencies:
                raise ValueError(f"sdc.clock_list: {target!r} has no frequency for corner {corner}")
            frequency = frequencies[corner]
            if index == 0:
                frequency = _primary_clock_frequency(frequency, parameters)
            clocks.append(PrimaryClock(target, frequency))
        names = [clock.name for clock in clocks]
        if len(set(names)) != len(names):
            raise ValueError("sdc.clock_list: targets produce duplicate clock names")
        return tuple(clocks)


def frequency_is_explicit(parameters: dict) -> bool:
    """True when ``design.frequency_mhz`` was set on top of the clock list.

    Two records say so: the marker written when the workspace was created with
    an explicit value, and a workspace-scope override of the parameter that
    changes its value. A ``frequency_max`` that merely differs from the list is
    not evidence: it is derived metadata and can be older than the list in
    effect.
    """
    if parameters.get(EXPLICIT_FREQUENCY_KEY) is True:
        return True
    overrides = parameters.get("workspace_param_overrides")
    return isinstance(overrides, list) and any(
        isinstance(item, dict)
        and item.get("key") == _FREQUENCY_PARAM
        and item.get("value") != item.get("baseline")
        for item in overrides
    )


def _primary_clock_frequency(frequency: float, parameters: dict) -> float:
    """The first clock's frequency, following an explicit ``design.frequency_mhz``.

    Synthesis and the summaries read ``frequency_max``. When the user set
    ``design.frequency_mhz`` on top of the clock list, the constraints have to
    describe the same clock, so that value replaces the row's frequency in
    every corner, as it does for a project without a clock list. Otherwise the
    rows of the list decide.
    """
    if not frequency_is_explicit(parameters):
        return frequency
    try:
        return clock_frequency(parameters.get("frequency_max"))
    except ValueError:
        return frequency


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
