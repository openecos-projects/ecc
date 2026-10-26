import json

from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.files import case_identity
from ecc_experience.knowledge.index import build_index, filter_case_ids, index_status
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceCase, InputDigest, SourceObservation, ToolchainIdentity


def _case(root, name, *, input_fingerprint, process="process-a"):
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
        "flow": {
            "steps": [
                {
                    "name": "Synthesis",
                    "tool": "yosys",
                    "state": "Success",
                    "resource_observation": {
                        "status": "available",
                        "scope": "isolated_worker_process_tree",
                        "host": {"cpu_model": "test-cpu"},
                        "concurrency": {"max_concurrent": 1},
                    },
                }
            ]
        },
        "qorSnapshotExtension": {"status": "available", "score": 90.0},
    }
    case = ExperienceCase(
        schema_version=2,
        case_id="case-" + "0" * 64,
        collector_version="test",
        collected_at="2026-01-01T00:00:00Z",
        source=source,
        input_content_fingerprint=input_fingerprint,
        design_fingerprint=f"design-{name}",
        process_fingerprint=process,
        toolchain=ToolchainIdentity(runtime_fingerprint="runtime", status="available"),
        inputs=[InputDigest(input_id="rtl", role="rtl", status="available", sha256="a" * 64)],
        facts=facts,
        evidence=[],
        limitations=[],
        parameter_evidence="configured",
        validation_scope="committed_observation",
    )
    return case.model_copy(update={"case_id": case_identity(case.model_dump())})


def test_index_prefilter_and_damage_fallback_are_conservative(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    first = _case(tmp_path, "first", input_fingerprint="input-a")
    second = _case(tmp_path, "second", input_fingerprint="input-b", process="process-b")
    store.put(first, {})
    store.put(second, {})

    built = build_index(store.root)
    assert built["status"] == "pass"
    assert index_status(store.root)["status"] == "valid"

    ids = [first.case_id, second.case_id]
    selected, status = filter_case_ids(store.root, ids, input_fingerprint="input-a")
    assert selected == [first.case_id]
    assert status["status"] == "used"
    selected, _ = filter_case_ids(store.root, ids, process_fingerprint="process-b")
    assert selected == [second.case_id]

    index_path = store.root / "index/cases.json"
    index_path.write_text("{")
    selected, status = filter_case_ids(store.root, ids, input_fingerprint="input-a")
    assert selected == ids
    assert status["status"] == "invalid"


def test_index_cli_builds_and_reports_status(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    case = _case(tmp_path, "first", input_fingerprint="input-a")
    store.put(case, {})
    runner = CliRunner()

    built = runner.invoke(
        app, ["experience", "index", "build", "--store", str(store.root), "--json"]
    )
    assert built.exit_code == 0, built.output
    assert json.loads(built.stdout)[0]["case_count"] == 1

    status = runner.invoke(
        app, ["experience", "index", "status", "--store", str(store.root), "--json"]
    )
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout)[0]["status"] == "valid"
