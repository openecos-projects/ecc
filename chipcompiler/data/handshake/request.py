"""Turn the flow's step wiring into the ``req.json`` a step worker runs from.

The flow still plans steps from its ledger. Everything the worker needs from
that plan travels in the request: its input files, the step whose design it
reads, the upstream step that provided each design data item it needs, and
whether it is the final step.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from chipcompiler.data import LEC_STEP_TOOLS, EccOutput, LecInput, StepEnum, WorkspaceStep
from chipcompiler.data.flow_check import step_provides
from chipcompiler.data.handshake.files import load_response
from chipcompiler.data.handshake.messages import (
    DesignFiles,
    StepInputs,
    StepRequest,
    UpstreamResponse,
)
from chipcompiler.data.step import recorded_step_directory
from chipcompiler.data.types import DesignData, flow_step_policy
from chipcompiler.data.workspace.flow_policy import FlowInputResolver


def build_step_request(
    workspace_directory: Path,
    records: Sequence[Mapping[str, object]],
    workspace_step: WorkspaceStep,
    *,
    attempt_id: str,
    layout_image: bool,
) -> StepRequest:
    """The request for *workspace_step*, wired as the ledger *records* plan it."""
    inputs = step_inputs(workspace_step)
    directory = workspace_step.directory
    if directory is None or Path(directory).parent != workspace_directory:
        raise ValueError(
            f"{workspace_step.name} step directory is not inside the workspace: {directory}"
        )
    index = next(
        (
            position
            for position, record in enumerate(records)
            if record.get("name") == workspace_step.name
            and record.get("tool") == workspace_step.tool
        ),
        None,
    )
    design_source: UpstreamResponse | None = None
    upstream: Mapping[DesignData, UpstreamResponse] = MappingProxyType({})
    if index is not None:
        source_name = FlowInputResolver(records).input_step_name(index)
        source = next(
            (record for record in reversed(records[:index]) if record.get("name") == source_name),
            None,
        )
        if source is not None:
            design_source = _link(workspace_directory, source)
        upstream = upstream_responses(workspace_directory, records, index)
    if workspace_step.name == StepEnum.STA.value and isinstance(workspace_step.output, EccOutput):
        # STA reads the parasitics the flow wired onto it (RCX or info.spef).
        inputs = replace(inputs, spef=tuple(workspace_step.output.spef))
    return StepRequest(
        workspace_directory=workspace_directory,
        step=workspace_step.name,
        tool=workspace_step.tool,
        step_directory=Path(directory).name,
        attempt_id=attempt_id,
        inputs=inputs,
        design_source=design_source,
        upstream=upstream,
        final_step=bool(records) and records[-1].get("name") == workspace_step.name,
        layout_image=layout_image,
    )


def step_inputs(workspace_step: WorkspaceStep) -> StepInputs:
    """The input files a created step was built from.

    Builders record their inputs on ``step.input``; LEC steps keep the gate
    netlist as ``gate_verilog`` and the golden argument as ``db``, so rebuilding
    a step from these inputs gives the same step.
    """
    step_input = workspace_step.input
    if workspace_step.tool in LEC_STEP_TOOLS and isinstance(step_input, LecInput):
        return StepInputs(
            design=DesignFiles(verilog=step_input.gate_verilog),
            golden_verilog=_path(step_input.db),
        )
    return StepInputs(
        design=DesignFiles(
            def_=step_input.def_, verilog=step_input.verilog, db=_path(step_input.db)
        )
    )


def _path(value: Path | str | None) -> Path | None:
    return Path(value) if value else None


def upstream_responses(
    workspace_directory: Path,
    records: Sequence[Mapping[str, object]],
    index: int,
) -> Mapping[DesignData, UpstreamResponse]:
    """The upstream step that provided each design data item step *index* needs.

    For each item the step requires or uses, the latest earlier step that
    provides it (for ``LEGAL``, the latest legalizing step). Items no earlier
    step provides are declared by the project and are left out.
    """
    earlier = records[:index]
    policy = flow_step_policy(str(records[index].get("name", "")))
    upstream: dict[DesignData, UpstreamResponse] = {}
    for item in sorted(policy.requires | policy.uses):
        provider = next(
            (
                record
                for record in reversed(earlier)
                if step_provides(str(record.get("name", "")), item)
            ),
            None,
        )
        if provider is not None:
            upstream[item] = _link(workspace_directory, provider)
    return MappingProxyType(upstream)


def _link(workspace_directory: Path, record: Mapping[str, object]) -> UpstreamResponse:
    """A link to the step *record*, with the attempt id of its current response."""
    directory = recorded_step_directory(record)
    response = load_response(workspace_directory / directory)
    return UpstreamResponse(directory, None if response is None else response.attempt_id)
