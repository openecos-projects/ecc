"""The req/rsp messages a step exchanges with the flow and downstream steps.

Before a step runs, the flow sends it a ``StepRequest``: its input design files,
the step whose design it reads and the upstream step that provided each design
data item it needs. When the step finishes, its worker answers with a
``StepResponse``: the status, the output design files, the design states they
carry and the analysis data produced. Downstream steps read upstream responses.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from chipcompiler.data.types import AnalysisData, DesignData, DesignState


class ResponseStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class UpstreamResponse:
    """An upstream step whose output a step accepts, and the run accepted.

    ``attempt_id`` is None when the upstream step ran before steps wrote
    ``rsp.json``; such an input can never be reported stale.
    """

    step_directory: str
    attempt_id: str | None


@dataclass(frozen=True, slots=True)
class DesignFiles:
    def_: Path | None = None
    verilog: Path | None = None
    db: Path | None = None


@dataclass(frozen=True, slots=True)
class StepInputs:
    design: DesignFiles = DesignFiles()
    golden_verilog: Path | None = None
    spef: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class StepRequest:
    workspace_directory: Path
    step: str
    tool: str
    step_directory: str
    attempt_id: str
    inputs: StepInputs
    #: The step whose output design the step reads; None for a declared design.
    design_source: UpstreamResponse | None
    #: The upstream step that provided each design data item the step needs.
    upstream: Mapping[DesignData, UpstreamResponse]
    final_step: bool
    layout_image: bool

    @property
    def directory(self) -> Path:
        return self.workspace_directory / self.step_directory


@dataclass(frozen=True, slots=True)
class StepResponse:
    step: str
    tool: str
    attempt_id: str
    status: ResponseStatus
    design: DesignFiles
    design_states: frozenset[DesignState]
    outputs: Mapping[AnalysisData, tuple[Path, ...]]
    #: The upstream runs the step accepted, as its request named them.
    design_source: UpstreamResponse | None
    upstream: Mapping[DesignData, UpstreamResponse]
    #: Optional design data the step ran without (its results are degraded).
    warnings: frozenset[DesignData]
