import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data import StateEnum
from chipcompiler.engine import execution
from ecc_experience.collection import context
from ecc_experience.collection.drain import drain
from ecc_experience.files import digest
from ecc_experience.knowledge.configuration import configuration_identity
from ecc_experience.knowledge.normalize import normalize_stores
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.recording import ExperienceRecorder, set_enabled


@pytest.fixture
def recorded_design(workspace_factory, tmp_path, monkeypatch):
    workspace = workspace_factory("recorded")
    project = tmp_path / "project"
    project.mkdir()
    store = ExperienceStore(tmp_path / "store")
    config = set_enabled(project, store=store.root, enabled=True)
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    pdk_files = {}
    for role in ("tech", "lef", "liberty"):
        path = tmp_path / f"selected.{role}"
        path.write_text(f"test {role} content")
        pdk_files[role] = str(path)
    rtl = tmp_path / "sample.v"
    rtl.write_text("module sample; endmodule")
    snapshot["workspaceSpec"] = {
        "design": {"name": "sample", "topModule": "sample"},
        "parameters": {"place.target_density": 0.4},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
        "pdk": {
            "familyId": "ics55",
            "mode": "manual",
            "files": [{"fileId": role, "role": role} for role in pdk_files],
        },
    }
    snapshot["workspaceBindings"] = {"pdk": {"files": pdk_files}, "inputs": {"rtl": str(rtl)}}
    snapshot["flow"]["steps"][0]["checklist_status"] = {"status": "passed"}
    snapshot["signoffAssessment"] = {"status": "ready"}
    snapshot["qorSnapshotExtension"].update(status="available", score=80.0, scalarStatus="GREEN")
    snapshot["qorSnapshotExtension"].pop("reason", None)
    snapshot_path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
    runtime = {
        "ecc": "test",
        "sources": {"chipcompiler": "test-source"},
        "tools": {"yosys": "0.60", "kepler_formal": "kepler-formal 0.3.0"},
        "native_packages": {},
    }
    monkeypatch.setattr(context, "runtime_identity", lambda: deepcopy(runtime))
    return SimpleNamespace(
        workspace=workspace,
        project=project,
        store=store,
        config=config,
        snapshot=snapshot,
        pdk_files=pdk_files,
        runtime=runtime,
    )


def _record(design):
    recorder = ExperienceRecorder(design.project, design.workspace, design.config)
    recorder.start(intent="run")
    recorder.committed_step(
        design.snapshot, SimpleNamespace(name="Synthesis", tool="yosys"), "Success"
    )
    return recorder


def test_recording_to_normalization_preserves_complete_attempt_bound_identity(
    recorded_design, tmp_path
):
    design = recorded_design
    before = {path: path.read_bytes() for path in design.workspace.rglob("*") if path.is_file()}
    identifiers = []
    for _attempt in range(2):
        recorder = _record(design)
        recorder.finish(status="success")
        results = drain(design.project)
        assert [result["status"] for result in results] == ["created"]
        case = design.store.read(results[0]["case_id"])
        identifiers.append(case.case_id)
        captured = case.facts["experienceExecutionContext"]
        assert captured["attempt_id"] == recorder.attempt_id == case.source.attempt_id
        assert captured["snapshot_digest"] == digest(design.snapshot)
        assert captured["checks"] == {"runtime": "available", "process": "available"}
        assert captured["runtime"] == design.runtime
        assert case.process_fingerprint == captured["process"]["fingerprint"]
        assert configuration_identity(case)["complete"]
    report = normalize_stores([design.store.root], tmp_path / "normalized")
    assert report["exit_code"] == 0
    assert report["counts"]["positive"] == 2
    assert report["counts"]["configuration_groups"] == 1
    assert report["configuration_groups"][0]["case_ids"] == sorted(identifiers)
    assert before == {path: path.read_bytes() for path in before}


def test_changed_runtime_is_preserved_but_not_claimed_as_execution_identity(recorded_design):
    design = recorded_design
    recorder = _record(design)
    design.runtime["tools"]["yosys"] = "0.61"
    recorder.finish(status="success")
    result = drain(design.project)[0]
    case = design.store.read(result["case_id"])
    captured = case.facts["experienceExecutionContext"]
    assert captured["checks"] == {"runtime": "changed", "process": "available"}
    assert captured["runtime"] is None
    assert captured["observations"]["runtime_before"] != captured["observations"]["runtime_after"]
    assert configuration_identity(case)["missing_identity"] == ["runtime"]


