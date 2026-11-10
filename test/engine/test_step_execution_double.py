"""The in-process step double runs beside sibling checker threads like the real worker."""

import logging
from types import SimpleNamespace

from chipcompiler.data.workspace import Flow
from chipcompiler.data.workspace.flow_ledger import save_ledger
from test.engine.step_execution_double import _initialize_worker_db, _worker_view
from test.flow_fixture import current_flow_document


def test_worker_sees_its_own_read_only_ledger(tmp_path):
    # A parallel checker wave shares the engine's ledger; reloading it from
    # disk drops the siblings' concurrent state saves (CI: RCX Unstart → Success).
    (tmp_path / "home").mkdir()
    flow = Flow(
        path=tmp_path / "home" / "flow.json",
        data=current_flow_document(
            [{"name": "postRouteLec", "tool": "kepler_formal", "state": "Ongoing"}]
        ),
    )
    assert save_ledger(flow)
    ledger = flow.data
    workspace = SimpleNamespace(directory=tmp_path, flow=flow, logger=logging.getLogger(__name__))

    view = _worker_view(workspace)
    _initialize_worker_db(view, SimpleNamespace(name="postRouteLec", tool="kepler_formal"))

    assert workspace.flow is flow and flow.data is ledger
    assert (view.flow.read_only, view.flow.data == ledger, view.flow.data is ledger) == (
        True,
        True,
        False,
    )
