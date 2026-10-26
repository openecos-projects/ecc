"""Build immutable, leakage-checked numerical datasets from verified cases."""

import math
from pathlib import Path

from ecc_experience.files import digest, file_digest, read_json
from ecc_experience.knowledge.features import case_features
from ecc_experience.knowledge.matching import read_groups
from ecc_experience.knowledge.release import verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceCase, ExperienceError, parameter_evidence_level
from ecc_experience.optimization.plan import write_plan

DATASET_SCHEMA_V1 = "ecc-experience-model-dataset/1"
FEATURE_SCHEMA_V1 = "ecc-experience-model-features/1"
DATASET_SCHEMA = "ecc-experience-model-dataset/2"
FEATURE_SCHEMA = "ecc-experience-model-features/2"
SUPPORTED_SCHEMAS = {
    DATASET_SCHEMA_V1: FEATURE_SCHEMA_V1,
    DATASET_SCHEMA: FEATURE_SCHEMA,
}
_MAX_ROWS = 10000


def build_dataset(
    release: str | Path,
    store: str | Path,
    output: str | Path,
    *,
    target: str,
    through_step: str,
    groups: str | Path | None = None,
) -> dict:
    repository = ExperienceStore(store)
    frozen = verify_release(release, repository.root)
    if frozen["status"] != "pass":
        raise invalid("The source release must verify before dataset construction")
    family_map = read_groups(groups) if groups else {}
    rows = []
    excluded = []
    for record in frozen["cases"]:
        case_id = record["case_id"]
        try:
            case = repository.read(case_id)
            verification = verify_case(case, repository.case_directory(case_id))
            if verification.status != "pass" or verification.integrity != "pass":
                raise invalid("Case verification did not pass")
            value = target_value(case, target, through_step)
            if value is None:
                raise invalid("Target is missing or non-finite")
            features = extract_features(case, repository.case_directory(case_id), through_step)
            if not features:
                raise invalid("No numeric features are available")
            rows.append(
                {
                    "case_id": case_id,
                    "input_content_fingerprint": case.input_content_fingerprint,
                    "group": family_map.get(case_id),
                    "attempt_id": case.source.attempt_id,
                    "features": features,
                    "target": value,
                    "parameters": _parameters(case),
                    "process_fingerprint": case.process_fingerprint,
                    "runtime": _runtime(case),
                    "design_fingerprint": case.design_fingerprint
                    or (case.design.fingerprint if case.design else None),
                    "constraints_fingerprint": (
                        case.constraints.fingerprint if case.constraints else None
                    ),
                    "toolchain_fingerprint": (
                        case.toolchain.runtime_fingerprint if case.toolchain else None
                    ),
                    "parameter_evidence_level": parameter_evidence_level(case),
                    "resource_scope": _resource_scope(case),
                    "feature_coverage": {
                        "stage": str(through_step),
                        "identity_fields": sum(
                            bool(value)
                            for value in (
                                case.design_fingerprint
                                or (case.design.fingerprint if case.design else None),
                                case.constraints.fingerprint if case.constraints else None,
                                case.process_fingerprint,
                                (case.toolchain.runtime_fingerprint if case.toolchain else None),
                            )
                        ),
                        "required_identity_fields": 4,
                    },
                }
            )
        except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
            excluded.append({"case_id": case_id, "reason": str(exc)})
    if not rows:
        raise invalid("No verified rows with the requested target")
    if len(rows) > _MAX_ROWS:
        raise invalid("Dataset exceeds the maximum row count")
    inputs = {row["input_content_fingerprint"] for row in rows if row["input_content_fingerprint"]}
    release_path = Path(release).expanduser().absolute()
    identity = {
        "schema": DATASET_SCHEMA,
        "feature_schema": FEATURE_SCHEMA,
        "release_id": frozen["release_id"],
        "release_sha256": file_digest(release_path)[0],
        "target": target,
        "through_step": through_step,
        "groups": family_map,
        "rows": rows,
    }
    result = {
        **identity,
        "dataset_id": f"dataset-{digest(identity)}",
        "summary": {
            "row_count": len(rows),
            "excluded_count": len(excluded),
            "independent_input_count": len(inputs),
            "group_count": len({row["group"] for row in rows if row["group"]}),
            "process_fingerprints": sorted(
                {row["process_fingerprint"] for row in rows if row["process_fingerprint"]}
            ),
            "runtime_count": len({digest(row["runtime"]) for row in rows}),
            "design_fingerprint_count": len(
                {row["design_fingerprint"] for row in rows if row["design_fingerprint"]}
            ),
            "constraints_fingerprint_count": len(
                {row["constraints_fingerprint"] for row in rows if row["constraints_fingerprint"]}
            ),
            "toolchain_fingerprint_count": len(
                {row["toolchain_fingerprint"] for row in rows if row["toolchain_fingerprint"]}
            ),
            "parameter_evidence": {
                level: sum(row["parameter_evidence_level"] == level for row in rows)
                for level in ("applied", "configured", "unknown")
            },
        },
        "excluded": excluded,
        "limitations": [
            "Configured parameters describe committed configuration and do not prove "
            "tool consumption",
            "A dataset is an observation snapshot and does not establish independent "
            "design families",
            "Resource fields retain their recorded measurement scope and are not recomputed",
            "Feature schema v2 records identity and resource scope metadata; missing family "
            "labels cannot support held-out generalization claims",
        ],
    }
    _write_new(Path(output).expanduser().absolute(), result)
    return result


