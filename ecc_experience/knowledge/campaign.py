"""Turn one measured campaign into candidate knowledge without auto-promotion."""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ecc_experience.benchmark.d4 import D4_REPORT_SCHEMA, _entries, _load_run
from ecc_experience.files import digest, read_json
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

CAMPAIGN_MANIFEST_SCHEMA = "ecc-experience-campaign-manifest/1"
KNOWLEDGE_DELTA_SCHEMA = "ecc-experience-knowledge-delta/1"
QUEUE = ("reuse", "rebridge", "reobserve", "retire")


def build_campaign_manifest(report_path: str | Path, output: str | Path) -> dict[str, Any]:
    report_path = Path(report_path).expanduser().absolute()
    report = read_json(report_path, 64 * 1024 * 1024)
    if report.get("schema") != D4_REPORT_SCHEMA or not isinstance(report.get("runs"), list):
        raise _invalid("Campaign manifest currently requires a D4 report")
    spec_path = report.get("spec")
    if not isinstance(spec_path, str) or not spec_path:
        raise _invalid("D4 report has no frozen specification path")
    spec_path = Path(spec_path).expanduser().absolute()
    spec = read_json(spec_path, 16 * 1024 * 1024)
    entries = _entries(spec)
    measured = [_load_run(spec_path.parent, entry) for entry in entries]
    _verify_report_evidence(report, spec, spec_path, measured)

    runs = [_run_record(run) for run in measured]
    cohorts = Counter(row["cohort"]["cohort_id"] for row in runs if row["cohort"]["cohort_id"])
    manifest = {
        "schema": CAMPAIGN_MANIFEST_SCHEMA,
        "campaign_id": report.get("report_id") or f"campaign-{digest(report)}",
        "mode": "candidate",
        "status": "candidate",
        "source": {
            "report": str(report_path),
            "report_sha256": digest(report),
            "spec": str(spec_path),
            "spec_sha256": digest(spec),
            "report_status": report.get("status"),
            "report_reasons": report.get("reasons", []),
        },
        "budget": {
            "equal_budget": bool(report.get("summary", {}).get("equal_budget")),
            "min_designs": report.get("summary", {}).get("minimum_designs"),
            "min_families": report.get("summary", {}).get("minimum_families"),
            "min_seeds": report.get("summary", {}).get("minimum_seeds"),
        },
        "cohorts": [
            {"cohort_id": cohort_id, "run_count": count}
            for cohort_id, count in sorted(cohorts.items())
        ],
        "search": {
            "strategy_separation": report.get("summary", {}).get("strategy_separation"),
            "space_coverage": report.get("summary", {}).get("search_space_coverage"),
        },
        "model_evidence": {
            "calibration": report.get("summary", {}).get("model_calibration"),
            "strategies": {
                strategy: {
                    "run_count": values.get("run_count"),
                    "model_metrics_available": values.get("model_metrics_available"),
                    "model_prediction_count": values.get("model_prediction_count"),
                    "model_used_for_selection_count": values.get(
                        "model_used_for_selection_count"
                    ),
                }
                for strategy, values in sorted(report.get("strategies", {}).items())
                if isinstance(values, dict)
            },
        },
        "runs": runs,
        "counts": {
            "runs": len(runs),
            "designs": len({row["design"] for row in runs}),
            "families": len({row["family"] for row in runs}),
            "seeds": len({row["seed"] for row in runs}),
            "candidate_cases": len(
                {case_id for row in runs for case_id in row["case_ids"] if row["eligible"]}
            ),
        },
        "policy": {
            "candidate_only": True,
            "training_allowed_in_same_round": False,
            "automatic_apply": False,
            "automatic_promotion": False,
        },
        "safe_to_apply": False,
    }
    _write_once(Path(output).expanduser().absolute(), manifest)
    return manifest


def _verify_report_evidence(
    report: dict[str, Any], spec: dict[str, Any], spec_path: Path, measured: list[dict[str, Any]]
) -> None:
    if report.get("spec_fingerprint") != digest(spec):
        raise _invalid("D4 report fingerprint does not match its frozen specification")
    recorded_spec = report.get("spec")
    if not isinstance(recorded_spec, str) or not recorded_spec:
        raise _invalid("D4 report has no frozen specification path")
    if Path(recorded_spec).expanduser().absolute() != spec_path:
        raise _invalid("D4 report and specification paths disagree")
    reported = report["runs"]
    if len(measured) != len(reported):
        raise _invalid("D4 report and specification disagree on run count")

    actual = {_run_key(run): run for run in measured}
    if len(actual) != len(measured):
        raise _invalid("D4 specification contains duplicate run identities")
    reported_keys = [_run_key(row) for row in reported]
    if len(set(reported_keys)) != len(reported_keys) or set(reported_keys) != set(actual):
        raise _invalid("D4 report and specification disagree on run identities")

    for row in reported:
        run = actual[_run_key(row)]
        result = run["result"]
        fresh = result.get("fresh_validation")
        final_qor = fresh.get("qor_score") if isinstance(fresh, dict) else None
        if (
            row.get("status") != result.get("status")
            or row.get("full_validation") != _validation_status(result.get("full_validation"))
            or row.get("fresh_validation") != _validation_status(fresh)
            or row.get("final_qor") != final_qor
        ):
            raise _invalid("D4 report and current run evidence disagree")


