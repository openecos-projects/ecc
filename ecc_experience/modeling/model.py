"""Train and verify a small, deterministic ridge baseline for P4."""

import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ecc_experience.files import digest, file_digest, read_json
from ecc_experience.modeling.dataset import read_dataset
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

MODEL_SCHEMA = "ecc-experience-model/1"
RELEASE_SCHEMA = "ecc-experience-model-release/1"
EVALUATION_SCHEMA = "ecc-experience-model-evaluation/1"


def train_model(dataset: str | Path, output: str | Path, *, ridge: float = 1.0) -> dict:
    source = Path(dataset).expanduser().absolute()
    data = read_dataset(source)
    if (
        not isinstance(ridge, (int, float))
        or isinstance(ridge, bool)
        or not math.isfinite(ridge)
        or ridge <= 0
    ):
        raise invalid("Ridge regularization must be a finite positive number")
    rows = data["rows"]
    columns = sorted({key for row in rows for key in row["features"]})
    matrix = np.array(
        [[float(row["features"].get(key, 0.0)) for key in columns] for row in rows],
        dtype=float,
    )
    targets = np.array([float(row["target"]) for row in rows], dtype=float)
    means = matrix.mean(axis=0)
    scales = matrix.std(axis=0)
    scales[scales == 0] = 1.0
    normalized = (matrix - means) / scales
    design = np.column_stack([np.ones(len(rows)), normalized])
    penalty = np.eye(design.shape[1]) * float(ridge)
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
    predictions = design @ coefficients
    residuals = targets - predictions
    model_identity = {
        "schema": MODEL_SCHEMA,
        "model_type": "ridge-1",
        "feature_schema": data["feature_schema"],
        "target": data["target"],
        "through_step": data["through_step"],
        "columns": columns,
        "means": means.tolist(),
        "scales": scales.tolist(),
        "coefficients": coefficients.tolist(),
        "feature_effects": [
            {
                "feature": column,
                "coefficient": float(coefficient),
                "direction": "positive" if coefficient >= 0 else "negative",
            }
            for column, coefficient in zip(columns, coefficients[1:], strict=True)
        ],
        "ridge": float(ridge),
        "training_dataset_id": data["dataset_id"],
        "training_release_id": data["release_id"],
        "training_input_fingerprints": sorted(
            {
                row["input_content_fingerprint"]
                for row in rows
                if row.get("input_content_fingerprint")
            }
        ),
        "training_groups": sorted({row["group"] for row in rows if row.get("group")}),
        "process_fingerprints": sorted(
            {row["process_fingerprint"] for row in rows if row.get("process_fingerprint")}
        ),
        "runtime_fingerprints": sorted({digest(row["runtime"]) for row in rows}),
    }
    result = {
        **model_identity,
        "model_id": f"model-{digest(model_identity)}",
        "trained_at": datetime.now(UTC).isoformat(),
        "training_summary": {
            "row_count": len(rows),
            "independent_input_count": len(model_identity["training_input_fingerprints"]),
            "group_count": len(model_identity["training_groups"]),
            "mae": float(np.mean(np.abs(residuals))),
            "rmse": float(np.sqrt(np.mean(residuals**2))),
            "residual_std": float(np.std(residuals)),
        },
        "policy": {"auto_apply": False, "requires_real_dse_validation": True},
        "limitations": [
            "Ridge baseline estimates association and does not prove parameter causality",
            "Predictions are valid only for the frozen feature, process and runtime scope",
            "Training data may contain repeated observations; independent counts are "
            "reported separately",
        ],
    }
    validate_model(result)
    _write_new(Path(output).expanduser().absolute(), result)
    return result


