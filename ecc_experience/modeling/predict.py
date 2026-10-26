"""Apply published P4 models to verified observations without changing a design."""

from pathlib import Path

from ecc_experience.files import digest, read_json
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.modeling.dataset import extract_features, read_dataset
from ecc_experience.modeling.model import (
    RELEASE_SCHEMA,
    RELEASE_SCHEMA_V1,
    predict_features,
)
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

PREDICTION_SCHEMA = "ecc-experience-model-prediction/1"
ADVICE_SCHEMA = "ecc-experience-model-advice/1"


def read_model_release(path: str | Path) -> dict:
    source = Path(path).expanduser().absolute()
    payload = read_json(source, 64 * 1024 * 1024)
    schema = payload.get("schema")
    if schema not in {RELEASE_SCHEMA_V1, RELEASE_SCHEMA}:
        raise invalid("The model release schema is unsupported")
    model = payload.get("model")
    if not isinstance(model, dict):
        raise invalid("The model release does not contain a model")
    read_model_payload(model)
    identity = {
        "schema": payload.get("schema"),
        "model_id": payload.get("model_id"),
        "model": model,
        "evaluation_fingerprint": payload.get("evaluation_fingerprint"),
        "scope": payload.get("scope"),
    }
    if schema == RELEASE_SCHEMA:
        validation = payload.get("validation")
        base_keys = {
            "status",
            "metrics",
            "summary",
            "thresholds",
            "generalization_status",
        }
        if (
            not isinstance(validation, dict)
            or (set(validation) != base_keys and set(validation) != base_keys | {"calibration"})
            or validation["status"] != "pass"
            or not isinstance(validation["metrics"], dict)
            or not isinstance(validation["summary"], dict)
            or not isinstance(validation["thresholds"], dict)
            or not {"mae", "rmse", "rank_accuracy", "interval_coverage"}
            <= set(validation["metrics"])
            or not {"row_count", "independent_input_count", "family_count"}
            <= set(validation["summary"])
            or not {
                "min_independent_designs",
                "min_families",
                "max_mae",
                "min_interval_coverage",
            }
            <= set(validation["thresholds"])
        ):
            raise invalid("The model release validation summary is invalid")
        if "calibration" in validation:
            calibration = validation["calibration"]
            if (
                not isinstance(calibration, dict)
                or set(calibration)
                != {
                    "method",
                    "status",
                    "target_coverage",
                    "interval_half_width",
                    "base_residual_std",
                    "sample_count",
                    "group_count",
                    "cross_validated_coverage",
                    "cross_validated_group_count",
                    "limitations",
                }
                or calibration["method"] != "grouped_conformal_absolute_error"
                or calibration["status"] not in {"available", "insufficient_evidence"}
                or not 0 < calibration["target_coverage"] <= 1
                or calibration["interval_half_width"] <= 0
                or not 0 <= calibration["cross_validated_coverage"] <= 1
            ):
                raise invalid("The model release calibration is invalid")
        identity["validation"] = validation
    if payload.get("release_id") != f"model-release-{digest(identity)}":
        raise invalid("Model release identity mismatch")
    policy = payload.get("policy")
    if not isinstance(policy, dict) or policy.get("auto_apply") is not False:
        raise invalid("Model release auto-apply policy is invalid")
    return payload


def predict_case(
    model_release: str | Path,
    case_id: str,
    store: str | Path,
    *,
    through_step: str | None = None,
) -> dict:
    release = read_model_release(model_release)
    model = release["model"]
    repository = ExperienceStore(store)
    case = repository.read(case_id)
    if case.process_fingerprint not in set(model["process_fingerprints"]):
        raise ExperienceError(
            "Case process is outside the published model scope",
            code="experience_model_incompatible",
        )
    context = case.facts.get("experienceExecutionContext")
    runtime = context.get("runtime", {}) if isinstance(context, dict) else {}
    if digest(runtime) not in set(model["runtime_fingerprints"]):
        raise ExperienceError(
            "Case runtime is outside the published model scope",
            code="experience_model_incompatible",
        )
    boundary = through_step or model["through_step"]
    if boundary != model["through_step"]:
        raise invalid("Prediction boundary is incompatible with the model feature scope")
    features = extract_features(case, repository.case_directory(case_id), boundary)
    calibration = release.get("validation", {}).get("calibration")
    prediction = predict_features(model, features, calibration=calibration)
    result = {
        "schema": PREDICTION_SCHEMA,
        "model_release_id": release["release_id"],
        "model_id": model["model_id"],
        "case_id": case_id,
        "input_content_fingerprint": case.input_content_fingerprint,
        "target": model["target"],
        "through_step": boundary,
        "prediction": prediction,
        "safe_to_apply": False,
        "limitations": [
            "Prediction is advisory and does not modify workspace parameters",
            "The model is valid only for its declared feature, process and runtime scope",
            "Run a bounded ECC DSE and fresh full-flow validation before accepting a change",
        ],
    }
    result["prediction_id"] = f"prediction-{digest(result)}"
    return result


def advise_dataset(
    model_release: str | Path,
    dataset: str | Path,
    output: str | Path,
    *,
    limit: int = 10,
) -> dict:
    if limit < 1 or limit > 1000:
        raise invalid("Advice limit must be between 1 and 1000")
    release = read_model_release(model_release)
    model = release["model"]
    calibration = release.get("validation", {}).get("calibration")
    data = read_dataset(dataset)
    if (
        data["feature_schema"] != model["feature_schema"]
        or data["target"] != model["target"]
        or data["through_step"] != model["through_step"]
    ):
        raise invalid("Advice dataset is incompatible with the model release")
    if not _compatible_scope(model, data):
        raise ExperienceError(
            "Advice dataset is outside the published model scope",
            code="experience_model_incompatible",
        )
    candidates = []
    for row in data["rows"]:
        candidates.append(
            {
                "case_id": row["case_id"],
                "parameters": row.get("parameters", {}),
                "input_content_fingerprint": row.get("input_content_fingerprint"),
                "prediction": predict_features(model, row["features"], calibration=calibration),
            }
        )
    reverse = not model["target"].startswith("resource:")
    candidates.sort(key=lambda item: item["prediction"]["prediction"], reverse=reverse)
    result = {
        "schema": ADVICE_SCHEMA,
        "model_release_id": release["release_id"],
        "model_id": model["model_id"],
        "dataset_id": data["dataset_id"],
        "target": model["target"],
        "through_step": model["through_step"],
        "candidates": candidates[:limit],
        "safe_to_apply": False,
        "limitations": [
            "Ranking is advisory and does not select or apply an ECC DSE plan",
            "A candidate must be replayed through a bounded flow and fresh validation",
            "Resource targets sort low-to-high only for the documented runtime and memory fields",
        ],
    }
    result["advice_id"] = f"advice-{digest(result)}"
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise invalid("Advice output must be a new file")
    write_plan(destination, result)
    return result


def read_model_payload(payload: dict) -> dict:
    """Validate an embedded model using the same contract as a model file."""
    from ecc_experience.modeling.model import validate_model

    validate_model(payload)
    return payload


def _compatible_scope(model: dict, data: dict) -> bool:
    processes = {
        row.get("process_fingerprint") for row in data["rows"] if row.get("process_fingerprint")
    }
    runtimes = {digest(row.get("runtime", {})) for row in data["rows"]}
    return (
        bool(processes)
        and bool(runtimes)
        and processes <= set(model["process_fingerprints"])
        and runtimes <= set(model["runtime_fingerprints"])
    )


def invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_model_invalid")
