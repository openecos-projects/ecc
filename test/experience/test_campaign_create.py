import json
from pathlib import Path

import pytest

from ecc_experience.api import campaign_create
from ecc_experience.benchmark.manifest import load_manifest
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.process import Invocation


@pytest.fixture
def creation_spec(workspace_factory, tmp_path):
    workspace = workspace_factory("source/baseline")
    rtl = tmp_path / "source/design.v"
    rtl.write_text("module sample; endmodule")
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = {
        "pdk": {"familyId": "ics55"},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(rtl)}}
    snapshot_path.write_text(json.dumps(snapshot))
    (workspace.parent / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "design_name": "sample",
                "root_path": str(workspace.parent),
                "workspaces": [{"workspace_id": "baseline", "workspace_path": str(workspace)}],
            }
        )
    )
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "campaign_id": "generic-batch",
                "process_profile": "ics55",
                "budget": {
                    "max_concurrent_flows": 1,
                    "max_trials_per_design": 1,
                    "timeout_seconds_per_trial": 60,
                },
                "designs": [{"id": "sample", "project": "source", "workspace": "baseline"}],
            }
        )
    )
    return spec, workspace


@pytest.fixture
def preparation_commands(monkeypatch):
    commands = []

    def invoke(self, arguments, *, deadline):
        commands.append(arguments)
        if arguments[0] == "init":
            project = Path(arguments[1])
            project.mkdir()
            (project / "ecc.toml").write_text("example defaults")
        stdout = self.output / f"stdout-{len(commands)}.log"
        stderr = self.output / f"stderr-{len(commands)}.log"
        stdout.write_text("")
        stderr.write_text("")
        return Invocation(0, stdout, stderr)

    monkeypatch.setattr("ecc_experience.benchmark.create.CliRunner.invoke", invoke)
    return commands


def test_create_organizes_directory_without_running_or_mutating_source(
    creation_spec, preparation_commands, tmp_path
):
    spec, workspace = creation_spec
    from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation

    read_workspace_observation(workspace)
    before = {
        str(path): path.read_bytes() for path in workspace.parent.rglob("*") if path.is_file()
    }

    result = campaign_create(spec, tmp_path / "batch")

    assert result["eda_executed"] is False
    assert [command[:2] for command in preparation_commands] == [
        ["init", str(tmp_path / "batch/inputs/sample")],
        ["workspace", "import"],
        ["workspace", "derive"],
    ]
    manifest, _summary = load_manifest(tmp_path / "batch/campaign.json")
    assert (manifest.store, manifest.output_root, manifest.designs[0].input.path) == (
        "store",
        "runs",
        "inputs/sample",
    )
    assert {
        str(path): path.read_bytes() for path in workspace.parent.rglob("*") if path.is_file()
    } == before
    assert json.loads((tmp_path / "batch/logs/create.json").read_text())["status"] == "complete"
    assert not (tmp_path / "batch/inputs/sample/ecc.toml").exists()


@pytest.mark.parametrize("change", ["overlap", "profile", "traversal", "duplicate"])
def test_create_validates_every_source_before_writing(
    creation_spec, preparation_commands, tmp_path, change
):
    spec, workspace = creation_spec
    payload = json.loads(spec.read_text())
    destination = tmp_path / "batch"
    if change == "overlap":
        destination = workspace.parent / "batch"
    elif change == "profile":
        payload["process_profile"] = "other"
    elif change == "traversal":
        payload["designs"][0]["id"] = "../escape"
    else:
        payload["designs"].append(payload["designs"][0])
    spec.write_text(json.dumps(payload))

    with pytest.raises(ExperienceError):
        campaign_create(spec, destination)

    assert not destination.exists()
    assert preparation_commands == []


def test_failed_preparation_keeps_evidence_without_publishing_manifest(
    creation_spec, tmp_path, monkeypatch
):
    spec, _workspace = creation_spec

    def fail(self, _arguments, *, deadline):
        return Invocation(1, self.output / "stdout", self.output / "stderr")

    monkeypatch.setattr("ecc_experience.benchmark.create.CliRunner.invoke", fail)
    with pytest.raises(ExperienceError, match="preparation failed"):
        campaign_create(spec, tmp_path / "batch")

    assert not (tmp_path / "batch/campaign.json").exists()
    assert json.loads((tmp_path / "batch/logs/create.json").read_text())["status"] == "failed"
