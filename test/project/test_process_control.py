import json
import uuid
from pathlib import Path

import pytest

import chipcompiler.project.process_control as process_control
from chipcompiler.project.process_control import reconcile_process
from chipcompiler.project.runtime_processes import (
    RuntimeProcessError,
    default_log_path,
    write_run_result,
)
from test.flow_fixture import step_fields


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
                        "name": "synthesis",
                        "tool": "yosys",
                        "state": "Ongoing",
                        "info": {
                            "execution": {
                                "schema_version": 1,
                                "run_id": run_id,
                                "started_at": 1.0,
                            }
                        },
                        **step_fields("synthesis", "yosys"),
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
                        "start_step": "synthesis",
                        "end_step": "harden",
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

    recovered = reconcile_process(project, "baseline", run_id, blocking=False)

    assert recovered == ("synthesis",)
    manifest = json.loads((project / "project.json").read_text())
    assert manifest["runtime_processes"] == {}
    result = json.loads((workspace / "log" / f"{run_id}.run.json").read_text())
    assert result["run_id"] == run_id
    assert result["state"] == "interrupted"
    step = json.loads((workspace / "home" / "flow.json").read_text())["steps"][0]
    assert step["state"] == "Incomplete"
    assert "execution" not in step["info"]


def test_reconcile_preserves_a_result_already_published_by_ecc(tmp_path):
    project, workspace, run_id = _project(tmp_path)
    manifest = json.loads((project / "project.json").read_text())
    entry = manifest["runtime_processes"]["baseline"]
    write_run_result(workspace, "baseline", entry, "succeeded")
    result_path = workspace / "log" / f"{run_id}.run.json"
    before = result_path.read_bytes()

    reconcile_process(project, "baseline", run_id, blocking=False)

    assert result_path.read_bytes() == before


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

    assert reconcile_process(project, "baseline", None, blocking=False) == ("synthesis",)
    step = json.loads((workspace / "home" / "flow.json").read_text())["steps"][0]
    assert step["state"] == "Incomplete"


def test_run_id_does_not_fall_back_to_orphan_mode(tmp_path):
    project, workspace, _run_id = _project(tmp_path, registered=False)
    before = (workspace / "home" / "flow.json").read_text()

    with pytest.raises(RuntimeProcessError) as caught:
        reconcile_process(project, "baseline", str(uuid.uuid4()), blocking=False)

    assert caught.value.code == "process_not_found"
    assert (workspace / "home" / "flow.json").read_text() == before


def test_orphan_reconcile_new_registry_entry_is_workspace_busy(tmp_path, monkeypatch):
    # §14.3: a registry entry appearing between acquiring the Workspace lock
    # and reading the manifest must fail busy (exit 20), not recover the new
    # run's Ongoing flow as interrupted (exit 22).
    project, workspace, run_id = _project(tmp_path, registered=False)
    before_flow = (workspace / "home" / "flow.json").read_text()
    real_load = process_control.load_manifest
    reads = {"count": 0}

    def racing_load(project_dir):
        manifest = real_load(project_dir)
        reads["count"] += 1
        if reads["count"] == 2:  # the manifest read inside the locks
            manifest.raw.setdefault("runtime_processes", {})["baseline"] = {
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
        return manifest

    monkeypatch.setattr(process_control, "load_manifest", racing_load)

    with pytest.raises(RuntimeProcessError) as caught:
        reconcile_process(project, "baseline", None, blocking=False)

    assert caught.value.code == "workspace_busy"
    assert (workspace / "home" / "flow.json").read_text() == before_flow


def _register_on_this_host(project: Path, *, boot: str | None = None) -> None:
    """Rewrite the registered entry as one of a run started on this host."""
    from chipcompiler.project.runtime_processes import boot_id, host_id

    path = project / "project.json"
    manifest = json.loads(path.read_text())
    manifest["runtime_processes"]["baseline"].update(
        {"host_id": host_id(), "boot_id": boot_id() if boot is None else boot}
    )
    path.write_text(json.dumps(manifest))


def test_orphan_reconcile_clears_the_entry_of_a_run_that_died_on_this_host(tmp_path):
    # Issue #443: the run was killed and could not unregister itself. Its
    # entry names a process that no longer exists (pid 999999, start id "1").
    project, workspace, _run_id = _project(tmp_path)
    _register_on_this_host(project)

    assert reconcile_process(project, "baseline", None, blocking=False) == ("synthesis",)

    assert json.loads((project / "project.json").read_text())["runtime_processes"] == {}
    step = json.loads((workspace / "home" / "flow.json").read_text())["steps"][0]
    assert step["state"] == "Incomplete"
    assert "execution" not in step["info"]


def test_orphan_reconcile_clears_an_entry_from_before_the_current_boot(tmp_path):
    project, workspace, _run_id = _project(tmp_path)
    _register_on_this_host(project, boot="earlier-boot")

    assert reconcile_process(project, "baseline", None, blocking=False) == ("synthesis",)

    assert json.loads((project / "project.json").read_text())["runtime_processes"] == {}
    step = json.loads((workspace / "home" / "flow.json").read_text())["steps"][0]
    assert step["state"] == "Incomplete"


def test_orphan_reconcile_leaves_a_live_run_on_this_host_alone(tmp_path, monkeypatch):
    project, workspace, _run_id = _project(tmp_path)
    _register_on_this_host(project)
    monkeypatch.setattr(process_control, "identity_is_live", lambda _entry: True)
    before_manifest = (project / "project.json").read_text()
    before_flow = (workspace / "home" / "flow.json").read_text()

    with pytest.raises(RuntimeProcessError) as caught:
        reconcile_process(project, "baseline", None, blocking=False)

    assert caught.value.code == "workspace_busy"
    assert (project / "project.json").read_text() == before_manifest
    assert (workspace / "home" / "flow.json").read_text() == before_flow


def test_orphan_reconcile_does_not_assume_a_run_on_another_host_is_dead(tmp_path):
    project, workspace, _run_id = _project(tmp_path)  # registered by "remote-host"
    before_manifest = (project / "project.json").read_text()
    before_flow = (workspace / "home" / "flow.json").read_text()

    with pytest.raises(RuntimeProcessError) as caught:
        reconcile_process(project, "baseline", None, blocking=False)

    assert caught.value.code == "workspace_busy"
    assert (project / "project.json").read_text() == before_manifest
    assert (workspace / "home" / "flow.json").read_text() == before_flow
