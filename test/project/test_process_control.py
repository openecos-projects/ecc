import json
import uuid
from pathlib import Path

import pytest

from chipcompiler.project.process_control import reconcile_process
from chipcompiler.project.runtime_processes import RuntimeProcessError, default_log_path


def _project(tmp_path: Path, *, registered: bool = True) -> tuple[Path, Path, str]:
    project = tmp_path / "project"
    workspace = project / "baseline"
    home = workspace / "home"
    home.mkdir(parents=True)
    run_id = str(uuid.uuid4())
    (home / "flow.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "steps": [
                    {
                        "name": "Synthesis",
                        "tool": "yosys",
                        "state": "Ongoing",
                        "info": {
                            "execution": {
                                "schema_version": 1,
                                "run_id": run_id,
                                "started_at": 1.0,
                            }
                        },
                    }
                ],
            }
        )
    )
    runtime_processes = {}
    if registered:
        runtime_processes["baseline"] = {
            "schema_version": 1,
            "run_id": run_id,
            "pid": 999999,
            "pgid": 999999,
            "process_start_id": "1",
            "boot_id": "remote-boot",
            "host_id": "remote-host",
            "workspace_path": "baseline",
            "started_at": 1.0,
            "runtime_id": "ecc-test",
            "log_path": default_log_path(run_id),
        }
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
                        "start_step": "Synth",
                        "end_step": "Harden",
                        "status": "not_started",
                    }
                ],
                "runtime_processes": runtime_processes,
                "qor_baseline": None,
            }
        )
    )
    return project, workspace, run_id


def test_registered_reconcile_recovers_flow_then_removes_matching_entry(tmp_path):
    project, workspace, run_id = _project(tmp_path)

    recovered = reconcile_process(
        project, "baseline", run_id, blocking=False
    )

    assert recovered == ("Synthesis",)
    manifest = json.loads((project / "project.json").read_text())
    assert manifest["runtime_processes"] == {}
    step = json.loads((workspace / "home" / "flow.json").read_text())["steps"][0]
    assert step["state"] == "Incomplete"
    assert "execution" not in step["info"]


def test_registered_reconcile_run_id_mismatch_changes_nothing(tmp_path):
    project, workspace, _run_id = _project(tmp_path)
    before_manifest = (project / "project.json").read_text()
    before_flow = (workspace / "home" / "flow.json").read_text()

    with pytest.raises(RuntimeProcessError) as caught:
        reconcile_process(project, "baseline", str(uuid.uuid4()), blocking=False)

    assert caught.value.code == "process_not_found"
    assert (project / "project.json").read_text() == before_manifest
    assert (workspace / "home" / "flow.json").read_text() == before_flow


def test_orphan_reconcile_recovers_without_registry(tmp_path):
    project, workspace, _run_id = _project(tmp_path, registered=False)

    assert reconcile_process(project, "baseline", None, blocking=False) == ("Synthesis",)
    step = json.loads((workspace / "home" / "flow.json").read_text())["steps"][0]
    assert step["state"] == "Incomplete"


def test_run_id_does_not_fall_back_to_orphan_mode(tmp_path):
    project, workspace, _run_id = _project(tmp_path, registered=False)
    before = (workspace / "home" / "flow.json").read_text()

    with pytest.raises(RuntimeProcessError) as caught:
        reconcile_process(project, "baseline", str(uuid.uuid4()), blocking=False)

    assert caught.value.code == "process_not_found"
    assert (workspace / "home" / "flow.json").read_text() == before
