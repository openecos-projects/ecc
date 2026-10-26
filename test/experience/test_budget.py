import json

from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.files import case_identity
from ecc_experience.knowledge.budget import resource_budget, validate_budget_coverage
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import (
    ExperienceCase,
    InputDigest,
    SourceObservation,
    ToolchainIdentity,
)


def make_case(
    root,
    name,
    *,
    elapsed=10.0,
    peak=1000,
    status="available",
    outcome="success",
    concurrency=1,
    process="pdk",
    runtime="runtime",
):
    source = SourceObservation(
        workspace_root=str(root),
        workspace_id=name,
        workspace_revision=1,
        snapshot_schema=4,
        snapshot_digest="a" * 64,
        cause=None,
        observation_type="committed_import",
        attempt_id=name,
    )
    facts = {
        "workspaceSpec": {"design": {"topModule": name}},
        "flow": {
            "steps": [
                {
                    "name": "place",
                    "tool": "dreamplace",
                    "state": "Success",
                    "resource_observation": {
                        "schema_version": 1,
                        "status": status,
                        "outcome": {"status": outcome},
                        "elapsed_seconds": elapsed,
                        "peak_rss_bytes": peak,
                        "host": {
                            "cpu_model": "test-cpu",
                            "logical_cores": 8,
                            "total_memory_bytes": 64 * 1024**3,
                        },
                        "concurrency": {"max_concurrent": concurrency},
                        "scope": "isolated_worker_process_tree",
                    },
                }
            ]
        },
    }
    case = ExperienceCase(
        schema_version=2,
        case_id="case-" + "0" * 64,
        collector_version="test",
        collected_at="2026-01-01T00:00:00Z",
        source=source,
        input_content_fingerprint=f"input-{name}",
        design_fingerprint=f"design-{name}",
        process_fingerprint=process,
        toolchain=ToolchainIdentity(runtime_fingerprint=runtime, status="available"),
        inputs=[InputDigest(input_id="rtl", role="rtl", status="available", sha256="a" * 64)],
        facts=facts,
        evidence=[],
        limitations=[],
        parameter_evidence="configured",
        validation_scope="committed_observation",
    )
    case = case.model_copy(update={"case_id": case_identity(case.model_dump())})
    return case


def test_budget_uses_scoped_success_samples_and_p90(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    query = make_case(tmp_path, "query")
    store.put(query, {})
    for index in range(10):
        store.put(make_case(tmp_path, f"sample-{index}", elapsed=10 + index, peak=1000 + index), {})
    store.put(make_case(tmp_path, "partial", status="partial"), {})
    store.put(make_case(tmp_path, "timeout", outcome="timeout"), {})
    store.put(make_case(tmp_path, "other-concurrency", concurrency=2), {})
    store.put(make_case(tmp_path, "other-process", process="other"), {})
    store.put(make_case(tmp_path, "other-runtime", runtime="other"), {})

    result = resource_budget(query.case_id, store.root, through_step="place")

    assert result["status"] == "available"
    assert result["samples"] == 10
    assert result["elapsed_seconds"]["min"] == 10
    assert result["elapsed_seconds"]["p50"] == 14.5
    assert result["elapsed_seconds"]["p90"] == 18.1
    assert result["risk"]["oom_or_timeout"] == 1
    assert result["risk"]["partial"] == 1


def test_budget_below_minimum_is_explicitly_insufficient(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    query = make_case(tmp_path, "query")
    store.put(query, {})
    for index in range(7):
        store.put(make_case(tmp_path, f"sample-{index}"), {})

    result = resource_budget(query.case_id, store.root, through_step="place")

    assert result["status"] == "insufficient_evidence"
    assert result["samples"] == 7
    assert result["elapsed_seconds"]["p90"] is None


def test_budget_host_and_concurrency_scope_do_not_mix(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    query = make_case(tmp_path, "query")
    store.put(query, {})
    for index in range(8):
        store.put(make_case(tmp_path, f"sample-{index}", concurrency=2), {})

    result = resource_budget(query.case_id, store.root, through_step="place", concurrency=1)

    assert result["status"] == "unknown"
    assert result["samples"] == 0


def test_heldout_budget_coverage_below_target_returns_unknown(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    query = make_case(tmp_path, "query")
    store.put(query, {})
    for index in range(10):
        case = make_case(tmp_path, f"sample-{index}", elapsed=10, peak=1000)
        store.put(case, {})
    validation_ids = []
    for index in range(3):
        case = make_case(tmp_path, f"heldout-{index}", elapsed=1000, peak=1000)
        store.put(case, {})
        validation_ids.append(case.case_id)

    result = resource_budget(
        query.case_id,
        store.root,
        through_step="place",
        validation_case_ids=validation_ids,
    )

    assert result["status"] == "unknown"
    assert result["validation"]["coverage"] < 0.8
    assert (
        validate_budget_coverage(
            query.case_id,
            store.root,
            through_step="place",
            case_ids=validation_ids,
        )["status"]
        == "available"
    )


def test_heldout_budget_rejects_scope_mismatch_and_non_success_outcomes(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    query = make_case(tmp_path, "query")
    store.put(query, {})
    for index in range(8):
        store.put(make_case(tmp_path, f"sample-{index}", elapsed=10, peak=1000), {})
    good = make_case(tmp_path, "heldout-good", elapsed=10, peak=1000)
    wrong_scope = make_case(tmp_path, "heldout-scope", concurrency=2)
    failed = make_case(tmp_path, "heldout-failed", outcome="failed")
    for case in (good, wrong_scope, failed):
        store.put(case, {})

    report = validate_budget_coverage(
        query.case_id,
        store.root,
        through_step="place",
        case_ids=[good.case_id, wrong_scope.case_id, failed.case_id],
    )

    assert report["status"] == "available"
    assert report["samples"] == 1
    assert report["unavailable"] == 2
    assert report["rows"][0]["case_id"] == good.case_id


def test_budget_cli_reports_scoped_estimate(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    query = make_case(tmp_path, "query")
    store.put(query, {})
    for index in range(8):
        store.put(make_case(tmp_path, f"sample-{index}"), {})

    result = CliRunner().invoke(
        app,
        [
            "experience",
            "budget",
            query.case_id,
            "--store",
            str(store.root),
            "--through-step",
            "place",
            "--min-samples",
            "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)[0]
    assert payload["status"] == "available"
    assert payload["samples"] == 8