def evaluate_model(
    model: str | Path,
    dataset: str | Path,
    output: str | Path | None = None,
    *,
    min_independent_designs: int = 3,
    min_families: int = 2,
    max_mae: float = 10.0,
    min_interval_coverage: float = 0.5,
) -> dict:
    model_path = Path(model).expanduser().absolute()
    data_path = Path(dataset).expanduser().absolute()
    payload = read_model(model_path)
    data = read_dataset(data_path)
    if (
        data["feature_schema"] != payload["feature_schema"]
        or data["target"] != payload["target"]
        or data["through_step"] != payload["through_step"]
    ):
        raise invalid("Evaluation dataset is incompatible with the model feature scope")
    overlaps = sorted(
        set(payload["training_input_fingerprints"])
        & {
            row["input_content_fingerprint"]
            for row in data["rows"]
            if row.get("input_content_fingerprint")
        }
    )
    if overlaps:
        raise ExperienceError(
            "Training and held-out input fingerprints overlap",
            code="experience_model_leakage",
        )
    if not _compatible_scope(payload, data):
        raise ExperienceError(
            "Held-out process or runtime scope is incompatible",
            code="experience_model_incompatible",
        )
    predictions = [predict_features(payload, row["features"])["prediction"] for row in data["rows"]]
    targets = [float(row["target"]) for row in data["rows"]]
    residuals = [
        target - prediction for target, prediction in zip(targets, predictions, strict=True)
    ]
    residual_std = max(float(payload["training_summary"]["residual_std"]), 1e-12)
    coverage = sum(abs(error) <= 2 * residual_std for error in residuals) / len(residuals)
    pairs = [
        (
            (targets[left], predictions[left]),
            (targets[right], predictions[right]),
        )
        for left in range(len(targets))
        for right in range(left + 1, len(targets))
    ]
    rank_accuracy = (
        sum((left[0] - right[0]) * (left[1] - right[1]) >= 0 for left, right in pairs) / len(pairs)
        if pairs
        else None
    )
    independent = {
        row["input_content_fingerprint"]
        for row in data["rows"]
        if row.get("input_content_fingerprint")
    }
    families = {row["group"] for row in data["rows"] if row.get("group")}
    thresholds = {
        "min_independent_designs": min_independent_designs,
        "min_families": min_families,
        "max_mae": max_mae,
        "min_interval_coverage": min_interval_coverage,
    }
    known = len(independent) >= min_independent_designs and len(families) >= min_families
    mae = float(np.mean(np.abs(residuals)))
    status = (
        "pass"
        if known and mae <= max_mae and coverage >= min_interval_coverage
        else "unknown"
        if not known
        else "fail"
    )
    identity = {
        "schema": EVALUATION_SCHEMA,
        "model_id": payload["model_id"],
        "dataset_id": data["dataset_id"],
        "metrics": {
            "mae": mae,
            "rmse": float(np.sqrt(np.mean(np.array(residuals) ** 2))),
            "rank_accuracy": rank_accuracy,
            "interval_coverage": coverage,
        },
        "summary": {
            "row_count": len(data["rows"]),
            "independent_input_count": len(independent),
            "family_count": len(families),
        },
        "thresholds": thresholds,
        "status": status,
    }
    result = {
        **identity,
        "model": str(model_path),
        "dataset": str(data_path),
        "model_sha256": file_digest(model_path)[0],
        "dataset_sha256": file_digest(data_path)[0],
        "exit_code": {"pass": 0, "fail": 6, "unknown": 7}[status],
        "generalization_status": (
            "validated_for_declared_scope" if status == "pass" else "unproven"
        ),
        "predictions": [
            {
                "case_id": row["case_id"],
                "actual": target,
                **predict_features(payload, row["features"]),
            }
            for row, target in zip(data["rows"], targets, strict=True)
        ],
        "limitations": [
            "Held-out metrics apply only to the declared process, runtime, feature and "
            "target scope",
            "A passing report does not establish causal parameter effects or future "
            "design certainty",
            "The model must be followed by real ECC DSE and fresh validation",
        ],
    }
    result["evaluation_fingerprint"] = digest(result)
    result["evaluated_at"] = datetime.now(UTC).isoformat()
    if output is not None:
        _write_new(Path(output).expanduser().absolute(), result)
    return result


def publish_model(model: str | Path, evaluation: str | Path, output: str | Path) -> dict:
    model_path = Path(model).expanduser().absolute()
    evaluation_path = Path(evaluation).expanduser().absolute()
    report = read_json(evaluation_path)
    identity = {
        key: value
        for key, value in report.items()
        if key not in {"evaluated_at", "evaluation_fingerprint"}
    }
    if report.get("schema") != EVALUATION_SCHEMA or report.get("evaluation_fingerprint") != digest(
        identity
    ):
        raise invalid("Model evaluation report is invalid or changed")
    if report.get("status") != "pass":
        raise ExperienceError(
            "Only a passing held-out evaluation can publish a model",
            code="experience_model_unverified",
        )
    if Path(report.get("model", "")).resolve() != model_path or file_digest(model_path)[
        0
    ] != report.get("model_sha256"):
        raise ExperienceError(
            "Model artifact changed after evaluation", code="experience_source_changed"
        )
    current = evaluate_model(
        model_path,
        report["dataset"],
        min_independent_designs=report["thresholds"]["min_independent_designs"],
        min_families=report["thresholds"]["min_families"],
        max_mae=report["thresholds"]["max_mae"],
        min_interval_coverage=report["thresholds"]["min_interval_coverage"],
    )
    if current["evaluation_fingerprint"] != report["evaluation_fingerprint"]:
        raise ExperienceError("Model evaluation evidence changed", code="experience_source_changed")
    destination = Path(output).expanduser().absolute()
    if (
        destination.exists()
        or destination.is_symlink()
        or destination in {model_path, evaluation_path}
    ):
        raise invalid("Model release output must be a new file")
    model_payload = read_model(model_path)
    release_identity = {
        "schema": RELEASE_SCHEMA,
        "model_id": model_payload["model_id"],
        "model": model_payload,
        "evaluation_fingerprint": report["evaluation_fingerprint"],
        "scope": "validated_observations_only",
    }
    result = {
        **release_identity,
        "release_id": f"model-release-{digest(release_identity)}",
        "published_at": datetime.now(UTC).isoformat(),
        "policy": {"auto_apply": False, "requires_dse_validation": True},
        "limitations": [
            "This release ranks candidates within the evaluated scope; it does not "
            "automatically change a workspace"
        ],
    }
    _write_new(destination, result)
    return {
        "status": "created",
        "release_id": result["release_id"],
        "model_id": result["model_id"],
        "output": str(destination.resolve()),
        "generalization_status": "validated_for_declared_scope",
    }


