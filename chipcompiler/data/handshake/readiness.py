"""Whether a step has the design data it requires before its tool runs.

A required design state must be carried by the design the step reads, as its
design source's response publishes it. Required analysis data must be
published by the successful response of the upstream step the request names
or, when no step provides it, come from a project declaration.
"""

from pathlib import Path

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
    must be published by the upstream step the request names; only when no
    step provides it may it come from a project declaration: parasitics from
    ``design.spef`` (or a SPEF wired onto the step), the golden netlist from
    the step's own golden input.
    """
    input_states = input_design_states(request)
    missing: set[DesignData] = set()
    for item in flow_step_policy(request.step).requires:
        if isinstance(item, DesignState):
            if item not in input_states:
                missing.add(item)
        elif item in request.upstream:
            if not _published(request, item):
                missing.add(item)
        elif not _declared(item, request, step, declared_spef):
            missing.add(item)
    return frozenset(missing)


def _published(request: StepRequest, item: AnalysisData) -> bool:
    """Whether the upstream step the request names for *item* published it.

    Its response must be the run the request accepted, have succeeded and
    name the files; a step that has not answered published nothing.
    """
    link: UpstreamResponse = request.upstream[item]
    response = load_response(request.workspace_directory / link.step_directory)
    return (
        response is not None
        and response.attempt_id == link.attempt_id
        and response.status is ResponseStatus.SUCCESS
        and bool(response.outputs.get(item))
    )


def _declared(
    item: AnalysisData, request: StepRequest, step: WorkspaceStep, declared_spef: Path | None
) -> bool:
    match item:
        case AnalysisData.PARASITICS:
            return (
                bool(request.inputs.spef)
                or declared_spef is not None
                or _has_inherited_spef(request.workspace_directory)
            )
        case AnalysisData.GOLDEN_NETLIST:
            return getattr(step.input, "golden_verilog", None) is not None
        case AnalysisData.POWER:
            return False


def _has_inherited_spef(workspace_directory: Path) -> bool:
    """Whether the workspace holds RCX outputs it inherited from a source workspace."""
    output = StepDirectories.at(workspace_directory).path(StepEnum.RCX.value) / "output"
    return output.is_dir() and any(output.glob("*.spef"))


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
