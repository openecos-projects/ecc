import json
import os
import subprocess
import uuid

from chipcompiler.cli.experiments import operations
from chipcompiler.project.runtime_processes import (
    ProcessIdentity,
    build_runtime_entry,
    default_log_path,
    register_runtime_process,
    unregister_runtime_process,
)


def _project(tmp_path):
    project = tmp_path / "project"
    (project / "baseline").mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "proj-test",
                "name": "test",
                "design_name": "gcd",
                "root_path": str(project),
                "base_design": {},
                "objectives": {},
                "workspaces": [
                    {
                        "workspace_id": "baseline",
                        "workspace_path": "baseline",
                        "start_step": "synthesis",
                        "end_step": "harden",
                        "status": "not_started",
                    }
                ],
                "runtime_processes": {},
                "qor_baseline": None,
            }
        ),
        encoding="utf-8",
    )
    return project


def _declare_workspace(project, workspace_id):
    path = project / "project.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["workspaces"].append(
        {
            "workspace_id": workspace_id,
            "workspace_path": workspace_id,
            "start_step": "synthesis",
            "end_step": "harden",
            "status": "not_started",
        }
    )
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _register_like_a_run(command):
    """What the candidate's `ecc run` does before its first step: declare and register."""
    project = command[command.index("--project") + 1]
    workspace = command[command.index("--workspace") + 1]
    workspace_id = os.path.basename(workspace)
    os.makedirs(workspace)
    _declare_workspace(operations.Path(project), workspace_id)
    run_id = str(uuid.uuid4())
    entry = build_runtime_entry(
        project,
        workspace,
        run_id=run_id,
        runtime_id="ecc-test",
        log_path=default_log_path(run_id),
        identity=ProcessIdentity(os.getpid(), os.getpid(), "123", "boot", "host"),
        started_at=1.0,
    )
    register_runtime_process(project, workspace_id, entry)
    assert unregister_runtime_process(project, workspace_id, run_id) is True


def _stub_candidate_runs(monkeypatch, commands):
    def fake_run(command, **_kwargs):
        commands.append(command)
        _register_like_a_run(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(operations.subprocess, "run", fake_run)
    monkeypatch.setattr(
        operations,
        "collect_candidate_evidence",
        lambda *_args: {"status": "passed", "step_statuses": []},
    )


def test_sweep_run_gives_each_candidate_an_empty_runtime_registry(tmp_path, monkeypatch):
    project = _project(tmp_path)
    operations.create_sweep(project, "s1", {"design.frequency_mhz": ["100", "200"]})
    _stub_candidate_runs(monkeypatch, [])

    operations.run_sweep(project, "s1", None)

    for candidate in ("candidate_0001", "candidate_0002"):
        copy = project / "experiments" / "s1" / "candidates" / candidate / "project"
        manifest = json.loads((copy / "project.json").read_text(encoding="utf-8"))
        assert manifest["root_path"] == str(copy)
        assert manifest["runtime_processes"] == {}
        assert [row["workspace_id"] for row in manifest["workspaces"]] == [candidate]


def test_sweep_run_candidate_can_register_its_run(tmp_path, monkeypatch):
    project = _project(tmp_path)
    operations.create_sweep(project, "s1", {"design.frequency_mhz": ["100", "200"]})
    commands = []
    _stub_candidate_runs(monkeypatch, commands)

    payload = operations.run_sweep(project, "s1", None)

    assert len(commands) == 2
    assert [row["exit_code"] for row in payload["results"]] == [0, 0]
    assert [row["status"] for row in payload["results"]] == ["passed", "passed"]


def test_sweep_run_does_not_carry_the_parent_registry_into_a_candidate(tmp_path, monkeypatch):
    project = _project(tmp_path)
    path = project / "project.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["runtime_processes"] = {"baseline": {"run_id": str(uuid.uuid4())}}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    operations.create_sweep(project, "s1", {"design.frequency_mhz": ["100"]})
    _stub_candidate_runs(monkeypatch, [])

    operations.run_sweep(project, "s1", None)

    copy = project / "experiments" / "s1" / "candidates" / "candidate_0001" / "project"
    copied = json.loads((copy / "project.json").read_text(encoding="utf-8"))
    parent = json.loads(path.read_text(encoding="utf-8"))
    assert copied["runtime_processes"] == {}
    assert parent["runtime_processes"] == manifest["runtime_processes"]
