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
            no_wait=True, run_id=str(uuid4()),
        )
        print("ready", flush=True)
        with managed_run_process(
            request, project, "baseline", workspace, workspace_path=str(project / "baseline")
        ) as entry:
            assert read_runtime_process(project, "baseline") == entry
            assert workspace._ecc_run_id == request.run_id
            print("registered", flush=True)
        assert not hasattr(workspace, "_ecc_run_id")
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


def _setup_interrupted_workspace(tmp_path: Path):
    import os
    from uuid import uuid4

    from chipcompiler.project.runtime_processes import (
        ProcessIdentity,
        boot_id,
        build_runtime_entry,
        default_log_path,
        host_id,
        register_runtime_process,
    )

    workspace = tmp_path / "baseline"
    home = workspace / "home"
    home.mkdir(parents=True)
    dead_run_id = str(uuid4())
    flow_path = home / "flow.json"
    flow_path.write_text(
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
                                "run_id": dead_run_id,
                                "started_at": 1.0,
                            }
                        },
                    }
                ],
            }
        )
    )
    manifest = build_manifest_document(
        str(tmp_path),
        design_name="gcd",
        base_design={},
        workspace_id="baseline",
        workspace_path="baseline",
        start_step="synthesis",
        end_step="harden",
    )
    (tmp_path / "project.json").write_text(json.dumps(manifest))
    dead_entry = build_runtime_entry(
        tmp_path,
        workspace,
        run_id=dead_run_id,
        runtime_id="ecc-dead",
        log_path=default_log_path(dead_run_id),
        identity=ProcessIdentity(os.getpid(), os.getpid(), "0", boot_id(), host_id()),
        started_at=1.0,
    )
    register_runtime_process(tmp_path, "baseline", dead_entry)
    return workspace, home, flow_path, dead_entry


def _run_managed_subprocess(
    project: Path, *, fail_recovery: bool = False
) -> subprocess.CompletedProcess[str]:
    import os

    script = dedent("""
        import json
        import sys
        from pathlib import Path
        from types import SimpleNamespace
        from uuid import uuid4

        import chipcompiler.engine.interrupted_run as interrupted_run
        from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions, RunInput
        from chipcompiler.cli.project.run_process import managed_run_process

        project = Path(sys.argv[1])
        fail_recovery = sys.argv[2] == "1"
        if fail_recovery:
            interrupted_run.json_write = lambda *_args, **_kwargs: False
        workspace_dir = project / "baseline"
        request = RunInput(
            output=OutputOptions(),
            project=ProjectOptions(project=str(project)),
            run_id=str(uuid4()),
        )
        with managed_run_process(
            request, project, "baseline", SimpleNamespace(), workspace_path=str(workspace_dir)
        ):
            step = json.loads((workspace_dir / "home" / "flow.json").read_text())["steps"][0]
            assert step["state"] == "Incomplete"
            assert "execution" not in step["info"]
    """)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3]))
    return subprocess.run(
        [sys.executable, "-c", script, str(project), "1" if fail_recovery else "0"],
        capture_output=True,
        text=True,
        start_new_session=True,
        env=env,
        timeout=10,
    )


def test_managed_run_process_reaps_dead_local_entry_and_recovers_step(tmp_path):
    _setup_interrupted_workspace(tmp_path)
    proc = _run_managed_subprocess(tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_managed_run_process_preserves_stale_entry_when_recovery_fails(tmp_path):
    from chipcompiler.project.runtime_processes import RuntimeProcessError, read_runtime_process

    _workspace, _home, flow_path, dead_entry = _setup_interrupted_workspace(tmp_path)
    proc_fail = _run_managed_subprocess(tmp_path, fail_recovery=True)
    assert proc_fail.returncode != 0
    assert "failed to save recovered flow state" in proc_fail.stderr
    assert read_runtime_process(tmp_path, "baseline") == dead_entry
    step_before_retry = json.loads(flow_path.read_text())["steps"][0]
    assert step_before_retry["state"] == "Ongoing"
    assert "execution" in step_before_retry["info"]

    proc_retry = _run_managed_subprocess(tmp_path)
    assert (proc_retry.returncode, proc_retry.stdout, proc_retry.stderr) == (0, "", "")
    with pytest.raises(RuntimeProcessError, match="No runtime process"):
        read_runtime_process(tmp_path, "baseline")
    assert json.loads((tmp_path / "project.json").read_text()).get("runtime_processes", {}) == {}
