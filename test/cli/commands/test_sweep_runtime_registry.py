import io
import json
import shutil
import subprocess
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter import Parameters, save_parameter
from chipcompiler.project import create_project_manifest
from chipcompiler.project.locking import flock_file
from chipcompiler.project.process_control import reconcile_process
from chipcompiler.project.runtime_processes import RuntimeProcessError


@pytest.fixture
def sweep_project(create_cli_project, capsys):
    project = Path(create_cli_project())
    create_project_manifest(project, "Sweep", "gcd")
    exit_code = cli_main.run(
        [
            "sweep",
            "create",
            "--project",
            str(project),
            "--name",
            "registry",
            "--param",
            "floorplan.core_util=0.6",
        ]
    )
    assert exit_code == 0
    capsys.readouterr()
    return project


@pytest.fixture
def candidate_cli(monkeypatch, flow_mocks):
    calls = []
    runtime = SimpleNamespace(probe=False)

    def invoke(command, **kwargs):
        assert command[1:3] == ["-m", "chipcompiler.cli.main"]
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            if runtime.probe and command[3] == "run":
                assert "--set" not in command
                project = Path(command[command.index("--project") + 1])
                workspace = Path(command[command.index("--workspace") + 1])
                try:
                    reconcile_process(project, workspace.name, None, blocking=False)
                    exit_code = 0
                except RuntimeProcessError as exc:
                    print(exc.code)
                    exit_code = 1
            else:
                exit_code = cli_main.run(command[3:])
        completed = subprocess.CompletedProcess(
            command, exit_code, stdout.getvalue(), stderr.getvalue()
        )
        calls.append(completed)
        return completed

    monkeypatch.setattr("chipcompiler.cli.experiments.operations.subprocess.run", invoke)
    return SimpleNamespace(calls=calls, flow=flow_mocks.flow, runtime=runtime)


def _run_sweep(project, capsys):
    exit_code = cli_main.run(
        ["sweep", "run", "--project", str(project), "--name", "registry", "--max-candidates", "1"]
    )
    output = capsys.readouterr().out
    assert exit_code == 0, output
    return json.loads(output)["results"][0]


@pytest.mark.parametrize("parent_registry", [None, {}, {"parent": {"run_id": "parent-run"}}])
def test_sweep_candidate_can_enter_runtime_without_inheriting_parent_processes(
    sweep_project, candidate_cli, capsys, parent_registry
):
    manifest_path = sweep_project / "project.json"
    manifest = json.loads(manifest_path.read_text())
    if parent_registry is not None:
        manifest["runtime_processes"] = parent_registry
        manifest_path.write_text(json.dumps(manifest))
    parent_before = manifest_path.read_bytes()

    candidate = _run_sweep(sweep_project, capsys)

    run = candidate_cli.calls[0]
    assert candidate["exit_code"] == 0, run.stdout + run.stderr
    assert candidate_cli.flow.instances
    candidate_manifest = Path(candidate["workspace"]).parent / "project.json"
    assert json.loads(candidate_manifest.read_text())["runtime_processes"] == {}
    assert manifest_path.read_bytes() == parent_before


@pytest.mark.parametrize("cached_result", [False, True])
@pytest.mark.parametrize("workspace_exists", [False, True])
def test_sweep_repairs_legacy_registry_and_reruns_failed_candidate(
    sweep_project, candidate_cli, capsys, cached_result, workspace_exists
):
    candidate_cli.flow.run_steps_value = False
    failed = _run_sweep(sweep_project, capsys)
    assert failed["exit_code"] != 0
    workspace = Path(failed["workspace"])
    manifest_path = workspace.parent / "project.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime_processes"] = []
    manifest_path.write_text(json.dumps(manifest))
    if workspace_exists:
        (workspace / "keep.txt").write_text("candidate data")
        (workspace / "home" / "flow.json").write_text(json.dumps({"steps": []}))
    else:
        shutil.rmtree(workspace)
    if not cached_result:
        (sweep_project / "experiments" / "registry" / "results.json").unlink()
    candidate_cli.calls.clear()
    candidate_cli.runtime.probe = workspace_exists
    candidate_cli.flow.run_steps_value = True

    candidate = _run_sweep(sweep_project, capsys)

    assert candidate_cli.calls
    assert candidate["exit_code"] == 0, candidate_cli.calls[0].stdout
    assert json.loads(manifest_path.read_text())["runtime_processes"] == {}
    if workspace_exists:
        manifest["runtime_processes"] = {}
        assert json.loads(manifest_path.read_text()) == manifest
        assert (workspace / "keep.txt").read_text() == "candidate data"


