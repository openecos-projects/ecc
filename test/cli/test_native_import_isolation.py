import subprocess
import sys
from pathlib import Path


def test_parent_cli_and_flows_do_not_import_native_modules():
    repository = Path(__file__).parents[2]
    script = r"""
import sys
import tempfile

class NativeImportBlocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in {"klayout", "ecc_tools_bin"}:
            raise ModuleNotFoundError(f"blocked native import: {fullname}")
        return None

sys.meta_path.insert(0, NativeImportBlocker())

from chipcompiler.cli.app import app
from chipcompiler.cli.core.types import CommandContext, OutputMode
from chipcompiler.cli.rendering import progress
from chipcompiler.data import EccStep, Workspace
from chipcompiler.engine import step_execution
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.step_execution import StepExecutionResult


def fake_worker(*_args, **_kwargs):
    return StepExecutionResult(
        error=None,
        elapsed_seconds=0.0,
        peak_memory_mb=0.0,
        runtime="0:0:0",
    )


def make_flow(directory):
    workspace = Workspace(directory=directory)
    workspace.flow.path = directory / "flow.json"
    workspace.flow.data = {"steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}]}
    flow = EngineFlow(workspace)
    flow.workspace_steps = [EccStep(name="route", directory=directory, tool="ecc")]
    flow.check_step_result = lambda **_kwargs: True
    return flow


step_execution._execute_in_worker = fake_worker
progress.event_sink_for_workspace = lambda _workspace: None

with tempfile.TemporaryDirectory() as directory:
    from pathlib import Path

    workspace_dir = Path(directory)
    assert make_flow(workspace_dir).run_steps() is True
    flow = make_flow(workspace_dir)
    context = CommandContext(
        project_dir=workspace_dir,
        project=None,
        run_dir=workspace_dir,
        run_id="default",
        output_mode=OutputMode.TEXT,
    )
    assert progress.run_flow_with_progress(flow, context, None, sys.stderr) is True

print("native-import-isolation-ok")
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "native-import-isolation-ok" in completed.stdout
