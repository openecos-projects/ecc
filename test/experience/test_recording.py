import json
from types import SimpleNamespace

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.api import drain
from ecc_experience.files import digest
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.recording import ExperienceRecorder, recorder_for, set_enabled, status


def test_recording_writes_attempt_and_committed_step_facts(tmp_path):
    project = tmp_path / "project"
    workspace = project / "workspace"
    workspace.mkdir(parents=True)
    config = set_enabled(project, store=tmp_path / "store", enabled=True)
    recorder = ExperienceRecorder(project, workspace, config)
    recorder.start(intent="run", requested_steps=("synthesis",))
    recorder.committed_step(
        {
            "workspaceId": "workspace-1",
            "workspaceRevision": 4,
            "schemaVersion": 4,
            "cause": "flow_step.success",
            "flow": {
                "steps": [{"name": "synthesis", "runtime": "0:01:02", "peak memory (mb)": 12.5}]
            },
        },
        SimpleNamespace(name="synthesis", tool="yosys"),
        "Success",
    )
    recorder.finish(status="success")

    events = sorted((project / ".ecc/experience/outbox").glob("*.json"))
    assert [json.loads(path.read_text())["event"] for path in events] == [
        "attempt_started",
        "step_committed",
        "attempt_finished",
    ]
    step = json.loads(events[1].read_text())
    assert step["attempt_id"] == recorder.attempt_id
    assert step["resource"] == {
        "elapsed_seconds": 62.0,
        "peak_memory_mb": 12.5,
        "scope": "flow_step_ledger",
        "status": "available",
    }
    assert status(project)["outbox"]["pending"] == 3


def test_disabled_project_has_no_recorder(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    set_enabled(project, store=tmp_path / "store", enabled=False)
    assert recorder_for(project, project / "workspace") is None


def test_drain_materializes_completed_attempt(workspace_factory, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = workspace_factory("recorded")
    store = tmp_path / "store"
    config = set_enabled(project, store=store, enabled=True)
    recorder = ExperienceRecorder(project, workspace, config)
    recorder.start(intent="run")
    snapshot = json.loads((workspace / "home/engineering-snapshot.json").read_text())
    recorder.committed_step(snapshot, SimpleNamespace(name="Synthesis", tool="yosys"), "Success")
    recorder.finish(status="success")

    results = drain(project)
    assert results[0]["status"] == "created"
    case = json.loads((store / "cases" / results[0]["case_id"] / "case.json").read_text())
    assert case["source"]["attempt_id"] == recorder.attempt_id
    assert not list((project / ".ecc/experience/outbox").glob("*.json"))
    assert read_workspace_observation(workspace).source.snapshot_digest == digest(snapshot)
    verification = verify_case(
        ExperienceStore(store).read(results[0]["case_id"]),
        ExperienceStore(store).case_directory(results[0]["case_id"]),
    )
    assert (
        next(item for item in verification.findings if item.check == "execution_identity").status
        == "pass"
    )
