"""Whether a step has the design data it requires before its tool runs.

A required design state must be carried by the design the step reads, as its
design source's response publishes it. Required analysis data must be
published by the successful response of the upstream step the request names
or, when no step provides it, come from a project declaration.
"""

from pathlib import Path
from typing import NamedTuple

from chipcompiler.data import StepEnum, WorkspaceStep
from chipcompiler.data.flow_plan import entry_design_states
from chipcompiler.data.handshake.files import load_response
from chipcompiler.data.handshake.messages import ResponseStatus, StepRequest, UpstreamResponse
from chipcompiler.data.step import StepDirectories
from chipcompiler.data.types import AnalysisData, DesignData, DesignState, flow_step_policy


def missing_design_data(
    request: StepRequest, step: WorkspaceStep, *, declared_spef: Path | None
) -> frozenset[DesignData]:
    """Required design data the step has neither from upstream nor declared.

    Design states must be carried by the design the step reads. Analysis data
    must be available as :func:`analysis_available` decides.
    """
    input_states = input_design_states(request)
    missing: set[DesignData] = set()
    for item in flow_step_policy(request.step).requires:
        if isinstance(item, DesignState):
            if item not in input_states:
                missing.add(item)
        elif not analysis_available(request, item, step, declared_spef=declared_spef):
            missing.add(item)
    return frozenset(missing)


def analysis_available(
    request: StepRequest, item: AnalysisData, step: WorkspaceStep, *, declared_spef: Path | None
) -> bool:
    """Whether the step has *item*.

    An upstream step the request names supplies it only through its successful
    response for the accepted run. Without one, parasitics and power fall back
    as :func:`parasitics_source` and :func:`power_source` resolve them, and the
    golden netlist comes from the step's own golden input.
    """
    match item:
        case AnalysisData.PARASITICS:
            return parasitics_source(request, declared_spef=declared_spef) is not None
        case AnalysisData.POWER:
            return power_source(request) is not None
        case AnalysisData.GOLDEN_NETLIST:
            if item in request.upstream:
                return published_upstream(request, item)
            return getattr(step.input, "golden_verilog", None) is not None


class ParasiticsSource(NamedTuple):
    """Where a step reads its parasitics."""

    #: The RCX output directory holding the corner SPEFs; None when the step
    #: reads the project's declared SPEF.
    rcx_output_dir: Path | None


def parasitics_source(
    request: StepRequest, *, declared_spef: Path | None
) -> ParasiticsSource | None:
    """Where the step reads parasitics, or None when it has none.

    An upstream RCX step the request names supplies them only through its
    successful response for the accepted run. Without one, the step reads the
    project's declared SPEF, else the RCX outputs a derived workspace
    inherited from its source.
    """
    link = request.upstream.get(AnalysisData.PARASITICS)
    if link is not None:
        if not published_upstream(request, AnalysisData.PARASITICS):
            return None
        return ParasiticsSource(request.workspace_directory / link.step_directory / "output")
    if declared_spef is not None:
        return ParasiticsSource(None)
    inherited = StepDirectories.at(request.workspace_directory).path(StepEnum.RCX.value)
    if any((inherited / "output").glob("*.spef")):
        return ParasiticsSource(inherited / "output")
    return None


def power_source(request: StepRequest) -> Path | None:
    """The power analysis directory the step reads instance power from, or None.

    An upstream power analysis the request names supplies it only through its
    successful response for the accepted run. Without one, a derived workspace
    reads the power analysis it inherited from its source.
    """
    link = request.upstream.get(AnalysisData.POWER)
    if link is not None:
        if not published_upstream(request, AnalysisData.POWER):
            return None
        return request.workspace_directory / link.step_directory
    from chipcompiler.tools.ecc.power_artifacts import instance_power_path

    inherited = StepDirectories.at(request.workspace_directory).path(StepEnum.POWER_ANALYSIS.value)
    return inherited if instance_power_path(inherited).is_file() else None


def published_upstream(request: StepRequest, item: AnalysisData) -> bool:
    """Whether the upstream step the request names for *item* published it.

    Its response must be the run the request accepted, have succeeded and
    name the files; a step that has not answered published nothing.
    """
    link: UpstreamResponse | None = request.upstream.get(item)
    if link is None:
        return False
    response = load_response(request.workspace_directory / link.step_directory)
    return (
        response is not None
        and response.attempt_id == link.attempt_id
        and response.status is ResponseStatus.SUCCESS
        and bool(response.outputs.get(item))
    )


def input_design_states(request: StepRequest) -> frozenset[DesignState]:
    """The design states of the design the step read.

    They come from the response of the step that supplied the design; a source
    that has not answered for the accepted run carries none. A design declared
    by the project is trusted to carry every design state the step requires or
    uses and, as the flow plan assumes, every state the chain builds before
    the step.
    """
    source = request.design_source
    if source is not None:
        response = load_response(request.workspace_directory / source.step_directory)
        if response is not None and response.attempt_id == source.attempt_id:
            return response.design_states
        return frozenset()
    policy = flow_step_policy(request.step)
    return entry_design_states(request.step) | frozenset(
        item for item in policy.requires | policy.uses if isinstance(item, DesignState)
    )
