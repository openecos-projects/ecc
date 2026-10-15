import json
import os
import uuid
from pathlib import Path

import pytest

from chipcompiler.project.runtime_processes import (
    ProcessIdentity,
    RuntimeProcessError,
    build_runtime_entry,
    default_log_path,
    identity_is_live,
    normalize_log_path,
    normalize_run_id,
    read_runtime_process,
    register_runtime_process,
    unregister_runtime_process,
    validate_runtime_entry,
)


def _project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    workspace = project / "baseline"
    workspace.mkdir(parents=True)
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
                "qor_baseline": None,
            }
        )
    )
    return project, workspace


def _entry(project: Path, workspace: Path, run_id: str | None = None) -> dict:
    run_id = run_id or str(uuid.uuid4())
    return build_runtime_entry(
        project,
        workspace,
        run_id=run_id,
        runtime_id="ecc-test",
        log_path=default_log_path(run_id),
        identity=ProcessIdentity(os.getpid(), os.getpid(), "123", "boot", "host"),
        started_at=1.0,
    )


def test_register_and_conditionally_unregister(tmp_path):
    project, workspace = _project(tmp_path)
    entry = _entry(project, workspace)

    register_runtime_process(project, "baseline", entry)
    assert read_runtime_process(project, "baseline") == entry
    assert unregister_runtime_process(project, "baseline", str(uuid.uuid4())) is False
    assert read_runtime_process(project, "baseline") == entry
    assert unregister_runtime_process(project, "baseline", entry["run_id"]) is True
    with pytest.raises(RuntimeProcessError, match="No runtime process"):
        read_runtime_process(project, "baseline")


def test_registration_does_not_replace_another_run(tmp_path):
    project, workspace = _project(tmp_path)
    first = _entry(project, workspace)
    register_runtime_process(project, "baseline", first)

    with pytest.raises(RuntimeProcessError) as caught:
        register_runtime_process(project, "baseline", _entry(project, workspace))

    assert caught.value.code == "workspace_running"
    assert read_runtime_process(project, "baseline") == first


@pytest.mark.parametrize(
    "path",
    ["/tmp/run.log", "../run.log", "home/../run.log", "other.log"],
)
def test_log_path_is_derived_from_run_id(path):
    run_id = str(uuid.uuid4())
    with pytest.raises(RuntimeProcessError):
        normalize_log_path(path, run_id)


def test_runtime_entry_rejects_pid_pgid_mismatch(tmp_path):
    project, workspace = _project(tmp_path)
    entry = _entry(project, workspace)
    entry["pgid"] += 1
    with pytest.raises(RuntimeProcessError):
        validate_runtime_entry(entry)


def test_run_id_requires_canonical_uuid():
    with pytest.raises(RuntimeProcessError):
        normalize_run_id("not-a-uuid")


def test_current_process_identity_is_live():
    from chipcompiler.project.runtime_processes import current_process_identity

    identity = current_process_identity()
    if identity.pid != identity.pgid:
        pytest.skip("test runner is not a process group leader")
    entry = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "pid": identity.pid,
        "pgid": identity.pgid,
        "process_start_id": identity.process_start_id,
        "boot_id": identity.boot_id,
        "host_id": identity.host_id,
        "workspace_path": "baseline",
        "started_at": 1.0,
        "runtime_id": "ecc-test",
        "log_path": "log/placeholder.log",
    }
    entry["log_path"] = default_log_path(entry["run_id"])
    assert identity_is_live(entry)


def test_container_identity_without_machine_id_is_shared_by_child(monkeypatch):
    import subprocess
    import sys

    from chipcompiler.project.runtime_processes import _host_id

    original = Path.read_bytes

    def without_machine_id(path):
        if str(path) in {"/etc/machine-id", "/var/lib/dbus/machine-id"}:
            return b""
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", without_machine_id)
    parent = _host_id()
    child = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; "
            "from chipcompiler.project.runtime_processes import _host_id; "
            "Path.read_bytes=lambda self: b''; print(_host_id())",
        ],
        text=True,
    ).strip()
    assert parent == child


def test_container_identity_changes_with_namespace_and_rejects_missing_boot(monkeypatch):
    from types import SimpleNamespace

    from chipcompiler.project import runtime_processes

    monkeypatch.setattr(Path, "read_bytes", lambda _path: b"")
    monkeypatch.setattr(runtime_processes, "_boot_id", lambda: "boot-a")
    monkeypatch.setattr(Path, "stat", lambda _path: SimpleNamespace(st_dev=1, st_ino=2))
    first = runtime_processes._host_id()
    monkeypatch.setattr(Path, "stat", lambda _path: SimpleNamespace(st_dev=1, st_ino=3))
    assert runtime_processes._host_id() != first

    def unavailable():
        raise RuntimeProcessError("host_identity_unavailable", "boot ID unavailable")

    monkeypatch.setattr(runtime_processes, "_boot_id", unavailable)
    with pytest.raises(RuntimeProcessError, match="boot ID unavailable"):
        runtime_processes._host_id()
