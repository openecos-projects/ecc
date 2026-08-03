#!/usr/bin/env python
"""Typed path-group layout for workspace steps.

Two real step shapes exist: synthesis (:class:`YosysStep`) and place-and-route
(:class:`EccStep`, reused by ecc/dreamplace/sizer). Each path group has a common
base plus a per-shape variant that adds the tool-specific leaves. The step
classes are frozen so a variant may override a group field with its narrower
type (covariance) without a mutable-field variance error; the group dataclasses
themselves stay mutable so a builder can still populate ``output.spef`` or a
subflow's ``steps`` in place.

The legacy dict key ``"def"`` is a Python keyword, so it is exposed as the
attribute ``def_``.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

# --- input -----------------------------------------------------------------


@dataclass
class StepInput:
    verilog: Path | None = None
    def_: Path | None = None
    db: Path | None = None


# --- output ----------------------------------------------------------------


@dataclass
class OutputPaths:
    dir: Path | None = None
    def_: Path | None = None
    verilog: Path | None = None
    json: Path | None = None
    image: Path | None = None
    # Part of the cross-tool read contract (def/verilog/db): a Path for
    # place-and-route steps, `""` for sizer, and None for synthesis.
    db: Path | str | None = None


@dataclass
class YosysOutput(OutputPaths):
    sim_verilog: Path | None = None
    report: Path | None = None


@dataclass
class EccOutput(OutputPaths):
    gds: Path | None = None
    geometry: Path | None = None
    geometry_manifest: Path | None = None
    view_json: Path | None = None
    view_json_edits: Path | None = None
    lef: Path | None = None
    lib: Path | None = None
    spef: list[Path] = field(default_factory=list)


# --- data ------------------------------------------------------------------


@dataclass
class StepData:
    dir: Path | None = None

    def workdir_for(self, name: str) -> Path | None:
        """Working directory for a step name; overridden by :class:`EccData`."""
        return self.dir

    def iter_directories(self) -> Iterator[Path]:
        """All concrete directories to create; extended by variants."""
        if self.dir is not None:
            yield self.dir


@dataclass
class YosysData(StepData):
    tmp: Path | None = None
    # Synthesis extra: builder-set gate for the slang plugin path.
    requires_slang: bool = True

    def iter_directories(self) -> Iterator[Path]:
        yield from super().iter_directories()
        if self.tmp is not None:
            yield self.tmp


@dataclass
class EccData(StepData):
    # Per-step working directories keyed by step name (StepEnum values, some
    # containing spaces), so they cannot be plain attributes.
    steps: dict[str, Path] = field(default_factory=dict)

    def workdir_for(self, name: str) -> Path | None:
        return self.steps.get(name, self.dir)

    def iter_directories(self) -> Iterator[Path]:
        yield from super().iter_directories()
        yield from self.steps.values()


# --- feature ---------------------------------------------------------------


@dataclass
class StepFeature:
    dir: Path | None = None


@dataclass
class YosysFeature(StepFeature):
    step: Path | None = None
    generic_stat: Path | None = None
    stat: Path | None = None


@dataclass
class EccFeature(StepFeature):
    db: Path | None = None
    step: Path | None = None
    map: Path | None = None
    # STA-at-synthesis QoR roots; nested mapping.
    sta: dict = field(default_factory=dict)


# --- report ----------------------------------------------------------------


@dataclass
class StepReport:
    dir: Path | None = None


@dataclass
class YosysReport(StepReport):
    stat: Path | None = None
    check: Path | None = None


@dataclass
class EccReport(StepReport):
    db: Path | None = None
    step: Path | None = None
    # STA artifact root; nested mapping ({"dir": ...}).
    sta: dict = field(default_factory=dict)


# --- log / script / analysis ----------------------------------------------


@dataclass
class LogPaths:
    dir: Path | None = None
    file: Path | None = None


@dataclass
class ScriptPaths:
    dir: Path | None = None
    main: Path | None = None


@dataclass
class EccScript(ScriptPaths):
    # Sizer extras.
    sizer_env: Path | None = None
    sizer_cmd: Path | None = None


@dataclass
class AnalysisPaths:
    dir: Path | None = None
    metrics: Path | None = None
    # QoR extras.
    qor_metrics: Path | None = None
    qor_summary: Path | None = None
    qor_hotspots: Path | None = None


@dataclass
class EccAnalysis(AnalysisPaths):
    sta_timing_issues: Path | None = None
    # Place-and-route extra.
    statis_csv: Path | None = None


# --- subflow / checklist ---------------------------------------------------


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


@dataclass(frozen=True)
class WorkspaceStepBase:
    """Shared spine for every EDA tool step.

    Frozen so the variants can override a group field with its narrower type;
    the group objects stay mutable for in-place population by the builders.
    """

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


@dataclass(frozen=True)
class YosysStep(WorkspaceStepBase):
    """Synthesis step."""

    output: YosysOutput = field(default_factory=YosysOutput)
    data: YosysData = field(default_factory=YosysData)
    feature: YosysFeature = field(default_factory=YosysFeature)
    report: YosysReport = field(default_factory=YosysReport)


@dataclass(frozen=True)
class EccStep(WorkspaceStepBase):
    """Place-and-route step, shared by ecc, dreamplace and sizer."""

    output: EccOutput = field(default_factory=EccOutput)
    data: EccData = field(default_factory=EccData)
    feature: EccFeature = field(default_factory=EccFeature)
    report: EccReport = field(default_factory=EccReport)
    script: EccScript = field(default_factory=EccScript)
    analysis: EccAnalysis = field(default_factory=EccAnalysis)
