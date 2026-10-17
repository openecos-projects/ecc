import json
import subprocess
import sys
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
        start_step="Synth",
        end_step="Harden",
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
