"""Build the response a step worker publishes when its step finishes."""

from pathlib import Path

from chipcompiler.data import EccOutput, WorkspaceStep
from chipcompiler.data.flow_check import design_states_after
from chipcompiler.data.handshake.messages import (
    DesignFiles,
    ResponseStatus,
    StepRequest,
    StepResponse,
)
from chipcompiler.data.handshake.readiness import input_design_states
from chipcompiler.data.types import AnalysisData, DesignData, flow_step_policy


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
            design_source=request.design_source,
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
        design_source=request.design_source,
        upstream=request.upstream,
        warnings=frozenset(item for item in policy.uses if item not in available),
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
                from chipcompiler.tools.ecc.power_artifacts import instance_power_path

                outputs[item] = (instance_power_path(request.directory),)
            case _:
                pass
    return outputs
