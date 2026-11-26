import json
from threading import Thread

import pytest

from agent.cli import run_resume, run_status
from chipcompiler.cli import main as cli_main


def test_retry_reports_the_same_interrupted_operation_as_status(fresh_project, capsys, monkeypatch):
    assert cli_main.run(["workspace", "create", "source", "--project", str(fresh_project)]) == 0
    request = {
        "candidate_id": "candidate-1",
        "idempotency_key": "retry-1",
        "context_sha256": "sha256:" + "a" * 64,
        "parameter_card_sha256": "sha256:" + "b" * 64,
        "seed": 1,
        "expected_workspace_revision": 1,
    }

    def stop_before_execution(_thread):
        raise RuntimeError("stopped after enqueue")

    with monkeypatch.context() as patch:
        patch.setattr(Thread, "start", stop_before_execution)
        with pytest.raises(RuntimeError, match="stopped after enqueue"):
            run_resume(fresh_project, "source", request)

    capsys.readouterr()
    run_resume(fresh_project, "source", request)
    accepted, terminal = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    run_status(fresh_project, "source", "candidate-1")
    (stored,) = json.loads(capsys.readouterr().out)["operations"]
    assert stored["state"] == "interrupted"
    replay = terminal["operation"]
    assert terminal["record"] == "candidate_terminal"
    assert accepted == {"record": "candidate_accepted", "operation": replay}
    assert replay["deduplicated"] is True
    for key in ("operationId", "state", "error", "result"):
        assert replay[key] == stored[key]
