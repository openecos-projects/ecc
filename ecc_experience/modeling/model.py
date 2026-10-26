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
RELEASE_SCHEMA_V1 = "ecc-experience-model-release/1"
RELEASE_SCHEMA = "ecc-experience-model-release/2"
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
    means, scales, coefficients = _fit_ridge(matrix, targets, ridge)
    predictions = _predict_ridge(matrix, means, scales, coefficients)
    residuals = targets - predictions
    leave_one_out_errors = _leave_one_input_out_errors(
        matrix, targets, [row.get("input_content_fingerprint") for row in rows], ridge
    )
    residual_std = (
        float(np.std(leave_one_out_errors))
        if leave_one_out_errors is not None
        else float(np.std(residuals))
    )
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
            "residual_std": residual_std,
            "in_sample_residual_std": float(np.std(residuals)),
            "interval_basis": (
                "leave_one_input_out" if leave_one_out_errors is not None else "training_residual"
            ),
            "cross_validation_folds": (
                len(
                    {
                        item
                        for item in [row.get("input_content_fingerprint") for row in rows]
                        if item
                    }
                )
                if leave_one_out_errors is not None
                else 0
            ),
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


def _fit_ridge(
    matrix: np.ndarray, targets: np.ndarray, ridge: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    means = matrix.mean(axis=0)
    scales = matrix.std(axis=0)
    scales[scales == 0] = 1.0
    normalized = (matrix - means) / scales
    design = np.column_stack([np.ones(len(targets)), normalized])
    penalty = np.eye(design.shape[1]) * float(ridge)
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
    return means, scales, coefficients


def _predict_ridge(
    matrix: np.ndarray,
    means: np.ndarray,
    scales: np.ndarray,
    coefficients: np.ndarray,
) -> np.ndarray:
    normalized = (matrix - means) / scales
    design = np.column_stack([np.ones(len(matrix)), normalized])
    return design @ coefficients


def _leave_one_input_out_errors(
    matrix: np.ndarray,
    targets: np.ndarray,
    fingerprints: list[str | None],
    ridge: float,
) -> list[float] | None:
    groups = sorted({item for item in fingerprints if item})
    if len(groups) < 2:
        return None
    errors: list[float] = []
    for held_out in groups:
        training = [index for index, item in enumerate(fingerprints) if item != held_out]
        testing = [index for index, item in enumerate(fingerprints) if item == held_out]
        if not testing:
            continue
        means, scales, coefficients = _fit_ridge(matrix[training], targets[training], ridge)
        predictions = _predict_ridge(matrix[testing], means, scales, coefficients)
        errors.extend((targets[testing] - predictions).tolist())
    return errors or None


def evaluate_model(
    model: str | Path,
    dataset: str | Path,
    output: str | Path | None = None,
    *,
    min_independent_designs: int = 3,
    min_families: int = 2,
    max_mae: float = 10.0,
    min_interval_coverage: float = 0.5,
    calibration_target_coverage: float = 0.9,
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
    families = {row["group"] for row in data["rows"] if row.get("group")}
    if data["schema"] == "ecc-experience-model-dataset/2":
        family_overlap = sorted(set(payload["training_groups"]) & families)
        if family_overlap:
            raise ExperienceError(
                "Training and held-out families overlap: " + ", ".join(family_overlap),
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
    calibration = calibrate_residuals(
        residuals,
        [row.get("input_content_fingerprint") or row["case_id"] for row in data["rows"]],
        target_coverage=calibration_target_coverage,
        base_scale=float(payload["training_summary"]["residual_std"]),
    )
    coverage = calibration["cross_validated_coverage"]
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
    thresholds = {
        "min_independent_designs": min_independent_designs,
        "min_families": min_families,
        "max_mae": max_mae,
        "min_interval_coverage": min_interval_coverage,
        "calibration_target_coverage": calibration_target_coverage,
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
        "calibration": calibration,
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
            "Interval calibration uses held-out groups; cross-validated coverage is not a "
            "guarantee for new designs",
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
    supported_schemas = {EVALUATION_SCHEMA}
    from ecc_experience.modeling.validation import MATRIX_EVALUATION_SCHEMA

    supported_schemas.add(MATRIX_EVALUATION_SCHEMA)
    if report.get("schema") not in supported_schemas or report.get(
        "evaluation_fingerprint"
    ) != digest(identity):
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
    if report["schema"] == EVALUATION_SCHEMA:
        current = evaluate_model(
            model_path,
            report["dataset"],
            min_independent_designs=report["thresholds"]["min_independent_designs"],
            min_families=report["thresholds"]["min_families"],
            max_mae=report["thresholds"]["max_mae"],
            min_interval_coverage=report["thresholds"]["min_interval_coverage"],
            calibration_target_coverage=report["thresholds"]["calibration_target_coverage"],
        )
    else:
        from ecc_experience.modeling.validation import validate_matrix

        current = validate_matrix(
            model_path,
            report["matrix"],
            min_independent_designs=report["thresholds"]["min_independent_designs"],
            min_families=report["thresholds"]["min_families"],
            max_mae=report["thresholds"]["max_mae"],
            min_interval_coverage=report["thresholds"]["min_interval_coverage"],
            min_rank_accuracy=report["thresholds"]["min_rank_accuracy"],
            family_holdout=report["thresholds"]["family_holdout"],
            calibration_target_coverage=report["thresholds"]["calibration_target_coverage"],
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
    validation = {
        "status": report["status"],
        "metrics": report["metrics"],
        "summary": report["summary"],
        "thresholds": report["thresholds"],
        "calibration": report["calibration"],
        "generalization_status": report.get(
            "generalization_status", "validated_for_declared_scope"
        ),
    }
    release_identity = {
        "schema": RELEASE_SCHEMA,
        "model_id": model_payload["model_id"],
        "model": model_payload,
        "evaluation_fingerprint": report["evaluation_fingerprint"],
        "validation": validation,
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
    if payload.get("schema") in {RELEASE_SCHEMA_V1, RELEASE_SCHEMA}:
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


def calibrate_residuals(
    residuals: list[float],
    groups: list[str],
    *,
    target_coverage: float = 0.9,
    base_scale: float | None = None,
) -> dict:
    if (
        not residuals
        or len(residuals) != len(groups)
        or not all(math.isfinite(value) for value in residuals)
        or not 0 < target_coverage <= 1
    ):
        raise invalid("Calibration residuals or target coverage are invalid")
    absolute = [abs(value) for value in residuals]
    grouped: dict[str, list[float]] = {}
    for group, value in zip(groups, absolute, strict=True):
        grouped.setdefault(str(group), []).append(value)
    half_width = _quantile_absolute(absolute, target_coverage)
    if len(grouped) >= 2:
        covered = []
        for group, values in grouped.items():
            training = [value for key, items in grouped.items() if key != group for value in items]
            width = _quantile_absolute(training, target_coverage)
            covered.extend(value <= width for value in values)
        cross_validated = sum(covered) / len(covered)
        cross_status = "available"
    else:
        cross_validated = sum(value <= half_width for value in absolute) / len(absolute)
        cross_status = "insufficient_evidence"
    return {
        "method": "grouped_conformal_absolute_error",
        "status": cross_status,
        "target_coverage": target_coverage,
        "interval_half_width": half_width,
        "base_residual_std": max(float(base_scale or 0.0), 1e-12),
        "sample_count": len(absolute),
        "group_count": len(grouped),
        "cross_validated_coverage": cross_validated,
        "cross_validated_group_count": len(grouped),
        "limitations": [
            "Calibration requires independent held-out groups and cannot guarantee future design "
            "coverage",
            "Symmetric absolute-error intervals do not model asymmetric or failure tails",
        ],
    }


def _quantile_absolute(values: list[float], coverage: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(coverage * len(ordered)) - 1))
    return max(float(ordered[index]), 1e-12)


def predict_features(
    model: dict, features: dict[str, float], *, calibration: dict | None = None
) -> dict:
    values = np.array([float(features.get(key, 0.0)) for key in model["columns"]], dtype=float)
    means = np.array(model["means"], dtype=float)
    scales = np.array(model["scales"], dtype=float)
    coefficients = np.array(model["coefficients"], dtype=float)
    prediction = float(np.array([1.0, *((values - means) / scales)]) @ coefficients)
    training_residual = max(float(model["training_summary"]["residual_std"]), 1e-12)
    if model["target"] == "feasibility":
        prediction = min(1.0, max(0.0, prediction))
    if calibration is not None and calibration.get("status") == "available":
        residual = max(float(calibration["interval_half_width"]), 1e-12)
        coverage = float(calibration["cross_validated_coverage"])
        interval = {
            "basis": "held_out_grouped_calibration",
            "target_coverage": calibration["target_coverage"],
            "cross_validated_coverage": coverage,
        }
    else:
        residual = training_residual
        coverage = None
        interval = {"basis": "training_residual", "target_coverage": None}
    return {
        "prediction": prediction,
        "lower_bound": prediction - 2 * residual,
        "upper_bound": prediction + 2 * residual,
        "confidence": (
            "high"
            if coverage is not None and coverage >= 0.9
            else "medium"
            if coverage is not None and coverage >= 0.5
            else "low"
            if coverage is not None
            else "medium"
        ),
        "interval": interval,
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