def _run_key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
    return row.get("design"), row.get("strategy"), row.get("seed")


def _validation_status(value: Any) -> str:
    return value.get("status", "unknown") if isinstance(value, dict) else "unknown"


def compute_knowledge_delta(
    manifest_path: str | Path,
    output: str | Path,
    *,
    previous_release: str | Path | None = None,
    heldout: str | Path | None = None,
    active_cohort: str | None = None,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser().absolute()
    manifest = read_json(manifest_path, 64 * 1024 * 1024)
    if (
        manifest.get("schema") != CAMPAIGN_MANIFEST_SCHEMA
        or not isinstance(manifest.get("runs"), list)
        or manifest.get("mode") != "candidate"
    ):
        raise _invalid("Invalid candidate campaign manifest")
    release = _release_evidence(previous_release)
    heldout_payload = _heldout(heldout)
    triage = _triage(manifest["runs"], active_cohort)
    eligible = [row for row in manifest["runs"] if row["eligible"]]
    evidence_rows = [row for row in manifest["runs"] if row["validated"] and row["case_ids"]]
    designs = {row["design"] for row in evidence_rows}
    families = {row["family"] for row in evidence_rows}
    heldout_cases = set(heldout_payload.get("case_ids", []))
    heldout_designs = set(heldout_payload.get("designs", []))
    leakage = sorted(
        {
            *({case_id for row in eligible for case_id in row["case_ids"]} & heldout_cases),
            *(designs & heldout_designs),
        }
    )
    heldout_ready = bool(heldout_payload) and not leakage and bool(eligible)
    delta = {
        "schema": KNOWLEDGE_DELTA_SCHEMA,
        "campaign_id": manifest.get("campaign_id"),
        "manifest_sha256": digest(manifest),
        "status": "candidate",
        "queue": triage["queue"],
        "counts": {
            "runs": len(manifest["runs"]),
            "candidate_runs": len(eligible),
            "queue": triage["counts"],
            "quality": dict(
                sorted(Counter(row["quality"]["level"] for row in manifest["runs"]).items())
            ),
            "cohorts": dict(
                sorted(
                    Counter(
                        row["cohort"]["status"] for row in manifest["runs"] if row["cohort"]
                    ).items()
                )
            ),
            "families": len(families),
            "designs": len(designs),
        },
        "coverage": {
            "feature": _ratio(manifest["runs"], "feature_usable"),
            "resource": _ratio(manifest["runs"], "resource_available"),
            "validation": _ratio(manifest["runs"], "validated"),
        },
        "model": {
            "previous_release": release,
            "candidate_release": None,
            "metrics_delta": None,
            "campaign_calibration": manifest.get("model_evidence", {}).get("calibration"),
            "calibration_required": True,
        },
        "strategy": _strategy_results(manifest["runs"]),
        "heldout": {
            "provided": bool(heldout_payload),
            "ready": heldout_ready,
            "overlap": leakage,
            "reason": None
            if heldout_ready
            else "Independent held-out evidence is required before training or promotion",
        },
        "decisions": {
            "training_allowed": False,
            "promotion_allowed": False,
            "automatic_apply": False,
            "reason": (
                "Benchmark observations enter candidate state; held-out and champion gates "
                "remain required"
            ),
        },
        "safe_to_apply": False,
    }
    _write_once(Path(output).expanduser().absolute(), delta)
    return delta


def _run_record(run: dict[str, Any]) -> dict[str, Any]:
    result = run["result"]
    plan = run["plan"]
    trials = result.get("trials") if isinstance(result.get("trials"), list) else []
    selected_candidate, selected_parameters = _selection_evidence(result, trials)
    case_ids = sorted(
        {
            item["case_id"]
            for item in _case_records(result)
            if isinstance(item.get("case_id"), str) and item["case_id"]
        }
    )
    full = result.get("full_validation", {}).get("status")
    fresh = result.get("fresh_validation", {}).get("status")
    validated = result.get("status") == "complete" and full == "passed" and fresh == "passed"
    receipt_statuses = Counter(
        item.get("config_receipt", {}).get("status", "unknown")
        for item in trials
        if isinstance(item, dict) and isinstance(item.get("config_receipt"), dict)
    )
    feature_statuses = [
        item.get("feature_status") for item in trials if isinstance(item, dict)
    ]
    feature_usable = bool(feature_statuses) and all(
        status in {"available", "partial"} for status in feature_statuses
    )
    feature_complete = bool(feature_statuses) and all(
        status == "available" for status in feature_statuses
    )
    resources = run["resources"]
    coverage = resources.get("coverage") if isinstance(resources.get("coverage"), dict) else {}
    resource_available = bool(resources.get("observation_count")) and all(
        coverage.get(key) == 1.0
        for key in ("record_ratio", "rss_observation_ratio", "host_load_observation_ratio")
    )
    resource_attribution_isolated = resources.get("status") == "available"
    receipt_clean = bool(trials) and all(
        isinstance(item, dict)
        and isinstance(item.get("config_receipt"), dict)
        and item["config_receipt"].get("status") in {"applied", "matched"}
        and not item["config_receipt"].get("mismatches")
        and not item["config_receipt"].get("unmapped")
        for item in trials
    )
    quality = _run_quality(
        validated=validated,
        feature_usable=feature_usable,
        resource_available=resource_available,
        receipt_clean=receipt_clean,
        case_count=len(case_ids),
    )
    cohort = _plan_cohort(plan)
    return {
        "design": run["design"],
        "family": run["family"],
        "strategy": run["strategy"],
        "seed": run["seed"],
        "status": result.get("status"),
        "validated": validated,
        "full_validation": full,
        "fresh_validation": fresh,
        "case_ids": case_ids,
        "eligible": quality == "high" and validated and bool(case_ids),
        "quality": {
            "level": quality,
            "checks": {
                "validated": validated,
                "feature_usable": feature_usable,
                "feature_complete": feature_complete,
                "resource_available": resource_available,
                "resource_attribution_isolated": resource_attribution_isolated,
                "config_receipts": dict(sorted(receipt_statuses.items())),
                "case_evidence": bool(case_ids),
            },
            "basis": (
                "campaign_qor_candidate"
                if quality == "high"
                else "observation_only"
                if quality == "medium"
                else "insufficient_evidence"
            ),
            "limitations": [
                reason
                for reason, limited in (
                    ("feature_step_coverage_partial", not feature_complete),
                    ("resource_attribution_shared", not resource_attribution_isolated),
                )
                if limited
            ],
        },
        "cohort": cohort,
        "budget": {
            "limits": plan.get("limits", {}),
            "screening_trials": plan.get("screening_trials"),
            "rungs": plan.get("rungs", []),
        },
        "warm_start": run["warm_start"],
        "config_files": run["config_files"],
        "selected_candidate": selected_candidate,
        "selected_parameters": selected_parameters,
        "feature_available": feature_complete,
        "feature_usable": feature_usable,
        "resource_available": resource_available,
        "resource_attribution_isolated": resource_attribution_isolated,
        "final_qor": _final_qor(result),
        "score_delta": result.get("score_delta"),
        "model": _model_evidence(result),
        "resources": {
            "status": resources.get("status"),
            "record_ratio": resources.get("coverage", {}).get("record_ratio"),
            "rss_ratio": resources.get("coverage", {}).get("rss_observation_ratio"),
            "host_load_ratio": resources.get("coverage", {}).get("host_load_observation_ratio"),
            "scope_counts": resources.get("scope_counts", {}),
        },
        "rejected_reasons": _rejected_reasons(
            validated=validated,
            feature_usable=feature_usable,
            resource_available=resource_available,
            receipt_clean=receipt_clean,
            case_count=len(case_ids),
        ),
    }


def _selection_evidence(
    result: dict[str, Any], trials: list[Any]
) -> tuple[str | None, dict[str, Any] | None]:
    selection = result.get("selection")
    candidate = selection.get("candidate") if isinstance(selection, dict) else None
    for trial in trials:
        if not isinstance(trial, dict) or trial.get("candidate_id") != candidate:
            continue
        parameters = trial.get("parameters")
        return (
            candidate if isinstance(candidate, str) else None,
            parameters if isinstance(parameters, dict) else None,
        )
    return candidate if isinstance(candidate, str) else None, None


def _run_quality(
    *,
    validated: bool,
    feature_usable: bool,
    resource_available: bool,
    receipt_clean: bool,
    case_count: int,
) -> str:
    if not validated or not case_count:
        return "low"
    if feature_usable and resource_available and receipt_clean:
        return "high"
    return "medium"


def _rejected_reasons(**checks: Any) -> list[str]:
    names = {
        "validated": "full_and_fresh_validation_not_passed",
        "feature_usable": "feature_evidence_incomplete",
        "resource_available": "resource_measurement_incomplete",
        "receipt_clean": "config_receipt_mismatch_or_missing",
        "case_count": "case_evidence_missing",
    }
    return sorted(reason for key, reason in names.items() if not checks[key])


def _case_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for key in ("trials",):
        values = result.get(key)
        if isinstance(values, list):
            records.extend(item for item in values if isinstance(item, dict))
    for key in ("full_validation", "fresh_validation"):
        value = result.get(key)
        if isinstance(value, dict):
            records.append(value)
    return records


def _plan_cohort(plan: dict[str, Any]) -> dict[str, Any]:
    runtime = plan.get("runtime")
    process = plan.get("process")
    if not isinstance(runtime, dict):
        return {
            "cohort_id": None,
            "status": "unknown",
            "reason": "Plan has no runtime identity",
        }
    process_fingerprint = process.get("fingerprint") if isinstance(process, dict) else None
    contract = {
        "runtime": runtime,
        "process_fingerprint": process_fingerprint,
        "rungs": plan.get("rungs", []),
        "execution": plan.get("execution"),
    }
    return {
        "cohort_id": f"cohort-{digest(contract)}",
        "status": "available" if isinstance(process_fingerprint, str) else "partial",
        "runtime_fingerprint": digest(runtime),
        "process_fingerprint": process_fingerprint,
        "step_contract_fingerprint": digest(plan.get("rungs", [])),
    }


def _final_qor(result: dict[str, Any]) -> float | None:
    fresh = result.get("fresh_validation")
    value = fresh.get("qor_score") if isinstance(fresh, dict) else None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value)


