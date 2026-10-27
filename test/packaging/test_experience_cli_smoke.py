import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chipcompiler.cli.app import app


def test_smoke_checks_the_real_cli_contract_and_preserves_source(tmp_path, monkeypatch):
    path = Path(__file__).parents[2] / "packaging/experience_cli_smoke.py"
    specification = importlib.util.spec_from_file_location("experience_cli_smoke", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    project = tmp_path / "generic project"
    home = project / "workspace/home"
    home.mkdir(parents=True)
    (project / "ecc.toml").write_text("")
    flow = home / "flow.json"
    flow.write_text(
        json.dumps(
            {"steps": [{"name": "STA", "state": "Success"}, {"name": "Finish", "state": "Success"}]}
        )
    )
    original = {
        str(item.relative_to(project)): item.read_bytes()
        for item in project.rglob("*")
        if item.is_file()
    }
    runner = CliRunner()

    def invoke(command, **kwargs):
        result = runner.invoke(app, command[1:])
        return subprocess.CompletedProcess(command, result.exit_code, result.stdout, result.stderr)

    monkeypatch.setattr(module.subprocess, "run", invoke)
    result = module.run_smoke(Path("ecc"), project, "workspace", tmp_path / "output")
    assert result["status"] == "pass"
    assert {
        str(item.relative_to(project)): item.read_bytes()
        for item in project.rglob("*")
        if item.is_file() and item.name != "workspace.lock"
    } == original
    assert not (home / "engineering-snapshot.json").exists()
    assert (tmp_path / "output/verify-corrupt.exit").read_text() == "6"
    assert (tmp_path / "output/quality.exit").read_text() == "7"
    assert (tmp_path / "output/quality-corrupt.exit").read_text() == "6"
    prefix = json.loads((tmp_path / "output/features-prefix.stdout.json").read_text())[0]
    assert [item["step"] for item in prefix["steps"]] == ["STA"]
    assert (tmp_path / "output/features-corrupt.exit").read_text() == "6"
    for label in (
        "match-invalid-release",
        "dse-invalid-plan",
        "study-invalid-spec",
        "study-invalid-report",
    ):
        assert (tmp_path / f"output/{label}.exit").read_text() == "2"


def test_real_matrix_reports_independence_without_inventing_generalization(tmp_path):
    path = Path(__file__).parents[2] / "packaging/experience_matrix_report.py"
    specification = importlib.util.spec_from_file_location("experience_matrix_report", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    for name in ("first", "second"):
        directory = tmp_path / "inputs" / name
        directory.mkdir(parents=True)
        records = {
            "show": {
                "case_id": name,
                "input_content_fingerprint": "same-rtl",
                "facts": {"qorSnapshotExtension": {"status": "available", "score": 10}},
            },
            "verify": {"case_id": name, "status": "pass", "integrity": "pass"},
            "features": {
                "case_id": name,
                "parameters": {"values": {"place.target_density": 0.5}},
                "steps": [
                    {
                        "step": "place",
                        "resource_observation": {
                            "status": "available",
                            "scope": "isolated_worker_process_tree",
                            "elapsed_seconds": 3.5,
                            "peak_rss_bytes": 123,
                        },
                    }
                ],
            },
        }
        for label, record in records.items():
            (directory / f"{label}.stdout.json").write_text(json.dumps([record]))
    report = module.aggregate(tmp_path / "inputs", ["first", "second"], tmp_path / "report")
    assert report["status"] == "unknown"
    assert report["independent_input_count"] == 1
    assert report["observations"][1]["duplicate_input"] is True
    assert all(item["family"] is None for item in report["observations"])
    assert report["candidate_variation"]["status"] == "unknown"
    assert report["resource_summary"]["place"]["available_count"] == 2
    assert report["resource_summary"]["place"]["scopes"] == ["isolated_worker_process_tree"]
    labeled = module.aggregate(
        tmp_path / "inputs",
        ["first", "second"],
        tmp_path / "labeled-report",
        {"first": "small", "second": "small"},
    )
    assert labeled["family_count"] == 1
    assert labeled["missing_family_designs"] == []
    missing = module.aggregate(tmp_path / "inputs", ["missing"], tmp_path / "missing-report")
    assert missing["exit_code"] == 6


def test_real_matrix_reports_candidate_variation_and_rejects_corrupt_records(tmp_path):
    path = Path(__file__).parents[2] / "packaging/experience_matrix_report.py"
    specification = importlib.util.spec_from_file_location("experience_matrix_report", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    for name, density in (("first", 0.45), ("second", 0.55)):
        directory = tmp_path / "inputs" / name
        directory.mkdir(parents=True)
        records = {
            "show": {"case_id": name, "input_content_fingerprint": "same-rtl", "facts": {}},
            "verify": {"case_id": name, "status": "pass", "integrity": "pass"},
            "features": {
                "case_id": name,
                "parameters": {"values": {"place.target_density": density}},
                "steps": [],
            },
        }
        for label, record in records.items():
            (directory / f"{label}.stdout.json").write_text(json.dumps([record]))
    report = module.aggregate(tmp_path / "inputs", ["first", "second"], tmp_path / "report")
    assert report["candidate_variation"] == {
        "status": "available",
        "input_groups": 1,
        "varied_input_groups": 1,
        "configurations_by_input": {"same-rtl": 2},
    }

    (tmp_path / "inputs/second/verify.stdout.json").write_text("not-json")
    with pytest.raises(ValueError, match="Invalid CLI observation"):
        module.aggregate(tmp_path / "inputs", ["first", "second"], tmp_path / "corrupt")


def test_packaged_dse_smoke_spec_uses_a_supported_stage_metric():
    path = Path(__file__).parents[2] / "packaging/experience_cli_smoke.py"
    specification = importlib.util.spec_from_file_location("experience_cli_smoke", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)

    spec = module._dse_spec(
        {
            "steps": [
                {"step": "Synthesis", "metrics": []},
                {
                    "step": "postFloorplan",
                    "metrics": [{"id": "core_area", "unit": "um^2", "status": "available"}],
                },
            ]
        }
    )

    assert spec is not None
    assert spec["limits"]["patience"] == "auto"
    assert spec["rungs"] == [{"through_step": "postFloorplan", "promote_count": 1}]
    assert spec["objectives"][0]["direction"] == "minimize"
    assert module._dse_spec({"steps": [{"step": "postFloorplan", "metrics": []}]}) is None


def test_packaged_dse_patience_contract_checks_the_frozen_plan(tmp_path, monkeypatch):
    path = Path(__file__).parents[2] / "packaging/experience_cli_smoke.py"
    specification = importlib.util.spec_from_file_location("experience_cli_smoke", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    output = tmp_path / "output"
    output.mkdir()

    def invoke(_binary, arguments, _output, label, _expected):
        assert label == "dse-auto-patience"
        plan = Path(arguments[arguments.index("--output") + 1])
        plan.write_text(
            json.dumps(
                {
                    "limits": {"patience": 6},
                    "patience_resolution": {
                        "mode": "auto",
                        "resolved": 6,
                        "screening_trials": 7,
                    },
                }
            )
        )
        return [{"plan": str(plan.resolve())}]

    monkeypatch.setattr(module, "_invoke", invoke)
    module._dse_patience_contract(
        Path("ecc"),
        output,
        tmp_path / "store",
        tmp_path / "project",
        "default",
        {
            "steps": [
                {
                    "step": "postFloorplan",
                    "metrics": [{"id": "core_area", "unit": "um^2", "status": "available"}],
                }
            ]
        },
    )
    assert (output / "dse-auto-patience-plan.json").is_file()


def test_ci_keeps_experience_checks_manual_and_non_blocking():
    workflow = yaml.safe_load(
        (Path(__file__).parents[2] / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    trigger = workflow.get(True, workflow.get("on", {}))
    assert trigger["workflow_dispatch"]["inputs"]["run-experience"]["default"] is False
    packaged_steps = workflow["jobs"]["e2e-packaged-flow"]["steps"]
    experience_step = next(
        step
        for step in packaged_steps
        if step.get("name") == "Verify packaged experience collection"
    )
    assert experience_step["continue-on-error"] is True
    assert "inputs.run-experience" in experience_step["if"]
    matrix_job = workflow["jobs"]["experience-design-matrix"]
    assert "inputs.run-experience" in matrix_job["if"]
    assert matrix_job["continue-on-error"] is True
