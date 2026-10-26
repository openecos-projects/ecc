import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.api import dse_plan, dse_run
from ecc_experience.dse import execute2
from ecc_experience.models import ExperienceError
from test.experience import test_dse as fixtures

dse_project = fixtures.dse_project
version2_spec = fixtures.version2_spec
simulated_cli = fixtures.simulated_cli


def _parallel_spec(path):
    payload = json.loads(path.read_text())
    payload["execution"] = {"max_concurrent": 2}
    path.write_text(json.dumps(payload))


def test_version2_parallel_batches_keep_independent_attempts_and_replay(
    dse_project, simulated_cli, version2_spec
):
    workspace, store, path = dse_project
    _parallel_spec(version2_spec)
    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    assert frozen["execution"] == {"max_concurrent": 2}

    first = dse_run(path, path.parent / "parallel")
    second = dse_run(path, path.parent / "replayed")

    assert first["status"] == second["status"] == "complete", first
    assert first["max_concurrent"] == second["max_concurrent"] == 2
    assert first["execution_batches"] == second["execution_batches"] == 2
    assert [item["candidate_id"] for item in first["trials"]] == [
        item["candidate_id"] for item in second["trials"]
    ]
    assert [item["parameters"] for item in first["trials"]] == [
        item["parameters"] for item in second["trials"]
    ]
    attempts = [
        *first["trials"],
        first["full_validation"],
        first["fresh_validation"],
    ]
    assert len({item["workspace_id"] for item in attempts}) == len(attempts)
    assert len({item["run_id"] for item in attempts}) == len(attempts)
    assert len([item for item in simulated_cli if item[0] == "run"]) == 10


def test_parallel_concurrency_cannot_exceed_frozen_plan(dse_project, simulated_cli, version2_spec):
    workspace, store, path = dse_project
    _parallel_spec(version2_spec)
    dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    with pytest.raises(ExperienceError, match="concurrency"):
        dse_run(path, path.parent / "output", max_concurrent=3)


def test_parallel_batch_passes_observed_concurrency_to_trial_runner(
    dse_project, simulated_cli, version2_spec, monkeypatch
):
    workspace, store, path = dse_project
    _parallel_spec(version2_spec)
    dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    original = execute2.execute_trial
    observed = []

    def capture(*args, **kwargs):
        observed.append(kwargs.get("concurrency"))
        return original(*args, **kwargs)

    monkeypatch.setattr(execute2, "execute_trial", capture)
    result = dse_run(path, path.parent / "output")

    assert result["status"] == "complete"
    assert {"current_flows": 2, "max_concurrent": 2} in observed
    assert {"current_flows": 1, "max_concurrent": 1} in observed


def test_resume_preserves_declared_concurrency(dse_project, simulated_cli, version2_spec):
    workspace, store, path = dse_project
    _parallel_spec(version2_spec)
    dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    dse_run(path, path.parent / "output", max_concurrent=1)
    with pytest.raises(ExperienceError, match="concurrency"):
        dse_run(path, path.parent / "output", resume=True, max_concurrent=2)


def test_dse_cli_exposes_bounded_parallel_execution(dse_project, simulated_cli, version2_spec):
    workspace, store, path = dse_project
    _parallel_spec(version2_spec)
    dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    output = path.parent / "cli-parallel"

    result = CliRunner().invoke(
        app,
        [
            "experience",
            "dse",
            "run",
            "--plan",
            str(path),
            "--output",
            str(output),
            "--max-concurrent",
            "2",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["max_concurrent"] == 2
