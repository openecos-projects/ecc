import json
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.benchmark.archive import create as archive_campaign
from ecc_experience.benchmark.effect import compare
from ecc_experience.benchmark.matrix import aggregate
from ecc_experience.benchmark.plan import materialize
from ecc_experience.benchmark.readiness import check
from ecc_experience.benchmark.round_summary import summarize
from ecc_experience.benchmark.spec import validate
from ecc_experience.models import ExperienceError


def _read_member(archive, item):
    stream = archive.extractfile(item)
    assert stream is not None
    return stream.read()


def _observation(root: Path, name: str, fingerprint: str, density: float) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    records = {
        "show": {
            "case_id": f"case-{name}",
            "input_content_fingerprint": fingerprint,
            "process_fingerprint": "process",
            "facts": {
                "experienceExecutionContext": {"runtime": {"ecc": "test"}},
                "qorSnapshotExtension": {"status": "available", "score": density * 100},
            },
        },
        "verify": {"case_id": f"case-{name}", "status": "pass", "integrity": "pass"},
        "features": {
            "case_id": f"case-{name}",
            "parameters": {"values": {"place.target_density": density}},
            "steps": [
                {
                    "step": "place",
                    "resource_observation": {
                        "status": "available",
                        "scope": "isolated_worker_process_tree",
                        "elapsed_seconds": 2.0,
                        "peak_rss_bytes": 100,
                    },
                }
            ],
        },
    }
    for label, payload in records.items():
        (directory / f"{label}.stdout.json").write_text(json.dumps([payload]), encoding="utf-8")


def test_matrix_and_readiness_keep_insufficient_evidence_unknown(tmp_path):
    inputs = tmp_path / "observations"
    _observation(inputs, "first", "input-first", 0.45)
    _observation(inputs, "second", "input-second", 0.55)
    matrix = aggregate(
        inputs,
        ["first", "second"],
        tmp_path / "matrix",
        {"first": "logic", "second": "logic"},
    )
    assert matrix["status"] == "unknown"
    assert matrix["candidate_variation"]["status"] == "unknown"
    readiness = check(tmp_path / "matrix", tmp_path / "readiness")
    assert readiness["status"] == "unknown"
    assert readiness["exit_code"] == 7
    assert readiness["checks"]["independent_designs"]["status"] == "unknown"


def test_readiness_passes_only_with_declared_independent_families_and_trials(tmp_path):
    observations = [
        {
            "design": f"design-{index}",
            "verification": "pass",
            "integrity": "pass",
            "qor_score": 80 + index,
            "runtime_recorded": True,
            "runtime_fingerprint": "runtime",
            "process_fingerprint": "process",
            "input_content_fingerprint": f"input-{index}",
            "parameters": {"density": 0.4 + index / 10},
            "family": "family-a" if index < 2 else "family-b",
        }
        for index in range(3)
    ]
    payload = {
        "schema": "ecc-experience-ci-design-matrix/1",
        "status": "unknown",
        "observed_design_count": 3,
        "independent_input_count": 3,
        "family_count": 2,
        "candidate_variation": {
            "configurations_by_input": {"input-0": 2},
        },
        "observations": observations,
    }
    matrix = tmp_path / "matrix.json"
    matrix.write_text(json.dumps(payload), encoding="utf-8")
    result = check(matrix, tmp_path / "readiness")
    assert result["status"] == "pass"
    assert result["exit_code"] == 0