def read_model(path: str | Path) -> dict:
    payload = read_json(Path(path).expanduser(), 64 * 1024 * 1024)
    if payload.get("schema") == RELEASE_SCHEMA:
        payload = payload.get("model", {})
    validate_model(payload)
    return payload


def validate_model(payload: dict) -> None:
    required = {
        "schema",
        "model_type",
        "feature_schema",
        "target",
        "through_step",
        "columns",
        "means",
        "scales",
        "coefficients",
        "feature_effects",
        "ridge",
        "training_dataset_id",
        "training_release_id",
        "training_input_fingerprints",
        "training_groups",
        "process_fingerprints",
        "runtime_fingerprints",
        "model_id",
        "trained_at",
        "training_summary",
        "policy",
        "limitations",
    }
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != MODEL_SCHEMA
        or set(payload) != required
    ):
        raise invalid("Invalid model artifact")
    identity = {
        key: payload[key]
        for key in (
            "schema",
            "model_type",
            "feature_schema",
            "target",
            "through_step",
            "columns",
            "means",
            "scales",
            "coefficients",
            "feature_effects",
            "ridge",
            "training_dataset_id",
            "training_release_id",
            "training_input_fingerprints",
            "training_groups",
            "process_fingerprints",
            "runtime_fingerprints",
        )
    }
    if payload.get("model_id") != f"model-{digest(identity)}":
        raise invalid("Model identity mismatch")
    if (
        not isinstance(payload["columns"], list)
        or len(payload["columns"]) != len(payload["means"])
        or len(payload["columns"]) + 1 != len(payload["coefficients"])
    ):
        raise invalid("Invalid model dimensions")
    if not payload["columns"] or not all(isinstance(item, str) for item in payload["columns"]):
        raise invalid("Model feature columns are invalid")
    effects = payload["feature_effects"]
    if (
        not isinstance(effects, list)
        or len(effects) != len(payload["columns"])
        or any(
            not isinstance(item, dict)
            or item.get("feature") != column
            or item.get("coefficient") != coefficient
            for item, column, coefficient in zip(
                effects, payload["columns"], payload["coefficients"][1:], strict=True
            )
        )
    ):
        raise invalid("Model feature explanations are invalid")
    numeric = [*payload["means"], *payload["scales"], *payload["coefficients"]]
    if not all(
        isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)
        for item in numeric
    ):
        raise invalid("Model parameters must be finite")
    if any(scale <= 0 for scale in payload["scales"]):
        raise invalid("Model feature scales must be positive")
    if not isinstance(payload["policy"], dict) or payload["policy"].get("auto_apply") is not False:
        raise invalid("Model auto-apply policy is invalid")


def predict_features(model: dict, features: dict[str, float]) -> dict:
    values = np.array([float(features.get(key, 0.0)) for key in model["columns"]], dtype=float)
    means = np.array(model["means"], dtype=float)
    scales = np.array(model["scales"], dtype=float)
    coefficients = np.array(model["coefficients"], dtype=float)
    prediction = float(np.array([1.0, *((values - means) / scales)]) @ coefficients)
    residual = max(float(model["training_summary"]["residual_std"]), 1e-12)
    if model["target"] == "feasibility":
        prediction = min(1.0, max(0.0, prediction))
    return {
        "prediction": prediction,
        "lower_bound": prediction - 2 * residual,
        "upper_bound": prediction + 2 * residual,
        "confidence": "high" if residual == 0 else "medium",
    }


def _compatible_scope(model: dict, data: dict) -> bool:
    processes = {
        row["process_fingerprint"] for row in data["rows"] if row.get("process_fingerprint")
    }
    runtimes = {digest(row["runtime"]) for row in data["rows"]}
    return (
        bool(processes)
        and bool(runtimes)
        and processes <= set(model["process_fingerprints"])
        and runtimes <= set(model["runtime_fingerprints"])
    )


def invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_model_invalid")


def _write_new(path: Path, payload: dict) -> None:
    if path.exists() or path.is_symlink():
        raise invalid("Model output must be a new file")
    write_plan(path, payload)