def _model_evidence(result: dict[str, Any]) -> dict[str, Any]:
    model = result.get("model")
    if not isinstance(model, dict):
        return {"status": "unknown"}
    return {
        "status": model.get("status"),
        "release_id": model.get("release_id"),
        "model_id": model.get("model_id"),
        "used_for_selection": model.get("used_for_selection"),
        "reason": model.get("reason"),
    }


def _triage(runs: list[dict[str, Any]], active_cohort: str | None) -> dict[str, Any]:
    queue = {name: [] for name in QUEUE}
    details = []
    for row in runs:
        cohort = row["cohort"]
        cohort_id = cohort.get("cohort_id")
        if (
            row["status"] != "complete"
            or row["quality"]["level"] == "low"
            or cohort.get("status") != "available"
        ):
            action = "reobserve"
        elif active_cohort is not None and cohort_id != active_cohort:
            action = "rebridge"
        elif row["quality"]["level"] == "high":
            action = "reuse"
        else:
            action = "rebridge"
        identity = _run_identity(row)
        queue[action].append(identity)
        details.append({"identity": identity, "action": action})
    return {
        "queue": {name: sorted(values) for name, values in queue.items()},
        "counts": {name: len(values) for name, values in queue.items()},
        "details": details,
    }


def _run_identity(row: dict[str, Any]) -> str:
    return f"{row['design']}:{row['strategy']}:{row['seed']}"


