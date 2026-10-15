import json

import pytest

from chipcompiler.cli.experiments.operations import verify_sweep
from ecc_experience.files import canonical_bytes
from ecc_experience.modeling.dataset import read_dataset
from ecc_experience.modeling.dse import check_model
from ecc_experience.modeling.model import evaluate_model, publish_model, train_model
from ecc_experience.modeling.predict import advise_dataset
from ecc_experience.modeling.registry import promote, rollback, status
from ecc_experience.modeling.split import split_dataset, write_matrix
from ecc_experience.modeling.sweep import seed_sweep
from ecc_experience.modeling.validation import validate_matrix
from ecc_experience.models import ExperienceError
from test.experience.test_modeling import make_dataset, row


@pytest.fixture
def model_release(tmp_path):
    training = tmp_path / "training.json"
    heldout = tmp_path / "heldout.json"
    model = tmp_path / "model.json"
    evaluation = tmp_path / "evaluation.json"
    release = tmp_path / "release.json"
    make_dataset(training, [row(index, index + 1, f"family-{index % 2}") for index in range(6)])
    candidates = [row(index + 10, index + 1.5, f"family-{index % 2}") for index in range(4)]
    for index, item in enumerate(candidates):
        item["parameters"] = {"floorplan.core_util": 0.3 + index * 0.05, "sta.max_threads": 2}
    make_dataset(heldout, candidates)
    train_model(training, model)
    evaluate_model(model, heldout, evaluation)
    publish_model(model, evaluation, release)
    return model, heldout, release


@pytest.mark.parametrize("by", ["design", "family"])
def test_split_is_deterministic_and_never_splits_an_input(tmp_path, by):
    source = tmp_path / "data.json"
    rows = []
    for index in range(18):
        item = row(index, index + 1, f"family-{index // 6}")
        item["input_content_fingerprint"] = f"input-{index // 2}"
        rows.append(item)
    make_dataset(source, rows)
    first = tmp_path / "first"
    second = tmp_path / "second"
    result = split_dataset(source, first, by=by, seed="fixed")
    split_dataset(source, second, by=by, seed="fixed")
    partitions = []
    for name in ("training", "validation", "test"):
        assert (first / f"{name}.json").read_bytes() == (second / f"{name}.json").read_bytes()
        data = read_dataset(first / f"{name}.json")
        partitions.append({item["input_content_fingerprint"] for item in data["rows"]})
    assert all(
        not partitions[index] & partitions[other] for index in range(3) for other in range(index)
    )
    assert set.union(*partitions) == {f"input-{index}" for index in range(9)}
    if by == "family":
        families = [set(item["families"]) for item in result["partitions"].values()]
        assert all(
            not families[index] & families[other] for index in range(3) for other in range(index)
        )


def test_single_design_cannot_become_independent_by_renaming(tmp_path):
    source = tmp_path / "data.json"
    rows = [row(index, index + 1, "one-family") for index in range(8)]
    for item in rows:
        item["input_content_fingerprint"] = "same-input"
    make_dataset(source, rows)
    destination = tmp_path / "split"
    assert split_dataset(source, destination)["exit_code"] == 7
    assert not destination.exists()


def test_generated_matrix_detects_family_leakage_and_unknown_scope(tmp_path):
    source = tmp_path / "data.json"
    make_dataset(source, [row(index, index + 1, "same-family") for index in range(12)])
    split = tmp_path / "split"
    split_dataset(source, split)
    model = tmp_path / "model.json"
    train_model(split / "training.json", model)
    matrix = split / "validation-matrix.json"
    assert validate_matrix(model, matrix)["status"] == "unknown"
    with pytest.raises(ExperienceError, match="families overlap"):
        validate_matrix(model, matrix, family_holdout=True)
    with pytest.raises(ExperienceError, match="reuses training"):
        train_payload = read_dataset(split / "training.json")
        from ecc_experience.modeling.split import write_matrix

        write_matrix(tmp_path, "leaky", train_payload, train_payload["rows"])
        validate_matrix(model, tmp_path / "leaky-matrix.json")


