import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from chipcompiler.cli.experiments import pareto


@pytest.fixture
def sweep(tmp_path, monkeypatch):
    root = tmp_path / "experiments/example"
    root.mkdir(parents=True)
    candidates = [
        {"id": identity, "parameters": {"floorplan.core_util": "0.35"}}
        for identity in ("candidate_0001", "candidate_0002", "candidate_0003")
    ]
    (root / "sweep.json").write_text(json.dumps({"candidates": candidates}))
    rows = []
    for candidate in candidates:
        workspace = root / "candidates" / candidate["id"] / "project" / candidate["id"]
        (workspace / "home").mkdir(parents=True)
        (workspace / "home/engineering-snapshot.json").write_text("{}")
        rows.append(
            {
                "id": candidate["id"],
                "workspace": str(workspace),
                "exit_code": 0,
                "status": "passed",
                "parameters": candidate["parameters"],
            }
        )
    (root / "results.json").write_text(json.dumps({"results": rows}))

    def snapshot(workspace):
        score = 90.0 if workspace.name.endswith("1") else 85.0
        return {
            "flow": {"steps": [{"name": "sta", "tool": "ecc", "state": "Success"}]},
            "checklist": {"status": "ready", "checklist": [{"step": "sta", "state": "pass"}]},
            "workspaceSpec": {"parameters": {"floorplan.core_util": 0.35}},
            "qorSnapshotExtension": {"status": "available", "score": score},
            "artifacts": [],
        }

    def command(_project, workspace, command):
        if workspace.name.endswith("3"):
            return 7, [{"signoff": "check", "status": "unknown"}]
        return 0, [
            {"signoff": "check", "status": "pass"},
            *[
                {"gate": gate, "violation_count": 0}
                for gate in ("drc_clean", "lvs_clean", "sta_setup_clean", "sta_hold_clean")
            ],
        ]

    monkeypatch.setattr(pareto, "read_engineering_snapshot_from_directory", snapshot)
    monkeypatch.setattr(pareto, "_json_command", command)
    return tmp_path, root


def test_front_rechecks_signoff_instead_of_trusting_cached_success(sweep):
    project, _root = sweep
    report = pareto.sweep_pareto(project, "example", ["qor_score:score:maximize"])
    assert [row["id"] for row in report["front"]] == ["candidate_0001"]
    assert [row["candidate"] for row in report["excluded"]] == ["candidate_0003"]
    assert report["safe_to_apply"] is False
    assert pareto.select_front(report, None, None) is None
    with pytest.raises(ValueError, match="front"):
        pareto.select_front(report, "candidate_0002", None)
    assert pareto.select_front(report, None, "1") == "candidate_0001"


def test_pareto_cli_exports_without_implicitly_selecting(sweep):
    project, root = sweep
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "explore",
            "promote",
            "--project",
            str(project),
            "--name",
            "example",
            "--pareto",
            "--objective",
            "qor_score:score:maximize",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (root / "pareto.json").exists()
    assert not (root / "winner.json").exists()
    result = runner.invoke(
        app,
        [
            "explore",
            "promote",
            "--project",
            str(project),
            "--name",
            "example",
            "--pareto",
            "--objective",
            "qor_score:score:maximize",
            "--candidate",
            "candidate_0001",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads((root / "winner.json").read_text())["candidate"] == "candidate_0001"


@pytest.mark.parametrize(
    "objective", ["invalid", "qor_score:score:minimize", "core_area:ns:minimize"]
)
def test_objective_contract_rejects_unknown_units_and_polarity(sweep, objective):
    with pytest.raises(ValueError):
        pareto.sweep_pareto(sweep[0], "example", [objective])
