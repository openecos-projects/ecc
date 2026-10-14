"""Serial baseline campaign scheduling with immutable terminal trial records."""

from functools import partial
from pathlib import Path
from uuid import uuid4

from chipcompiler.utility.workspace_lock import workspace_lock
from ecc_experience.benchmark.ledger import initialize, record_trial, status
from ecc_experience.benchmark.manifest import CampaignManifest, load_manifest
from ecc_experience.benchmark.preparation import (
    PreparedDesign,
    assert_inputs,
    prepare,
    runtime_identity,
)
from ecc_experience.benchmark.summary import summarize
from ecc_experience.benchmark.trial import execute_trial
from ecc_experience.files import read_json, safe_child
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.process import cancellation_signals

_KIND = "ecc-experience-campaign-run"


def campaign_identity(summary: dict, inputs: dict, runtime: dict) -> dict:
    return {
        "schema_version": 1,
        "kind": _KIND,
        "manifest_fingerprint": summary["fingerprint"],
        "inputs": inputs,
        "runtime": runtime,
        "store": summary["store"],
        "output_root": summary["output_root"],
    }


def read_run_state(path: Path, identity: dict, prepared: list[PreparedDesign]) -> dict:
    result = read_json(path)
    if any(result.get(key) != value for key, value in identity.items()):
        raise ExperienceError(
            "Campaign frozen inputs or runtime changed", code="experience_source_changed"
        )
    _validate_trials(result, prepared)
    return result


def run_campaign(manifest_path: str | Path, *, retry_failed: bool = False) -> dict:
    manifest, summary = load_manifest(manifest_path)
    try:
        prepared = prepare(manifest, summary)
    except (ExperienceError, OSError) as exc:
        if isinstance(exc, ExperienceError) and exc.code == "experience_workspace_busy":
            raise
        if (Path(summary["output_root"]) / "campaign-run.json").exists():
            raise ExperienceError(
                "Campaign source is no longer compatible", code="experience_source_changed"
            ) from exc
        raise
    runtime = runtime_identity()
    output = Path(summary["output_root"])
    ledger = safe_child(output, "campaign-ledger.json")
    try:
        with workspace_lock(ledger, blocking=False), cancellation_signals():
            return _run(
                manifest_path, manifest, summary, prepared, runtime, retry_failed=retry_failed
            )
    except BlockingIOError as exc:
        raise ExperienceError("Campaign is busy", code="experience_workspace_busy") from exc


