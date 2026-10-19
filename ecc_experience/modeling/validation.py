"""Aggregate independent design validation for a published model candidate."""

import math
from pathlib import Path

import numpy as np

from ecc_experience.files import digest, file_digest, read_json
from ecc_experience.modeling.dataset import read_dataset
from ecc_experience.modeling.model import predict_features, read_model
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

MATRIX_SCHEMA = "ecc-experience-model-validation-matrix/1"
MATRIX_EVALUATION_SCHEMA = "ecc-experience-model-matrix-evaluation/1"


def validate_matrix(
    model: str | Path,
    matrix: str | Path,
    output: str | Path | None = None,
    *,
    min_independent_designs: int = 3,
    min_families: int = 2,
    max_mae: float = 10.0,
    min_interval_coverage: float = 0.5,
    min_rank_accuracy: float = 0.5,
    family_holdout: bool = False,
) -> dict:
    if (
        min_independent_designs < 1
        or min_families < 1
        or not math.isfinite(max_mae)
        or max_mae < 0
        or not 0 <= min_interval_coverage <= 1
        or not 0 <= min_rank_accuracy <= 1
    ):
        raise invalid("Invalid validation thresholds")
    model_path = Path(model).expanduser().absolute()
    matrix_path = Path(matrix).expanduser().absolute()
    payload = read_matrix(matrix_path)
    model_payload = read_model(model_path)
    rows = []
    reports = []
    seen_inputs = set(model_payload["training_input_fingerprints"])
    seen_designs = set()
    seen_cases = set()
    for entry in payload["datasets"]:
        dataset_path = _resolve_path(matrix_path.parent, entry["path"])
        data = read_dataset(dataset_path)
        _check_scope(model_payload, data)
        if any(
            not isinstance(row.get("input_content_fingerprint"), str)
            or not row["input_content_fingerprint"]
            or row.get("group") != entry["family"]
            for row in data["rows"]
        ):
            raise invalid(
                "Each matrix design requires one complete input and consistent family labels"
            )
        current_inputs = {row["input_content_fingerprint"] for row in data["rows"]}
        if len(current_inputs) != 1:
            raise invalid("Each matrix design must contain exactly one input fingerprint")
        if len(rows) + len(data["rows"]) > 10000:
            raise invalid("Validation matrix exceeds 10000 rows")
        if family_holdout and entry["family"] in model_payload["training_groups"]:
            raise ExperienceError(
                "Training and held-out families overlap", code="experience_model_leakage"
            )
        overlap = sorted(seen_inputs & current_inputs)
        if overlap:
            raise ExperienceError(
                f"Validation matrix reuses training or another held-out input: {overlap[0]}",
                code="experience_model_leakage",
            )
        seen_inputs.update(current_inputs)
        design_id = entry["design"]
        if design_id in seen_designs:
            raise invalid("Validation matrix design IDs must be unique")
        seen_designs.add(design_id)
        dataset_rows = []
        for row in data["rows"]:
            if row["case_id"] in seen_cases:
                raise invalid("Validation matrix contains duplicate case IDs")
            seen_cases.add(row["case_id"])
            prediction = predict_features(model_payload, row["features"])["prediction"]
            dataset_rows.append(
                {
                    "case_id": row["case_id"],
                    "design": design_id,
                    "family": entry["family"],
                    "actual": float(row["target"]),
                    "prediction": prediction,
                }
            )
        reports.append(
            {
                "design": design_id,
                "family": entry["family"],
                "dataset": str(dataset_path),
                "dataset_id": data["dataset_id"],
                "dataset_sha256": file_digest(dataset_path)[0],
                "row_count": len(dataset_rows),
                "metrics": _metrics(dataset_rows, model_payload),
            }
        )
        rows.extend(dataset_rows)
    if not rows:
        raise invalid("Validation matrix contains no rows")
    if len(rows) > 10000:
        raise invalid("Validation matrix exceeds 10000 rows")
    metrics = _metrics(rows, model_payload)
    independent = len(seen_inputs - set(model_payload["training_input_fingerprints"]))
    families = {entry["family"] for entry in payload["datasets"]}
    thresholds = {
        "min_independent_designs": min_independent_designs,
        "min_families": min_families,
        "max_mae": max_mae,
        "min_interval_coverage": min_interval_coverage,
        "min_rank_accuracy": min_rank_accuracy,
        "family_holdout": family_holdout,
    }
    known = (
        len(seen_designs) >= min_independent_designs
        and len(families) >= min_families
        and (min_rank_accuracy == 0 or metrics["rank_pair_count"] > 0)
    )
    status = (
        "pass"
        if known
        and metrics["mae"] <= max_mae
        and metrics["interval_coverage"] >= min_interval_coverage
        and (metrics["rank_accuracy"] is None or metrics["rank_accuracy"] >= min_rank_accuracy)
        else "unknown"
        if not known
        else "fail"
    )
    identity = {
        "schema": MATRIX_EVALUATION_SCHEMA,
        "model_id": model_payload["model_id"],
        "model": str(model_path),
        "model_sha256": file_digest(model_path)[0],
        "matrix": str(matrix_path),
        "matrix_sha256": file_digest(matrix_path)[0],
        "metrics": metrics,
        "summary": {
            "row_count": len(rows),
            "independent_input_count": independent,
            "design_count": len(seen_designs),
            "family_count": len(families),
        },
        "thresholds": thresholds,
        "status": status,
        "designs": reports,
        "predictions": rows,
    }
    result = {
        **identity,
        "generalization_status": "validated_for_declared_scope" if status == "pass" else "unproven",
        "limitations": [
            "Matrix metrics apply only to the declared process, runtime, feature and target scope",
            "A passing matrix does not establish causal parameter effects or future design "
            "certainty",
            "A real ECC DSE and fresh full-flow validation remain required before promotion",
        ],
    }
    result["evaluation_fingerprint"] = digest(result)
    if output is not None:
        _write_new(Path(output).expanduser().absolute(), result)
    return result