def _strategy_results(runs: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = defaultdict(list)
    for row in runs:
        if row["final_qor"] is not None:
            grouped[row["strategy"]].append(row["final_qor"])
    return {
        strategy: {
            "run_count": len(values),
            "mean_final_qor": sum(values) / len(values) if values else None,
            "candidate_run_count": sum(
                row["eligible"] for row in runs if row["strategy"] == strategy
            ),
        }
        for strategy, values in sorted(grouped.items())
    }


def _release_evidence(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    source = Path(path).expanduser().absolute()
    payload = read_json(source, 32 * 1024 * 1024)
    validation = payload.get("validation")
    if not isinstance(validation, dict):
        validation = {}
    return {
        "path": str(source),
        "sha256": digest(payload),
        "release_id": payload.get("release_id"),
        "model_id": payload.get("model_id"),
        "metrics": validation.get("metrics"),
        "calibration": validation.get("calibration"),
    }


def _heldout(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = read_json(Path(path).expanduser().absolute(), 16 * 1024 * 1024)
    if payload.get("schema") != "ecc-experience-heldout/1":
        raise _invalid("Held-out declaration must use ecc-experience-heldout/1")
    case_ids = payload.get("case_ids", [])
    designs = payload.get("designs", [])
    if not all(isinstance(item, str) and item for item in [*case_ids, *designs]):
        raise _invalid("Held-out case and design IDs must be non-empty strings")
    return {"case_ids": sorted(set(case_ids)), "designs": sorted(set(designs))}


def _ratio(rows: list[dict[str, Any]], field: str) -> float:
    return sum(bool(row.get(field)) for row in rows) / len(rows) if rows else 0.0


def _write_once(destination: Path, payload: dict[str, Any]) -> None:
    if destination.exists() or destination.is_symlink():
        raise _invalid("Knowledge output must be a new file")
    write_plan(destination, payload)


def _invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_knowledge_invalid")
