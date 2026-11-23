"""Read literal primary-clock SDC declarations without executing Tcl."""

import math
import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PrimaryClock:
    target: str
    frequency_mhz: float
    clock_name: str = ""
    source_kind: Literal["auto", "port", "pin"] = "auto"
    waveform: tuple[float, float] | None = None

    @property
    def name(self) -> str:
        if self.clock_name:
            return self.clock_name
        target = self.target
        if "/" in target:
            target = re.sub(r"[/\[.]", "_", target).replace("]", "")
        return f"CLK_{target}"

    @property
    def period(self) -> float:
        return 1000.0 / self.frequency_mhz


# Only literal words are accepted: Tcl substitutions and backslash escapes must
# not be interpreted by the CLI. Braces support literal bus and hierarchy names.
_WORD = r'(?:\{[^{}\\\n]*\}|"[^"$\[\]\\\n]*"|[^\s{}"$\[\]\\;]+)'
_OPTION = re.compile(rf"-(name|period|waveform)\s+({_WORD})\s*")
_DECLARATION = re.compile(
    rf"create_clock\s+(?P<options>(?:-(?:name|period|waveform)\s+{_WORD}\s+)+)"
    rf"\[(?P<query>get_ports|get_pins)\s+(?:-quiet\s+)?(?P<target>{_WORD})\]"
    r"\s*(?:;\s*(?:#.*)?)?"
)


def _literal(word: str) -> str:
    return word[1:-1] if word.startswith(("{", '"')) else word


def _number(value: str) -> float:
    if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
        raise ValueError("Expected a decimal numeric literal")
    return float(value)


def parse_primary_clocks(text: str) -> tuple[PrimaryClock, ...]:
    """Accept one named create_clock per logical line, on one literal port/pin."""
    clocks = []
    names = set()
    targets = set()
    for number, raw in enumerate(re.sub(r"\\\r?\n[ \t]*", " ", text).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        prefix = f"primary_clocks line {number}"
        match = _DECLARATION.fullmatch(line)
        if match is None:
            raise ValueError(
                f"{prefix}: expected create_clock -name NAME -period NS "
                "[-waveform {RISE FALL}] [get_ports PORT] (or get_pins PIN); "
                "use literal values and one command per line, not Tcl expressions"
            )
        options = {}
        for option in _OPTION.finditer(match["options"]):
            key, value = option.groups()
            if key in options:
                raise ValueError(f"{prefix}: duplicate -{key}")
            options[key] = _literal(value)
        if not {"name", "period"} <= options.keys():
            raise ValueError(f"{prefix}: -name and -period are required")
        name = options["name"]
        target = _literal(match["target"])
        if not name or any(char.isspace() for char in name):
            raise ValueError(f"{prefix}: clock name must be one nonempty literal name")
        if not target or any(char.isspace() or char in "*?" for char in target):
            raise ValueError(
                f"{prefix}: target must be one literal port/pin, not a list or wildcard"
            )
        try:
            period = _number(options["period"])
        except ValueError as exc:
            raise ValueError(f"{prefix}: -period must be a finite positive number in ns") from exc
        if not math.isfinite(period) or period <= 0 or not math.isfinite(1000.0 / period):
            raise ValueError(f"{prefix}: -period must be a finite positive number in ns")
        waveform = None
        if "waveform" in options:
            try:
                rise, fall = (_number(edge) for edge in options["waveform"].split())
            except ValueError as exc:
                raise ValueError(f"{prefix}: -waveform requires two numeric edges in ns") from exc
            if not all(math.isfinite(edge) for edge in (rise, fall)) or rise >= fall:
                raise ValueError(f"{prefix}: -waveform edges must be finite and increasing")
            waveform = (rise, fall)
        source_kind = "port" if match["query"] == "get_ports" else "pin"
        if name in names:
            raise ValueError(f"{prefix}: duplicate clock name {name!r}")
        if (source_kind, target) in targets:
            raise ValueError(f"{prefix}: duplicate clock target {target!r}")
        names.add(name)
        targets.add((source_kind, target))
        clocks.append(PrimaryClock(target, 1000.0 / period, name, source_kind, waveform))
    return tuple(clocks)
