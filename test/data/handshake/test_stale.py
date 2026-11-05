"""A step built from an upstream run that changed since is reported stale."""

from chipcompiler.data.handshake import (
    ChangedInput,
    DesignFiles,
    ResponseStatus,
    StaleStep,
    StepResponse,
    UpstreamResponse,
    stale_steps,
    write_response,
)
from chipcompiler.data.types import DesignData, DesignState

_CHAIN = ("09_CTS_ecc", "10_legalization_dreamplace", "12_route_ecc", "13_filler_ecc")


def _answer(
    workspace,
    directory: str,
    attempt_id: str,
    source: tuple[str, str | None] | None,
    *,
    status: ResponseStatus = ResponseStatus.SUCCESS,
    clock_tree: tuple[str, str | None] | None = None,
) -> None:
    upstream: dict[DesignData, UpstreamResponse] = {}
    if clock_tree is not None:
        upstream[DesignState.CLOCK_TREE] = UpstreamResponse(*clock_tree)
    write_response(
        workspace / directory,
        StepResponse(
            step=directory.split("_", 2)[1],
            tool="ecc",
            attempt_id=attempt_id,
            status=status,
            design=DesignFiles(),
            design_states=frozenset(),
            outputs={},
            design_source=None if source is None else UpstreamResponse(*source),
            upstream=upstream,
            warnings=frozenset(),
        ),
    )


def _run_chain(workspace) -> None:
    """CTS, legalization, route and filler, each built on the previous run."""
    _answer(workspace, _CHAIN[0], "cts-1", None)
    _answer(workspace, _CHAIN[1], "legal-1", (_CHAIN[0], "cts-1"))
    _answer(
        workspace, _CHAIN[2], "route-1", (_CHAIN[1], "legal-1"), clock_tree=(_CHAIN[0], "cts-1")
    )
    _answer(workspace, _CHAIN[3], "filler-1", (_CHAIN[2], "route-1"))


def test_a_flow_built_on_current_runs_has_no_stale_steps(tmp_path):
    _run_chain(tmp_path)

    assert stale_steps(tmp_path, _CHAIN) == ()


def test_rerunning_a_step_makes_every_step_built_on_it_stale(tmp_path):
    _run_chain(tmp_path)
    _answer(tmp_path, _CHAIN[0], "cts-2", None)

    assert stale_steps(tmp_path, _CHAIN) == (
        StaleStep("legalization", _CHAIN[1], (ChangedInput(_CHAIN[0], "cts-1", "cts-2"),), ()),
        StaleStep("route", _CHAIN[2], (ChangedInput(_CHAIN[0], "cts-1", "cts-2"),), (_CHAIN[1],)),
        StaleStep("filler", _CHAIN[3], (), (_CHAIN[2],)),
    )


def test_an_upstream_step_whose_rerun_failed_leaves_its_users_stale(tmp_path):
    _run_chain(tmp_path)
    _answer(tmp_path, _CHAIN[2], "route-2", (_CHAIN[1], "legal-1"), status=ResponseStatus.FAILED)

    assert stale_steps(tmp_path, _CHAIN) == (
        StaleStep("filler", _CHAIN[3], (ChangedInput(_CHAIN[2], "route-1", None),), ()),
    )


def test_steps_from_before_responses_are_never_stale(tmp_path):
    _answer(tmp_path, _CHAIN[0], "cts-2", None)
    _answer(tmp_path, _CHAIN[1], "legal-1", (_CHAIN[0], None))

    assert stale_steps(tmp_path, _CHAIN[:2]) == ()


def test_a_step_that_did_not_run_or_failed_is_not_checked(tmp_path):
    _answer(tmp_path, _CHAIN[0], "cts-2", None)
    _answer(tmp_path, _CHAIN[1], "legal-1", (_CHAIN[0], "cts-1"), status=ResponseStatus.FAILED)

    assert stale_steps(tmp_path, _CHAIN) == ()
