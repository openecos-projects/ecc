"""A step built from an upstream run that changed since is reported stale."""

from chipcompiler.data.handshake import ChangedInput, ResponseStatus, StaleStep, stale_steps
from chipcompiler.data.types import DesignState
from test.data.handshake.helpers import answer

_CHAIN = ("09_CTS_ecc", "10_legalization_dreamplace", "12_route_ecc", "13_filler_ecc")


def _run_chain(workspace) -> None:
    """CTS, legalization, route and filler, each built on the previous run."""
    answer(workspace, _CHAIN[0], "cts-1", None)
    answer(workspace, _CHAIN[1], "legal-1", (_CHAIN[0], "cts-1"))
    answer(
        workspace,
        _CHAIN[2],
        "route-1",
        (_CHAIN[1], "legal-1"),
        upstream={DesignState.CLOCK_TREE: (_CHAIN[0], "cts-1")},
    )
    answer(workspace, _CHAIN[3], "filler-1", (_CHAIN[2], "route-1"))


def test_a_flow_built_on_current_runs_has_no_stale_steps(tmp_path):
    _run_chain(tmp_path)

    assert stale_steps(tmp_path, _CHAIN) == ()


def test_rerunning_a_step_makes_every_step_built_on_it_stale(tmp_path):
    _run_chain(tmp_path)
    answer(tmp_path, _CHAIN[0], "cts-2", None)

    assert stale_steps(tmp_path, _CHAIN) == (
        StaleStep("legalization", _CHAIN[1], (ChangedInput(_CHAIN[0], "cts-1", "cts-2"),), ()),
        StaleStep("route", _CHAIN[2], (ChangedInput(_CHAIN[0], "cts-1", "cts-2"),), (_CHAIN[1],)),
        StaleStep("filler", _CHAIN[3], (), (_CHAIN[2],)),
    )


def test_an_upstream_step_whose_rerun_failed_leaves_its_users_stale(tmp_path):
    _run_chain(tmp_path)
    answer(tmp_path, _CHAIN[2], "route-2", (_CHAIN[1], "legal-1"), status=ResponseStatus.FAILED)

    assert stale_steps(tmp_path, _CHAIN) == (
        StaleStep("filler", _CHAIN[3], (ChangedInput(_CHAIN[2], "route-1", None),), ()),
    )


def test_steps_from_before_responses_are_never_stale(tmp_path):
    answer(tmp_path, _CHAIN[0], "cts-2", None)
    answer(tmp_path, _CHAIN[1], "legal-1", (_CHAIN[0], None))

    assert stale_steps(tmp_path, _CHAIN[:2]) == ()


def test_a_step_that_did_not_run_or_failed_is_not_checked(tmp_path):
    answer(tmp_path, _CHAIN[0], "cts-2", None)
    answer(tmp_path, _CHAIN[1], "legal-1", (_CHAIN[0], "cts-1"), status=ResponseStatus.FAILED)

    assert stale_steps(tmp_path, _CHAIN) == ()


def test_saving_the_ledger_resets_steps_built_on_a_changed_run(tmp_path):
    from chipcompiler.data.workspace import Flow
    from chipcompiler.data.workspace.flow_ledger import save_ledger
    from chipcompiler.data.workspace.flow_types import load_flow_document

    _run_chain(tmp_path)
    (tmp_path / "home").mkdir()
    flow = Flow(
        path=tmp_path / "home" / "flow.json",
        data={
            "schema_version": 2,
            "steps": [
                {
                    "name": directory.split("_")[1],
                    "tool": directory.split("_", 2)[2],
                    "state": "Success",
                    "runtime": "0:0:1",
                    "category": "PNR",
                    "directory": directory,
                }
                for directory in _CHAIN
            ],
        },
    )
    answer(tmp_path, _CHAIN[1], "legal-2", (_CHAIN[0], "cts-1"))  # legalization reran

    assert save_ledger(flow)

    states = [
        (step["state"], step.get("runtime"))
        for step in load_flow_document(flow.path).get("steps", [])
    ]
    assert states == [
        ("Success", "0:0:1"),
        ("Success", "0:0:1"),
        ("Unstart", ""),
        ("Unstart", ""),
    ]
