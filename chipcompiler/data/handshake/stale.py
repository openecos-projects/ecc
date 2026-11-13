"""Steps whose outputs were built from upstream runs that are no longer current.

A step's response records the upstream runs it accepted: the step whose design
it read and the step that provided each design data item it needs. When one of
those upstream steps runs again, its response carries a new attempt id, and a
step built on the older run is stale; so is any step that accepted a stale
step's outputs. Stale steps are reported, never rerun automatically:
``ecc run --from`` reruns them.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from chipcompiler.data.handshake.files import HandshakeError, load_response
from chipcompiler.data.handshake.messages import ResponseStatus, StepResponse, UpstreamResponse


@dataclass(frozen=True, slots=True)
class ChangedInput:
    """An upstream run a step accepted that is no longer the upstream's current run."""

    step_directory: str
    accepted_attempt_id: str
    #: The upstream step's current successful attempt; None when it has none.
    current_attempt_id: str | None


@dataclass(frozen=True, slots=True)
class StaleStep:
    step: str
    step_directory: str
    #: Accepted upstream runs that were replaced or failed since.
    changed_inputs: tuple[ChangedInput, ...]
    #: Accepted upstream steps that are stale themselves.
    stale_upstream: tuple[str, ...]


def stale_steps(
    workspace_directory: Path, step_directories: Sequence[str]
) -> tuple[StaleStep, ...]:
    """The stale steps among *step_directories*, which are given in flow order.

    Only steps with a successful response are checked: a step that has not run,
    or whose last run failed, has no outputs to be stale. Links that carry no
    attempt id come from steps that ran before responses existed and never count
    as changed.
    """
    stale: dict[str, StaleStep] = {}
    for directory in step_directories:
        response = _current_response(workspace_directory / directory)
        if response is None:
            continue
        changed: list[ChangedInput] = []
        stale_upstream: list[str] = []
        for link in _accepted_links(response):
            if link.step_directory in stale:
                stale_upstream.append(link.step_directory)
            if link.attempt_id is None:
                continue
            current = _current_response(workspace_directory / link.step_directory)
            current_attempt_id = None if current is None else current.attempt_id
            if current_attempt_id != link.attempt_id:
                changed.append(
                    ChangedInput(link.step_directory, link.attempt_id, current_attempt_id)
                )
        if changed or stale_upstream:
            stale[directory] = StaleStep(
                response.step, directory, tuple(changed), tuple(dict.fromkeys(stale_upstream))
            )
    return tuple(stale.values())


def _current_response(step_directory: Path) -> StepResponse | None:
    """The step's successful response; None when it has none or it is unreadable."""
    try:
        response = load_response(step_directory)
    except HandshakeError:
        return None
    if response is None or response.status is not ResponseStatus.SUCCESS:
        return None
    return response


def _accepted_links(response: StepResponse) -> tuple[UpstreamResponse, ...]:
    links = [] if response.design_source is None else [response.design_source]
    links.extend(response.upstream.values())
    return tuple(dict.fromkeys(links))