def read_dataset(path: str | Path) -> dict:
    payload = read_json(Path(path).expanduser(), 64 * 1024 * 1024)
    validate_dataset(payload)
    return payload


def validate_dataset(payload: dict) -> None:
    schema = payload.get("schema")
    if SUPPORTED_SCHEMAS.get(schema) != payload.get("feature_schema"):
        raise invalid("Unsupported model dataset schema")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > _MAX_ROWS:
        raise invalid("Dataset rows are missing or exceed the limit")
    identity = {
        key: payload.get(key)
        for key in (
            "schema",
            "feature_schema",
            "release_id",
            "release_sha256",
            "target",
            "through_step",
            "groups",
            "rows",
        )
    }
    if payload.get("dataset_id") != f"dataset-{digest(identity)}":
        raise invalid("Dataset identity mismatch")
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("case_id"), str)
            or not isinstance(row.get("features"), dict)
            or not row["features"]
            or not isinstance(row.get("target"), (int, float))
            or isinstance(row["target"], bool)
            or not math.isfinite(row["target"])
        ):
            raise invalid("Invalid dataset row")
        if not all(
            isinstance(key, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for key, value in row["features"].items()
        ):
            raise invalid("Dataset features must be finite numeric values")
        if schema == DATASET_SCHEMA:
            for key in (
                "design_fingerprint",
                "constraints_fingerprint",
                "process_fingerprint",
                "toolchain_fingerprint",
                "parameter_evidence_level",
                "resource_scope",
                "feature_coverage",
            ):
                if key not in row:
                    raise invalid(f"Dataset v2 row is missing {key}")
            if row["parameter_evidence_level"] not in {"applied", "configured", "unknown"}:
                raise invalid("Dataset v2 parameter evidence level is invalid")
            if not isinstance(row["resource_scope"], dict):
                raise invalid("Dataset v2 resource scope is invalid")
            coverage = row["feature_coverage"]
            if (
                not isinstance(coverage, dict)
                or set(coverage) != {"stage", "identity_fields", "required_identity_fields"}
                or coverage["required_identity_fields"] != 4
                or type(coverage["identity_fields"]) is not int
                or not 0 <= coverage["identity_fields"] <= 4
            ):
                raise invalid("Dataset v2 feature coverage is invalid")


def extract_features(case: ExperienceCase, directory: Path, through_step: str) -> dict[str, float]:
    features = {"constant": 1.0}
    observed = case_features(case.case_id, _store_for_case(directory), through_step=through_step)
    if observed["status"] == "fail":
        raise invalid("Stage evidence is corrupt")
    steps = observed.get("steps", [])
    features.update(
        {
            "flow.prefix_step_count": float(len(steps)),
            "flow.available_step_count": float(
                sum(item.get("status") == "available" for item in steps)
            ),
            "flow.success_step_count": float(sum(item.get("state") == "Success" for item in steps)),
        }
    )
    design = case.design
    constraints = case.constraints
    process = case.process
    toolchain = case.toolchain
    features.update(
        {
            "design.closure_complete": float(bool(design and design.closure == "complete")),
            "design.tag_count": float(len(design.tags) if design else 0),
            "design.memory_bits": float(design.memory_bits or 0) if design else 0.0,
            "design.macro_count": float(design.macro_count or 0) if design else 0.0,
            "constraints.sdc_available": float(bool(constraints and constraints.sdc_sha256)),
            "constraints.clock_period_count": float(
                len(constraints.clock_periods) if constraints else 0
            ),
            "constraints.corner_count": float(len(constraints.corners) if constraints else 0),
            "process.identity_available": float(bool(process and process.status == "available")),
            "process.file_count": float(len(process.files) if process else 0),
            "toolchain.identity_available": float(
                bool(toolchain and toolchain.status == "available")
            ),
            "toolchain.source_count": float(len(toolchain.sources) if toolchain else 0),
            "toolchain.tool_count": float(len(toolchain.tools) if toolchain else 0),
            "toolchain.native_package_count": float(
                len(toolchain.native_packages) if toolchain else 0
            ),
            "input_closure.complete_count": float(
                sum(item.closure == "complete" for item in case.inputs)
            ),
            "input_closure.partial_count": float(
                sum(item.closure == "partial" for item in case.inputs)
            ),
            "input_closure.unknown_count": float(
                sum(item.closure == "unknown" for item in case.inputs)
            ),
        }
    )
    if constraints and constraints.clock_periods:
        periods = [
            value
            for value in constraints.clock_periods
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ]
        if periods:
            features["constraints.clock_period_min"] = float(min(periods))
            features["constraints.clock_period_max"] = float(max(periods))
    for step in steps:
        prefix = f"step.{step['step']}"
        for metric in step.get("metrics", []):
            value = metric.get("value")
            if (
                metric.get("status") == "available"
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                features[f"{prefix}.metric.{metric['id']}.{metric['unit']}"] = float(value)
        observation = step.get("resource_observation")
        if isinstance(observation, dict):
            _numeric_flatten(features, f"{prefix}.resource", observation)
    specification = case.facts.get("workspaceSpec", {})
    if isinstance(specification, dict):
        _numeric_flatten(features, "spec", specification.get("parameters", {}))
    _numeric_flatten(
        features,
        "inputs",
        {
            "count": len(case.inputs),
            "available": sum(item.status == "available" for item in case.inputs),
        },
    )
    return features


def target_value(case: ExperienceCase, target: str, through_step: str) -> float | None:
    qor = case.facts.get("qorSnapshotExtension")
    qor_data = qor if isinstance(qor, dict) else {}
    if target == "final_qor":
        if _last_step(case) == through_step:
            raise invalid("Final QoR cannot be predicted from a prefix containing the final step")
        if qor_data.get("status") != "available":
            return None
        return _finite(qor_data.get("score"))
    if target == "feasibility":
        if qor_data.get("status") != "available":
            return None
        feasibility = qor_data.get("feasibility")
        status = feasibility.get("status") if isinstance(feasibility, dict) else None
        return 1.0 if status == "PASS" else 0.0 if status in {"FAIL", "UNKNOWN"} else None
    if target.startswith("metric:"):
        metric_id = target.split(":", 1)[1]
        metrics = case.facts.get("metrics")
        for item in metrics if isinstance(metrics, list) else []:
            if isinstance(item, dict) and item.get("id") == metric_id:
                return _finite(item.get("value"))
        return None
    if target.startswith("resource:"):
        parts = target.split(":")
        if len(parts) != 3 or _last_step(case) == through_step:
            raise invalid("Resource targets require a prior step boundary")
        flow = case.facts.get("flow")
        steps = flow.get("steps") if isinstance(flow, dict) else []
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, dict) and step.get("name") == parts[1]:
                observation = step.get("resource_observation")
                return _finite(observation.get(parts[2])) if isinstance(observation, dict) else None
    raise invalid(f"Unsupported target: {target}")


def _store_for_case(directory: Path) -> Path:
    case_directory = directory
    while case_directory.name != "cases" and case_directory.parent != case_directory:
        case_directory = case_directory.parent
    if case_directory.name != "cases":
        raise invalid("Cannot resolve case store for feature extraction")
    return case_directory.parent


def _parameters(case: ExperienceCase) -> dict:
    specification = case.facts.get("workspaceSpec", {})
    values = specification.get("parameters", {}) if isinstance(specification, dict) else {}
    return values if isinstance(values, dict) else {}


def _runtime(case: ExperienceCase) -> dict:
    context = case.facts.get("experienceExecutionContext")
    runtime = context.get("runtime") if isinstance(context, dict) else {}
    return runtime if isinstance(runtime, dict) else {}


def _resource_scope(case: ExperienceCase) -> dict:
    flow = case.facts.get("flow", {})
    steps = flow.get("steps", []) if isinstance(flow, dict) else []
    scopes = []
    for step in steps if isinstance(steps, list) else []:
        observation = step.get("resource_observation") if isinstance(step, dict) else None
        if not isinstance(observation, dict):
            continue
        host = observation.get("host") if isinstance(observation.get("host"), dict) else {}
        concurrency = (
            observation.get("concurrency")
            if isinstance(observation.get("concurrency"), dict)
            else {}
        )
        scopes.append(
            {
                "step": step.get("name"),
                "scope": observation.get("scope"),
                "host_class": host.get("class") or host.get("cpu_model"),
                "logical_cores": host.get("logical_cores"),
                "max_concurrent": concurrency.get("max_concurrent"),
            }
        )
    return {"steps": scopes}


def _last_step(case: ExperienceCase) -> str | None:
    flow = case.facts.get("flow", {})
    steps = flow.get("steps", []) if isinstance(flow, dict) else []
    if not isinstance(steps, list) or not steps or not isinstance(steps[-1], dict):
        return None
    name = steps[-1].get("name")
    return name if isinstance(name, str) else None


def _numeric_flatten(target: dict[str, float], prefix: str, value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                _numeric_flatten(target, f"{prefix}.{key}", child)
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        target[prefix] = float(value)


def _finite(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_dataset_invalid")


def _write_new(path: Path, payload: dict) -> None:
    if path.exists() or path.is_symlink():
        raise invalid("Dataset output must be a new file")
    write_plan(path, payload)