@pytest.mark.parametrize("failure", ["workspace-busy", "manifest-write"])
def test_sweep_does_not_run_or_rewrite_legacy_candidate_when_repair_fails(
    sweep_project, candidate_cli, capsys, monkeypatch, failure
):
    candidate = _run_sweep(sweep_project, capsys)
    workspace = Path(candidate["workspace"])
    manifest_path = workspace.parent / "project.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime_processes"] = []
    manifest_path.write_text(json.dumps(manifest))
    before = manifest_path.read_bytes()
    candidate_cli.calls.clear()
    if failure == "manifest-write":
        monkeypatch.setattr(
            "chipcompiler.cli.experiments.candidate_runtime.update_manifest_locked",
            lambda *_args: False,
        )
    lock = (
        flock_file(str(workspace.parent / f"{workspace.name}.lock"), blocking=False)
        if failure == "workspace-busy"
        else nullcontext()
    )
    with lock:
        exit_code = cli_main.run(
            ["sweep", "run", "--project", str(sweep_project), "--name", "registry"]
        )

    output = capsys.readouterr()
    assert exit_code == 2
    expected = "workspace is busy" if failure == "workspace-busy" else "could not repair"
    assert expected in output.out + output.err
    assert candidate_cli.calls == []
    assert manifest_path.read_bytes() == before


def test_sweep_reuses_valid_cached_candidate_without_clearing_runtime_registry(
    sweep_project, candidate_cli, capsys
):
    candidate = _run_sweep(sweep_project, capsys)
    manifest_path = Path(candidate["workspace"]).parent / "project.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime_processes"] = {"candidate_0001": {"run_id": "another-run"}}
    manifest_path.write_text(json.dumps(manifest))
    before = manifest_path.read_bytes()
    candidate_cli.calls.clear()

    assert _run_sweep(sweep_project, capsys) == candidate

    assert candidate_cli.calls == []
    assert manifest_path.read_bytes() == before


@pytest.mark.parametrize("workspace_path", ["default", "custom-name", "runs/nested workspace"])
@pytest.mark.parametrize("relative_path", [False, True])
def test_sweep_excludes_registered_workspace_directories_and_keeps_project_inputs(
    sweep_project, candidate_cli, capsys, workspace_path, relative_path
):
    workspace = sweep_project / workspace_path
    source = sweep_project / "source-workspace"
    assert (
        cli_main.run(
            ["workspace", "create", str(source), "--project", str(sweep_project), "--plain"]
        )
        == 0
    )
    capsys.readouterr()
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source, workspace)
    (workspace / "source-only.txt").write_text("source workspace")
    manifest_path = sweep_project / "project.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["workspaces"][0]["workspace_path"] = (
        workspace_path if relative_path else str(workspace)
    )
    manifest_path.write_text(json.dumps(manifest))
    inputs = sweep_project / workspace.parent.relative_to(sweep_project) / "design-input.v"
    inputs.write_text("module design_input; endmodule\n")
    parent_before = manifest_path.read_bytes()

    candidate = _run_sweep(sweep_project, capsys)

    candidate_project = Path(candidate["workspace"]).parent
    assert not (candidate_project / workspace_path).exists()
    assert (
        candidate_project / inputs.relative_to(sweep_project)
    ).read_bytes() == inputs.read_bytes()
    assert (workspace / "source-only.txt").read_text() == "source workspace"
    assert manifest_path.read_bytes() == parent_before


def test_sweep_does_not_copy_external_imported_workspace_through_a_symlink(
    sweep_project, candidate_cli, capsys
):
    workspace = sweep_project.parent / "external"
    home = workspace / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps({"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]})
    )
    assert save_parameter(
        Parameters(
            path=workspace / "home" / "params.toml",
            data={
                "pdk": "ics55",
                "design": "gcd",
                "top_module": "gcd",
                "clock": "clk",
                "_flow": {"start": "Synthesis", "end": "Synthesis"},
            },
        )
    )
    assert (
        cli_main.run(
            [
                "workspace",
                "import",
                "external-alias",
                "--path",
                str(workspace),
                "--project",
                str(sweep_project),
                "--plain",
            ]
        )
        == 0
    )
    capsys.readouterr()
    (sweep_project / "external-link").symlink_to(workspace, target_is_directory=True)
    source_before = (home / "params.toml").read_bytes()

    candidate = _run_sweep(sweep_project, capsys)

    candidate_project = Path(candidate["workspace"]).parent
    assert not (candidate_project / "external-link").exists()
    assert (home / "params.toml").read_bytes() == source_before


def test_sweep_batch_exit_does_not_hide_candidate_failure_or_allow_promotion(
    sweep_project, candidate_cli, capsys
):
    candidate_cli.flow.run_steps_value = False

    candidate = _run_sweep(sweep_project, capsys)

    assert candidate["exit_code"] != 0
    assert candidate["status"] == "failed"
    exit_code = cli_main.run(
        [
            "explore",
            "promote",
            "--project",
            str(sweep_project),
            "--name",
            "registry",
            "--candidate",
            candidate["id"],
        ]
    )
    assert exit_code == 2
    output = capsys.readouterr()
    assert "only passed candidates can be promoted" in output.out + output.err