def test_mid_attempt_pdk_change_is_detected_even_if_restored(recorded_design):
    design = recorded_design
    recorder = _record(design)
    liberty = Path(design.pdk_files["liberty"])
    before = liberty.read_bytes()
    liberty.write_text("changed liberty")
    recorder.committed_step(
        design.snapshot, SimpleNamespace(name="Synthesis", tool="yosys"), "Success"
    )
    liberty.write_bytes(before)
    recorder.finish(status="success")
    case = design.store.read(drain(design.project)[0]["case_id"])
    captured = case.facts["experienceExecutionContext"]
    assert captured["checks"] == {"runtime": "available", "process": "changed"}
    assert not captured["observations"]["process_unchanged_at_commits"]
    assert captured["observations"]["process_before"] == captured["observations"]["process_after"]
    assert case.process_fingerprint is None


@pytest.mark.parametrize("failure", [RuntimeError, SystemExit])
def test_optional_identity_failure_does_not_fail_the_flow(recorded_design, monkeypatch, failure):
    design = recorded_design

    def unavailable():
        raise failure("version probe unavailable")

    monkeypatch.setattr(context, "runtime_identity", unavailable)
    monkeypatch.setattr(
        "chipcompiler.engine.snapshot.ensure_engineering_snapshot",
        lambda workspace: design.snapshot,
    )
    monkeypatch.setattr(
        "chipcompiler.engine.snapshot.commit_engineering_snapshot",
        lambda *args, **kwargs: design.snapshot,
    )

    class Flow:
        workspace = SimpleNamespace(directory=design.workspace, _ecc_project_dir=design.project)

        def run_steps(self, *, rerun=False, observer=None):
            observer.on_step_completed(
                SimpleNamespace(name="Synthesis", tool="yosys"), StateEnum.Success
            )
            return True

    assert execution.execute(Flow(), execution.ExecutionPlan(intent="run")).succeeded
    result = drain(design.project)[0]
    assert result["status"] == "created"
    case = design.store.read(result["case_id"])
    assert case.facts["experienceExecutionContext"]["checks"]["runtime"] == "unknown"
    assert case.facts["experienceExecutionContext"]["runtime"] is None


def test_legacy_outbox_is_not_backfilled_from_the_current_environment(recorded_design, monkeypatch):
    design = recorded_design
    recorder = _record(design)
    recorder.finish(status="success")
    for path in (design.project / ".ecc/experience/outbox").glob("*.json"):
        event = json.loads(path.read_text())
        event.pop("execution_context", None)
        event.pop("execution_identity", None)
        event.pop("process_observation", None)
        path.write_text(json.dumps(event))

    def unexpected_probe():
        pytest.fail("drain must not probe the current environment")

    monkeypatch.setattr(context, "runtime_identity", unexpected_probe)
    result = drain(design.project)[0]
    assert result["status"] == "created"
    case = design.store.read(result["case_id"])
    assert case.process_fingerprint is None
    assert "experienceExecutionContext" not in case.facts


@pytest.mark.parametrize("invalid", ["attempt", "snapshot", "shape", "process", "runtime"])
def test_context_mismatch_preserves_pending_events_without_creating_a_case(
    recorded_design, invalid
):
    design = recorded_design
    recorder = _record(design)
    recorder.finish(status="success")
    outbox = design.project / ".ecc/experience/outbox"
    finished = sorted(outbox.glob("*.json"))[-1]
    event = json.loads(finished.read_text())
    if invalid == "shape":
        event["execution_context"] = []
    elif invalid in {"process", "runtime"}:
        event["execution_context"][invalid] = []
    else:
        field = "attempt_id" if invalid == "attempt" else "snapshot_digest"
        event["execution_context"][field] = "incorrect"
    finished.write_text(json.dumps(event))

    result = drain(design.project)[0]

    assert result["status"] == "failed"
    assert "does not match" in result["reason"]
    assert len(list(outbox.glob("*.json"))) == 3
    assert not (design.store.root / "cases").exists()
