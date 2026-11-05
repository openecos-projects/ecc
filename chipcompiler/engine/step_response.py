"""Build the ``rsp.json`` a step worker publishes when its step finishes."""

from pathlib import Path

from chipcompiler.data import EccOutput, WorkspaceStep
from chipcompiler.data.flow_check import design_states_after
from chipcompiler.data.types import AnalysisData, DesignData, DesignState, flow_step_policy
from chipcompiler.data.workspace.step_handshake import (
    DesignFiles,
    ResponseStatus,
    StepRequest,
    StepResponse,
    load_response,
)


def build_step_response(
    request: StepRequest, step: WorkspaceStep, *, succeeded: bool
) -> StepResponse:
    """The response for *step*, run from *request*.

    A failed step publishes no design or analysis data, so no downstream step
    can accept its outputs.
    """
    if not succeeded:
        return StepResponse(
            step=request.step,
            tool=request.tool,
            attempt_id=request.attempt_id,
            status=ResponseStatus.FAILED,
            design=DesignFiles(),
            design_states=frozenset(),
            outputs={},
            upstream=request.upstream,
            warnings=frozenset(),
        )
    policy = flow_step_policy(request.step)
    input_states = input_design_states(request)
    # Design states come with the design read; analysis data from an upstream step.
    available: set[DesignData] = {
        *input_states,
        *(item for item in request.upstream if isinstance(item, AnalysisData)),
    }
    return StepResponse(
        step=request.step,
        tool=request.tool,
        attempt_id=request.attempt_id,
        status=ResponseStatus.SUCCESS,
        design=_existing_design_files(step),
        design_states=design_states_after(request.step, input_states),
        outputs=_analysis_outputs(request, step),
        upstream=request.upstream,
        warnings=frozenset(item for item in policy.uses if item not in available),
    )


def input_design_states(request: StepRequest) -> frozenset[DesignState]:
    """The design states of the design the step read.

    They come from the upstream response that supplied the design. A design
    declared by the project, or supplied by a step that ran before responses
    existed, is trusted to carry every design state the step requires or uses.
    """
    source = next(
        (upstream for item, upstream in request.upstream.items() if isinstance(item, DesignState)),
        None,
    )
    if source is not None and source.attempt_id is not None:
        response = load_response(request.workspace_directory / source.step_directory)
        if response is not None and response.attempt_id == source.attempt_id:
            return response.design_states
    policy = flow_step_policy(request.step)
    return frozenset(
        item for item in policy.requires | policy.uses if isinstance(item, DesignState)
    )


def _existing_design_files(step: WorkspaceStep) -> DesignFiles:
    output = step.output
    return DesignFiles(
        def_=_existing(output.def_), verilog=_existing(output.verilog), db=_existing(output.db)
    )


def _existing(path: Path | str | None) -> Path | None:
    return Path(path) if path and Path(path).exists() else None


def _analysis_outputs(
    request: StepRequest, step: WorkspaceStep
) -> dict[AnalysisData, tuple[Path, ...]]:
    outputs: dict[AnalysisData, tuple[Path, ...]] = {}
    for item in flow_step_policy(request.step).provides:
        match item:
            case AnalysisData.PARASITICS if isinstance(step.output, EccOutput):
                outputs[item] = tuple(Path(path) for path in step.output.spef)
            case AnalysisData.GOLDEN_NETLIST:
                golden = getattr(step.output, "golden_verilog", None)
                outputs[item] = (Path(golden),) if golden else ()
            case AnalysisData.POWER:
                from chipcompiler.tools.ecc.power_artifacts import workspace_instance_power_path

                outputs[item] = (workspace_instance_power_path(request.workspace_directory),)
            case _:
                pass
    return outputs