def test_readiness_rejects_mixed_runtime_fingerprints(tmp_path):
    matrix = tmp_path / "matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "schema": "ecc-experience-ci-design-matrix/1",
                "status": "unknown",
                "observed_design_count": 2,
                "independent_input_count": 2,
                "family_count": 2,
                "candidate_variation": {"configurations_by_input": {"same": 2}},
                "observations": [
                    {
                        "verification": "pass",
                        "integrity": "pass",
                        "qor_score": 1,
                        "runtime_recorded": True,
                        "runtime_fingerprint": "runtime-a",
                        "process_fingerprint": "process",
                    },
                    {
                        "verification": "pass",
                        "integrity": "pass",
                        "qor_score": 2,
                        "runtime_recorded": True,
                        "runtime_fingerprint": "runtime-b",
                        "process_fingerprint": "process",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    result = check(matrix, tmp_path / "readiness")
    assert result["status"] == "unknown"
    assert result["checks"]["runtime"]["status"] == "unknown"


def test_campaign_archive_is_deterministic_and_redacts_paths(tmp_path):
    root = tmp_path / "campaign"
    (root / "inputs" / "design-a").mkdir(parents=True)
    (root / "store").mkdir()
    (root / "runs").mkdir()
    manifest = {
        "schema_version": 1,
        "campaign_id": "archive-test",
        "process_profile": "ics55",
        "store": "store",
        "output_root": "runs",
        "mode": "baseline",
        "budget": {
            "max_concurrent_flows": 1,
            "max_trials_per_design": 1,
            "timeout_seconds_per_trial": 60,
        },
        "designs": [
            {
                "id": "design-a",
                "input": {"kind": "ecc-project", "path": "inputs/design-a"},
                "workspace": "baseline",
                "labels": [],
                "evaluation_group": "family-a",
            }
        ],
    }
    manifest_path = root / "campaign.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = root / "reports"
    report.mkdir()
    (report / "matrix.json").write_text(
        json.dumps({"schema": "ecc-experience-campaign-report/1", "rows": [{"case_id": "case-1"}]}),
        encoding="utf-8",
    )
    (root / "runs" / "campaign-run.json").write_text(
        json.dumps({"directory": "/private/path", "case_id": "case-1"}), encoding="utf-8"
    )
    first = archive_campaign(manifest_path, report, tmp_path / "first.tar.gz")
    second = archive_campaign(manifest_path, report, tmp_path / "second.tar.gz")
    assert first["case_ids"] == ["case-1"]
    assert first["archive_sha256"] == second["archive_sha256"]
    with tarfile.open(tmp_path / "first.tar.gz", "r:gz") as archive:
        contents = {item.name: _read_member(archive, item) for item in archive if item.isfile()}
    assert b"<path-redacted>" in contents["campaign/campaign-run.json"]


def test_campaign_effect_compares_same_design_trials(tmp_path):
    report = {
        "schema": "ecc-experience-campaign-report/1",
        "campaign_id": "effect-test",
        "rows": [
            {
                "design_id": "design-a",
                "trial_id": "baseline",
                "status": "pass",
                "verification": "pass",
                "integrity": "pass",
                "qor_score": 80,
                "parameters": {"density": 0.4},
                "steps": [],
                "signoff": {},
            },
            {
                "design_id": "design-a",
                "trial_id": "candidate",
                "status": "pass",
                "verification": "pass",
                "integrity": "pass",
                "qor_score": 82,
                "parameters": {"density": 0.5},
                "steps": [],
                "signoff": {},
            },
        ],
    }
    source = tmp_path / "matrix.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    result = compare(source, tmp_path / "effect")
    assert result["status"] == "available"
    assert result["pairs"][0]["qor_delta"] == 2
    assert result["pairs"][0]["parameter_changes"]["changed"]["density"] == {
        "baseline": 0.4,
        "candidate": 0.5,
    }


def test_benchmark_spec_validation_is_execution_neutral(tmp_path):
    spec = tmp_path / "benchmark.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_id": "small-test",
                "process_profile": "ics55",
                "strategies": ["baseline", "adaptive"],
                "designs": [
                    {
                        "id": "design-a",
                        "project": "./design-a",
                        "workspace": "baseline",
                        "family": "logic",
                        "plans": {"adaptive": "plans/design-a.json"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = validate(spec)
    assert result["status"] == "valid"
    assert result["execution"] == {"mode": "serial", "eda_started": False, "plans_only": True}

    invalid = json.loads(spec.read_text())
    invalid["budget"] = {"max_concurrent_flows": 2}
    spec.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ExperienceError, match="serial"):
        validate(spec)


def test_benchmark_spec_cli_returns_json_without_starting_eda(tmp_path):
    spec = tmp_path / "benchmark.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_id": "cli-test",
                "process_profile": "ics55",
                "strategies": ["baseline"],
                "designs": [
                    {
                        "id": "design-a",
                        "project": "./design-a",
                        "workspace": "baseline",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        ["experience", "campaign", "benchmark", "validate", "--spec", str(spec), "--json"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["execution"]["eda_started"] is False


def test_benchmark_plan_materializes_commands_and_matrix_inputs(tmp_path):
    project = tmp_path / "design-a"
    project.mkdir()
    plan = tmp_path / "plans" / "design-a.json"
    plan.parent.mkdir()
    plan.write_text("{}", encoding="utf-8")
    spec = tmp_path / "benchmark.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_id": "plan-test",
                "process_profile": "ics55",
                "strategies": ["baseline", "adaptive"],
                "designs": [
                    {
                        "id": "design-a",
                        "project": "./design-a",
                        "workspace": "baseline",
                        "family": "logic",
                        "plans": {"adaptive": "plans/design-a.json"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = materialize(spec, tmp_path / "prepared")
    assert result["status"] == "ready"
    assert result["exit_code"] == 0
    assert json.loads((tmp_path / "prepared/expected-designs.json").read_text()) == [
        "design-a--baseline",
        "design-a--adaptive",
    ]
    assert json.loads((tmp_path / "prepared/families.json").read_text()) == {
        "design-a--baseline": "logic",
        "design-a--adaptive": "logic",
    }
    assert (
        json.loads((tmp_path / "prepared/baseline-sources.json").read_text())["designs"][0][
            "project"
        ]
        == "./design-a"
    )
    plan_payload = json.loads((tmp_path / "prepared/benchmark-plan.json").read_text())
    assert plan_payload["execution"] == {"mode": "serial", "eda_started": False, "plans_only": True}


def test_benchmark_plan_keeps_missing_strategy_plans_pending(tmp_path):
    spec = tmp_path / "benchmark.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_id": "pending-test",
                "process_profile": "ics55",
                "strategies": ["adaptive"],
                "designs": [
                    {
                        "id": "design-a",
                        "project": "./design-a",
                        "workspace": "baseline",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = materialize(spec, tmp_path / "prepared")
    assert result["status"] == "pending"
    assert result["exit_code"] == 7
    assert result["missing_plans"] == ["design-a/adaptive"]


def test_benchmark_plan_cli_preserves_pending_exit_code(tmp_path):
    spec = tmp_path / "benchmark.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_id": "cli-plan-test",
                "process_profile": "ics55",
                "strategies": ["adaptive"],
                "designs": [
                    {
                        "id": "design-a",
                        "project": "./design-a",
                        "workspace": "baseline",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        [
            "experience",
            "campaign",
            "benchmark",
            "plan",
            "--spec",
            str(spec),
            "--output",
            str(tmp_path / "prepared"),
            "--json",
        ],
    )
    assert result.exit_code == 7, result.output
    assert json.loads(result.stdout)[0]["status"] == "pending"


def test_benchmark_summary_links_artifacts_and_keeps_safe_to_apply_false(tmp_path):
    project = tmp_path / "design-a"
    project.mkdir()
    spec = tmp_path / "benchmark.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_id": "summary-test",
                "process_profile": "ics55",
                "strategies": ["baseline"],
                "designs": [
                    {
                        "id": "design-a",
                        "project": "./design-a",
                        "workspace": "baseline",
                        "family": "logic",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    prepared = tmp_path / "prepared"
    materialize(spec, prepared)
    matrix = tmp_path / "matrix"
    matrix.mkdir()
    (matrix / "matrix-report.json").write_text(
        json.dumps(
            {
                "schema": "ecc-experience-ci-design-matrix/1",
                "status": "unknown",
                "observed_design_count": 1,
                "independent_input_count": 1,
                "family_count": 1,
                "runtime_fingerprints": ["runtime"],
                "candidate_variation": {"configurations_by_input": {}},
                "observations": [],
            }
        ),
        encoding="utf-8",
    )
    readiness = tmp_path / "readiness"
    readiness.mkdir()
    (readiness / "readiness.json").write_text(
        json.dumps(
            {
                "schema": "ecc-experience-benchmark-readiness/1",
                "status": "pass",
                "exit_code": 0,
                "matrix": str(matrix.resolve()),
                "blocking_checks": [],
                "generalization_status": "ready_for_review",
            }
        ),
        encoding="utf-8",
    )
    result = summarize(prepared, matrix, readiness, tmp_path / "summary")
    assert result["status"] == "pass"
    assert result["exit_code"] == 0
    assert result["safe_to_apply"] is False
    assert len(result["artifacts"]) == 3
    assert (tmp_path / "summary/benchmark-summary.md").is_file()


def test_benchmark_summary_rejects_tampered_plan(tmp_path):
    plan = tmp_path / "plan.json"
    payload = {
        "schema": "ecc-experience-benchmark-plan/1",
        "plan_sha256": "bad",
        "benchmark_id": "tampered",
    }
    plan.write_text(json.dumps(payload), encoding="utf-8")
    for name, schema in (
        ("matrix", "ecc-experience-ci-design-matrix/1"),
        ("readiness", "ecc-experience-benchmark-readiness/1"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        (directory / ("matrix-report.json" if name == "matrix" else "readiness.json")).write_text(
            json.dumps({"schema": schema}), encoding="utf-8"
        )
    with pytest.raises(ExperienceError, match="fingerprint"):
        summarize(plan, tmp_path / "matrix", tmp_path / "readiness", tmp_path / "summary")
