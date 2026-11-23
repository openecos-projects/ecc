import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from chipcompiler.project.manifest_write import build_manifest_document, manifest_lock


def test_no_wait_run_waits_for_project_registration_transaction(tmp_path):
    workspace = tmp_path / "baseline"
    workspace.mkdir()
    manifest = build_manifest_document(
        str(tmp_path),
        design_name="gcd",
        base_design={},
        workspace_id="baseline",
        workspace_path="baseline",
        start_step="synthesis",
        end_step="harden",
    )
    manifest_path = tmp_path / "project.json"
    manifest_path.write_text(json.dumps(manifest))
    script = dedent("""
        import json
        import sys
        from pathlib import Path
        from types import SimpleNamespace
        from uuid import uuid4

        from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions, RunInput
        from chipcompiler.cli.project.run_process import managed_run_process
        from chipcompiler.project.runtime_processes import read_runtime_process

        project = Path(sys.argv[1])
        workspace = SimpleNamespace()
        request = RunInput(
            output=OutputOptions(), project=ProjectOptions(project=str(project)),
            no_wait=True, run_id=str(uuid4()), only="synthesis",
        )
        print("ready", flush=True)
        with managed_run_process(
            request, project, "baseline", workspace, workspace_path=str(project / "baseline")
        ) as outcome:
            entry = read_runtime_process(project, "baseline")
            assert entry["run_id"] == request.run_id
            assert entry["selection"] == {"only": "synthesis"}
            outcome.succeeded = True
            assert workspace._ecc_run_id == request.run_id
            print("registered", flush=True)
        assert not hasattr(workspace, "_ecc_run_id")
        report_path = project / "baseline" / "log" / f"{request.run_id}.run.json"
        report = json.loads(report_path.read_text())
        assert report == {
            "schema_version": 1,
            "run_id": request.run_id,
            "workspace_id": "baseline",
            "started_at": entry["started_at"],
            "finished_at": report["finished_at"],
            "runtime_id": entry["runtime_id"],
            "state": "succeeded",
            "only": "synthesis",
        }
    """)
    child = None
    try:
        with manifest_lock(tmp_path):
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(tmp_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            assert child.stdout is not None
            assert child.stdout.readline() == "ready\n"
            with pytest.raises(subprocess.TimeoutExpired):
                child.wait(timeout=1)

        stdout, stderr = child.communicate(timeout=10)
        assert (child.returncode, stdout, stderr) == (0, "registered\n", "")
        assert json.loads(manifest_path.read_text()).get("runtime_processes", {}) == {}
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)


@pytest.mark.parametrize("failed_write", ["result", "log"])
def test_run_unregisters_after_a_write_failure(tmp_path, monkeypatch, failed_write):
    from types import SimpleNamespace
    from uuid import uuid4

    from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions, RunInput
    from chipcompiler.cli.project import run_process
    from chipcompiler.project.runtime_processes import RuntimeProcessError

    workspace = tmp_path / "baseline"
    workspace.mkdir()
    manifest = build_manifest_document(
        str(tmp_path),
        design_name="gcd",
        base_design={},
        workspace_id="baseline",
        workspace_path="baseline",
        start_step="synthesis",
        end_step="harden",
    )
    manifest_path = tmp_path / "project.json"
    manifest_path.write_text(json.dumps(manifest))
    run_id = str(uuid4())
    request = RunInput(
        output=OutputOptions(),
        project=ProjectOptions(project=str(tmp_path)),
        run_id=run_id,
        only="synthesis",
    )
    monkeypatch.setattr(run_process, "_ensure_process_group_leader", lambda: None)

    def fail(*_args):
        raise OSError("injected write failure")

    # Use a real process group identity for the test fixture without changing the test runner.
    from chipcompiler.project import runtime_processes

    identity = runtime_processes.current_process_identity()
    monkeypatch.setattr(
        runtime_processes,
        "current_process_identity",
        lambda: runtime_processes.ProcessIdentity(
            identity.pid,
            identity.pid,
            identity.process_start_id,
            identity.boot_id,
            identity.host_id,
        ),
    )

    def run():
        with run_process.managed_run_process(
            request,
            tmp_path,
            "baseline",
            SimpleNamespace(),
            workspace_path=str(workspace),
        ) as outcome:
            outcome.succeeded = True
            assert (
                json.loads(manifest_path.read_text())["runtime_processes"]["baseline"]["run_id"]
                == run_id
            )

    if failed_write == "result":
        monkeypatch.setattr(run_process, "write_run_result", fail)
        with pytest.raises(RuntimeProcessError, match="injected write failure") as exc:
            run()
        assert exc.value.code == "run_result_write_failed"
        assert not (workspace / "log" / f"{run_id}.run.json").exists()
    else:
        # Preserve the real fsync for result and manifest writes. Fail only the run log.
        original_fsync = run_process.os.fsync
        log_path = workspace / "log" / f"{run_id}.log"

        def fail_log_fsync(fd):
            if Path(f"/proc/self/fd/{fd}").resolve() == log_path:
                fail()
            original_fsync(fd)

        monkeypatch.setattr(run_process.os, "fsync", fail_log_fsync)
        run()
        assert (
            json.loads((workspace / "log" / f"{run_id}.run.json").read_text())["state"]
            == "succeeded"
        )

    assert json.loads(manifest_path.read_text()).get("runtime_processes", {}) == {}
