"""Requests and published upstream responses for handshake tests."""

from collections.abc import Mapping
from pathlib import Path

from chipcompiler.data import StepEnum
from chipcompiler.data.handshake import (
    DesignFiles,
    ResponseStatus,
    StepInputs,
    StepRequest,
    StepResponse,
    UpstreamResponse,
    write_response,
)
from chipcompiler.data.step import unindexed_step_directory
from chipcompiler.data.types import DesignData, DesignState

_LEGALIZED = frozenset(
    {
        DesignState.NETLIST,
        DesignState.FLOORPLAN,
        DesignState.PDN,
        DesignState.PLACED,
        DesignState.LEGAL,
    }
)


def _request(
    workspace: Path, step: str, upstream, design_source: UpstreamResponse | None = None
) -> StepRequest:
    return StepRequest(
        workspace_directory=workspace,
        step=step,
        tool="ecc",
        step_directory=f"{step}_ecc",
        attempt_id=f"attempt-{step}",
        inputs=StepInputs(),
        design_source=design_source,
        upstream=upstream,
        final_step=False,
        layout_image=False,
    )


def _publish(workspace: Path, directory: str, states: frozenset[DesignState]) -> None:
    write_response(
        workspace / directory,
        StepResponse(
            step="legalization",
            tool="dreamplace",
            attempt_id="attempt-legal",
            status=ResponseStatus.SUCCESS,
            design=DesignFiles(),
            design_states=states,
            outputs={},
            design_source=None,
            upstream={},
            warnings=frozenset(),
        ),
    )


def _route_request(workspace: Path, attempt_id: str | None) -> StepRequest:
    """Routing that reads the legalized design; no CTS step ran before it."""
    legalization = UpstreamResponse("legalization_dreamplace", attempt_id)
    return _request(
        workspace,
        StepEnum.ROUTING.value,
        {DesignState.LEGAL: legalization},
        design_source=legalization,
    )


def answer(
    workspace: Path,
    directory: str,
    attempt_id: str,
    source: tuple[str, str | None] | None = None,
    *,
    upstream: Mapping[DesignData, tuple[str, str | None]] | None = None,
    status: ResponseStatus = ResponseStatus.SUCCESS,
) -> None:
    """Publish the response of the step in *directory* (``[NN_]<step>_<tool>``).

    *source* and each *upstream* link are ``(step directory, attempt id)``.
    """
    step, _separator, tool = unindexed_step_directory(directory).partition("_")
    write_response(
        workspace / directory,
        StepResponse(
            step=step,
            tool=tool,
            attempt_id=attempt_id,
            status=status,
            design=DesignFiles(),
            design_states=frozenset(),
            outputs={},
            design_source=None if source is None else UpstreamResponse(*source),
            upstream={item: UpstreamResponse(*link) for item, link in (upstream or {}).items()},
            warnings=frozenset(),
        ),
    )