def test_model_seed_sweep_is_bound_to_release_and_preserves_source(model_release, tmp_path):
    _model, heldout, release = model_release
    advice = tmp_path / "advice.json"
    advise_dataset(release, heldout, advice, limit=2)
    project = tmp_path / "project"
    project.mkdir()
    manifest = project / "ecc.toml"
    manifest.write_text("[design]\nname = 'generic'\n")
    original = manifest.read_bytes()
    result = seed_sweep(project, advice, release, "model-seeded")
    assert result["candidate_count"] == 2
    plan = json.loads((project / "experiments/model-seeded/sweep.json").read_text())
    assert all(set(item["parameters"]) == {"floorplan.core_util"} for item in plan["candidates"])
    assert verify_sweep(project, "model-seeded")["status"] == "fail"
    assert manifest.read_bytes() == original
    payload = json.loads(advice.read_text())
    payload["candidates"][0]["parameters"]["floorplan.core_util"] = 0.9
    advice.write_bytes(canonical_bytes(payload))
    with pytest.raises(ExperienceError, match="fingerprint"):
        seed_sweep(project, advice, release, "tampered")
    assert not (project / "experiments/tampered").exists()


def test_registry_rejects_parallel_writers_and_unsafe_or_corrupt_release(model_release, tmp_path):
    _model, _heldout, release = model_release
    registry = tmp_path / "registry"
    assert status(registry)["status"] == "empty"
    assert not registry.exists()
    promoted = promote(release, registry)
    assert promote(release, registry)["status"] == "already_active"
    (registry / ".write-lock").mkdir()
    with pytest.raises(ExperienceError) as error:
        promote(release, registry)
    assert error.value.code == "experience_store_busy"
    (registry / ".write-lock").rmdir()
    with pytest.raises(ExperienceError, match="Invalid.*ID"):
        rollback(registry, "../../outside")
    assert status(registry)["active_release_id"] == promoted["release_id"]
    stored = registry / "releases" / f"{promoted['release_id']}.json"
    payload = json.loads(stored.read_text())
    payload["scope"] = "corrupt"
    stored.write_bytes(canonical_bytes(payload))
    with pytest.raises(ExperienceError, match="identity"):
        status(registry)


def test_matrix_gates_ranking_and_rechecks_publication_evidence(model_release, tmp_path):
    model, heldout, _release = model_release
    data = read_dataset(heldout)
    for index, item in enumerate(data["rows"]):
        item["input_content_fingerprint"] = f"heldout-{index // 2}"
        item["group"] = f"new-family-{index // 2}"
    matrix = write_matrix(tmp_path, "matrix", data, data["rows"])
    matrix_path = tmp_path / "matrix-matrix.json"
    report = tmp_path / "matrix-report.json"
    assert (
        validate_matrix(model, matrix_path, report, min_independent_designs=2, family_holdout=True)[
            "status"
        ]
        == "pass"
    )
    first = tmp_path / matrix["datasets"][0]["path"]
    changed = read_dataset(first)
    for item in changed["rows"]:
        item["target"] = -1000.0 - item["target"]
    make_dataset(first, changed["rows"])
    failed = validate_matrix(model, matrix_path, min_independent_designs=2)
    assert failed["status"] == "fail"
    assert failed["metrics"]["rank_accuracy"] < 1
    with pytest.raises(ExperienceError, match="evidence changed"):
        publish_model(model, report, tmp_path / "rejected-release.json")
    assert not (tmp_path / "rejected-release.json").exists()


def test_matrix_without_candidate_pairs_is_unknown(model_release, tmp_path):
    model, heldout, _release = model_release
    data = read_dataset(heldout)
    write_matrix(tmp_path, "single-observations", data, data["rows"])
    report = validate_matrix(model, tmp_path / "single-observations-matrix.json")
    assert report["status"] == "unknown"
    assert report["metrics"]["rank_pair_count"] == 0


def test_dse_model_requires_matching_stage_process_and_runtime(model_release):
    _model, _heldout, release = model_release
    plan = {
        "through_step": "Synthesis",
        "process": {"fingerprint": "ics55-process"},
        "runtime": {"ecc": "test", "openroad": "2026"},
    }
    assert check_model(plan, release)["policy"]["auto_apply"] is False
    plan["runtime"] = {"ecc": "different-runtime"}
    with pytest.raises(ExperienceError) as error:
        check_model(plan, release)
    assert error.value.code == "experience_model_incompatible"
