from types import SimpleNamespace

import pytest

from chipcompiler.runtime import subflow_events


def test_interrupted_subflow_write_failure_restores_ongoing_state(monkeypatch, tmp_path):
    step = {"name": "run placement", "state": "Ongoing"}
    workspace_step = SimpleNamespace(
        subflow=SimpleNamespace(path=tmp_path / "subflow.json", steps=[step])
    )
    monkeypatch.setattr(subflow_events, "json_write", lambda *_args, **_kwargs: False)

    with pytest.raises(OSError, match="failed to save interrupted subflow"):
        subflow_events.finalize_interrupted_subflow(workspace_step, "0:0:1", 10.0)

    assert step == {"name": "run placement", "state": "Ongoing"}