def read_matrix(path: str | Path) -> dict:
    source = Path(path).expanduser().absolute()
    payload = read_json(source, 64 * 1024 * 1024)
    if payload.get("schema") != MATRIX_SCHEMA or not isinstance(payload.get("datasets"), list):
        raise invalid("Unsupported model validation matrix schema")
    if not payload["datasets"] or len(payload["datasets"]) > 1000:
        raise invalid("Validation matrix must contain between 1 and 1000 datasets")
    identity = {"schema": MATRIX_SCHEMA, "datasets": payload["datasets"]}
    if payload.get("matrix_id") != f"matrix-{digest(identity)}":
        raise invalid("Validation matrix identity mismatch")
    for entry in payload["datasets"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "design", "family"}
            or not all(isinstance(entry.get(key), str) and entry[key] for key in entry)
        ):
            raise invalid("Invalid validation matrix dataset entry")
    return payload


def _metrics(rows: list[dict], model: dict) -> dict:
    actual = np.array([row["actual"] for row in rows], dtype=float)
    predicted = np.array([row["prediction"] for row in rows], dtype=float)
    errors = actual - predicted
    residual = max(float(model["training_summary"]["residual_std"]), 1e-12)
    designs = np.array([row["design"] for row in rows])
    pairs = 0
    correct = 0.0
    for index in range(len(rows) - 1):
        comparable = (designs[index + 1 :] == designs[index]) & (
            actual[index + 1 :] != actual[index]
        )
        products = (actual[index] - actual[index + 1 :]) * (
            predicted[index] - predicted[index + 1 :]
        )
        pairs += int(np.sum(comparable))
        correct += float(np.sum((products > 0) & comparable))
        correct += 0.5 * float(np.sum((products == 0) & comparable))
    return {
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "rank_accuracy": correct / pairs if pairs else None,
        "rank_pair_count": pairs,
        "interval_coverage": float(np.mean(np.abs(errors) <= 2 * residual)),
    }


def _check_scope(model: dict, data: dict) -> None:
    if (
        data["feature_schema"] != model["feature_schema"]
        or data["target"] != model["target"]
        or data["through_step"] != model["through_step"]
    ):
        raise invalid("Validation dataset is incompatible with the model feature scope")
    if any(
        not isinstance(row.get("process_fingerprint"), str)
        or not isinstance(row.get("runtime"), dict)
        for row in data["rows"]
    ):
        raise invalid("Validation rows require recorded process and runtime identities")
    processes = {row.get("process_fingerprint") for row in data["rows"]}
    runtimes = {digest(row.get("runtime", {})) for row in data["rows"]}
    if not processes <= set(model["process_fingerprints"]) or not runtimes <= set(
        model["runtime_fingerprints"]
    ):
        raise ExperienceError(
            "Validation dataset is outside the published model scope",
            code="experience_model_incompatible",
        )


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.absolute() if path.is_absolute() else (base / path).absolute()


def invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_model_invalid")


def _write_new(path: Path, payload: dict) -> None:
    if path.exists() or path.is_symlink():
        raise invalid("Validation output must be a new file")
    write_plan(path, payload)