def _run(
    manifest_path: str | Path,
    manifest: CampaignManifest,
    summary: dict,
    prepared: list[PreparedDesign],
    runtime: dict,
    *,
    retry_failed: bool,
) -> dict:
    output = Path(summary["output_root"])
    result_path = safe_child(output, "campaign-run.json")
    fingerprints = {item.design_id: item.fingerprint for item in prepared}
    identity = campaign_identity(summary, fingerprints, runtime)
    if result_path.exists():
        result = read_run_state(result_path, identity, prepared)
        if any(trial["status"] == "running" for trial in result["trials"]):
            raise ExperienceError(
                "Unfinished attempt exists; inspect campaign-run.json and its process/logs "
                "before recovery",
                code="experience_workspace_busy",
            )
    else:
        result = {
            **identity,
            "campaign_id": manifest.campaign_id,
            "status": "running",
            "exit_code": 0,
            "trials": [],
            "retry_failed": retry_failed,
        }
    progress = initialize(manifest_path)
    ledger = progress["ledger"]

    def save() -> None:
        write_plan(result_path, result)

    def check_inputs(design_id: str) -> None:
        _current, current_summary = load_manifest(manifest_path)
        if current_summary["fingerprint"] != summary["fingerprint"]:
            raise ExperienceError("Campaign manifest changed", code="experience_source_changed")
        assert_inputs(manifest, summary, fingerprints, design_id=design_id)

    for trial in result["trials"]:
        _record(ledger, trial)
    result.update(status="running", exit_code=0, retry_failed=retry_failed)
    result.pop("reason", None)
    save()
    try:
        for source in prepared:
            check_inputs(source.design_id)
            current = next(
                item for item in status(manifest_path)["designs"] if item["id"] == source.design_id
            )
            if current["status"] == "running":
                raise ExperienceError(
                    "Externally recorded attempt is running", code="experience_workspace_busy"
                )
            if current["trial_count"] and (current["status"] == "pass" or not retry_failed):
                continue
            if current["trial_count"] >= manifest.budget.max_trials_per_design:
                continue
            trial_id = f"trial-{uuid4().hex}"
            directory = safe_child(output, f"attempts/{trial_id}")
            directory.mkdir(parents=True, exist_ok=False)
            trial = {
                "trial_id": trial_id,
                "design_id": source.design_id,
                "workspace": "baseline",
                "run_id": str(uuid4()),
                "status": "running",
                "execution_status": "preparing",
                "collection_status": "not_attempted",
                "exit_code": 1,
                "commands": [],
                "directory": str(directory),
                "case_id": None,
                "reason": None,
            }
            result["trials"].append(trial)
            save()
            try:
                execute_trial(
                    source,
                    directory,
                    summary["store"],
                    manifest.budget.timeout_seconds_per_trial,
                    trial,
                    save,
                    partial(check_inputs, source.design_id),
                )
            finally:
                if trial["status"] != "running":
                    _record(ledger, trial)
            check_inputs(source.design_id)
    except KeyboardInterrupt:
        result.update(status="cancelled", exit_code=130, reason="user_interrupt")
    except ExperienceError as exc:
        result.update(
            status="stopped",
            reason=str(exc),
            exit_code=21
            if exc.code == "experience_source_changed"
            else 20
            if exc.code == "experience_workspace_busy"
            else 1,
        )
    except OSError as exc:
        result.update(status="stopped", reason=str(exc), exit_code=1)
    else:
        progress = summarize(manifest_path)
        result["summary"] = progress
        latest = {item["id"]: item["latest_trial"] for item in status(manifest_path)["designs"]}
        latest_ids = {item["trial_id"] for item in latest.values() if item is not None}
        timed_out = any(
            item["trial_id"] in latest_ids and item["exit_code"] == 124 for item in result["trials"]
        )
        exit_code = _exit_code(progress, timed_out=timed_out)
        campaign_state = progress["campaign_status"]
        if campaign_state == "complete" and exit_code != 0:
            campaign_state = "completed_with_evidence_issues"
        result.update(status=campaign_state, exit_code=exit_code)
    finally:
        save()
    return {"result": str(result_path), **result}


def _exit_code(summary: dict, *, timed_out: bool) -> int:
    if timed_out:
        return 124
    if summary["counts"]["cancelled"]:
        return 130
    if (
        summary["counts"]["fail"]
        or summary["counts"]["blocked"]
        or summary["evidence_counts"]["fail"]
    ):
        return 6
    if summary["evidence_counts"]["unknown"] or summary["evidence_counts"]["missing"]:
        return 7
    return 0


def _record(ledger: str, trial: dict) -> None:
    record_trial(
        ledger,
        design_id=trial["design_id"],
        workspace=trial["workspace"],
        status=trial["status"],
        trial_id=trial["trial_id"],
        case_id=trial["case_id"],
        reason=trial["reason"],
    )


def _validate_trials(result: dict, prepared: list[PreparedDesign]) -> None:
    ids = {item.design_id for item in prepared}
    trials = result.get("trials")
    try:
        if not isinstance(trials, list) or len({item["trial_id"] for item in trials}) != len(
            trials
        ):
            raise ValueError("Invalid or duplicate trial IDs")
        for trial in trials:
            if (
                trial["design_id"] not in ids
                or trial["status"] not in {"running", "pass", "fail", "blocked", "cancelled"}
                or not isinstance(trial["exit_code"], int)
            ):
                raise ValueError("Invalid trial")
            for field in ("trial_id", "workspace", "case_id", "reason"):
                trial[field]
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperienceError(
            "Invalid campaign execution state", code="experience_campaign_ledger_invalid"
        ) from exc
