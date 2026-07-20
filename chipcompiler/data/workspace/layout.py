#!/usr/bin/env python
"""Typed path-group layout for workspace steps.

Every EDA tool step shares the same shape of "path groups" (``input``,
``output``, ``data`` ...). Each group is a dataclass with named attributes, and
the step itself is a small hierarchy: a shared :class:`WorkspaceStepBase` plus a
:class:`YosysStep` (synthesis) and an :class:`EccStep` (place-and-route, reused
by ecc/dreamplace/sizer). The two variants differ only by identity, so a group
holds the union of the keys any tool uses for it and cross-tool readers need no
narrowing.

The legacy dict key ``"def"`` is a Python keyword, so it is exposed as the
attribute ``def_``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

# --- path groups shared by every step -------------------------------------

@dataclass
class StepInput:
    verilog: Path | None = None
    def_: Path | None = None
    db: Path | None = None


@dataclass
class OutputPaths:
    # Common across tools.
    dir: Path | None = None
    def_: Path | None = None
    verilog: Path | None = None
    json: Path | None = None
    image: Path | None = None
    # Synthesis extras.
    fixed_verilog: Path | None = None
    report: Path | None = None
    # Place-and-route extras. `db` is `""` for sizer, a Path elsewhere.
    db: Path | str | None = None
    gds: Path | None = None
    view_json: Path | None = None
    view_json_edits: Path | None = None
    lef: Path | None = None
    lib: Path | None = None
    spef: list = field(default_factory=list)


@dataclass
class StepData:
    # Common fixed directories.
    dir: Path | None = None
    tmp: Path | None = None
    # Place-and-route per-step working directories, keyed by step name (StepEnum
    # values, some containing spaces), so they cannot be plain attributes.
    steps: dict[str, Path] = field(default_factory=dict)

    def workdir_for(self, name: str) -> Path | None:
        """Working directory for a step name, falling back to the base dir."""
        return self.steps.get(name, self.dir)

    def iter_directories(self) -> Iterator[Path]:
        """All concrete directories to create (base, tmp, and per-step)."""
        if self.dir is not None:
            yield self.dir
        if self.tmp is not None:
            yield self.tmp
        yield from self.steps.values()


@dataclass
class StepFeature:
    dir: Path | None = None
    # Synthesis extras.
    generic_stat: Path | None = None
    stat: Path | None = None
    # Place-and-route extras.
    db: Path | None = None
    step: Path | None = None
    map: Path | None = None
    timing: Path | None = None


@dataclass
class StepReport:
    dir: Path | None = None
    # Synthesis extras.
    stat: Path | None = None
    check: Path | None = None
    # Place-and-route extras. `sta` is a nested mapping of report paths.
    db: Path | None = None
    step: Path | None = None
    sta: dict = field(default_factory=dict)


@dataclass
class LogPaths:
    dir: Path | None = None
    file: Path | None = None


@dataclass
class ScriptPaths:
    dir: Path | None = None
    main: Path | None = None
    # Sizer extras.
    sizer_env: Path | None = None
    sizer_cmd: Path | None = None


@dataclass
class AnalysisPaths:
    dir: Path | None = None
    metrics: Path | None = None
    # Place-and-route extra.
    statis_csv: Path | None = None


@dataclass
class SubflowState:
    path: Path | None = None
    steps: list = field(default_factory=list)


@dataclass
class ChecklistState:
    path: Path | None = None
    # Holds either the checklist rows (list) or a loaded checklist mapping.
    checklist: list | dict = field(default_factory=list)


# --- step hierarchy --------------------------------------------------------

@dataclass
class WorkspaceStepBase:
    """Shared spine for every EDA tool step."""

    name: str = ""
    directory: Path | None = None
    tool: str = ""
    version: str = ""

    input: StepInput = field(default_factory=StepInput)
    output: OutputPaths = field(default_factory=OutputPaths)
    data: StepData = field(default_factory=StepData)
    feature: StepFeature = field(default_factory=StepFeature)
    report: StepReport = field(default_factory=StepReport)
    log: LogPaths = field(default_factory=LogPaths)
    script: ScriptPaths = field(default_factory=ScriptPaths)
    analysis: AnalysisPaths = field(default_factory=AnalysisPaths)
    subflow: SubflowState = field(default_factory=SubflowState)
    checklist: ChecklistState = field(default_factory=ChecklistState)


@dataclass
class YosysStep(WorkspaceStepBase):
    """Synthesis step."""


@dataclass
class EccStep(WorkspaceStepBase):
    """Place-and-route step, shared by ecc, dreamplace and sizer."""
