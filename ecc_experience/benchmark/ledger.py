"""Persistent, private-data-free campaign trial ledger operations."""

import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ecc_experience.benchmark.manifest import CampaignManifest, load_manifest
from ecc_experience.files import canonical_bytes, read_json
from ecc_experience.models import ExperienceError

LEDGER_SCHEMA_VERSION = 1
LEDGER_KIND = "ecc-experience-campaign-ledger"
TRIAL_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+\Z")
CASE_ID_PATTERN = re.compile(r"case-[0-9a-f]{64}\Z")
_MAX_LEDGER_BYTES = 4 * 1024 * 1024
_STATUSES = {"running", "pass", "fail", "blocked", "cancelled"}


def initialize(manifest_path: str | Path, ledger_path: str | Path | None = None) -> dict:
    manifest, summary = load_manifest(manifest_path)
    destination = _ledger_path(manifest_path, manifest, ledger_path)
    if destination.exists():
        existing = _read_ledger(destination)
        _assert_identity(existing, summary)
        return _status(existing, destination, summary, created=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    now = _timestamp()
    ledger = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "campaign_id": manifest.campaign_id,
        "manifest_fingerprint": summary["fingerprint"],
        "process_profile": manifest.process_profile,
        "mode": manifest.mode,
        "created_at": now,
        "updated_at": now,
        "designs": [
            {
                "id": design.id,
                "input": design.input.path,
                "workspace": design.workspace,
                "labels": list(design.labels),
                "evaluation_group": design.evaluation_group,
                "trials": [],
            }
            for design in manifest.designs
        ],
    }
    _write_json(destination, ledger)
    return _status(ledger, destination, summary, created=True)


def record_trial(
    ledger_path: str | Path,
    *,
    design_id: str,
    workspace: str,
    status: str,
    trial_id: str | None = None,
    case_id: str | None = None,
    reason: str | None = None,
) -> dict:
    destination = _validated_ledger_path(ledger_path)
    ledger = _read_ledger(destination)
    design = next((item for item in ledger["designs"] if item["id"] == design_id), None)
    if design is None:
        raise ExperienceError(
            f"Campaign design does not exist: {design_id}",
            code="experience_campaign_design_invalid",
        )
    if not workspace or not TRIAL_ID_PATTERN.fullmatch(workspace):
        raise ExperienceError(
            "Campaign workspace must be a non-empty single-segment name",
            code="experience_campaign_trial_invalid",
        )
    if status not in _STATUSES:
        raise ExperienceError(
            f"Unsupported campaign trial status: {status}",
            code="experience_campaign_trial_invalid",
        )
    if trial_id is None:
        trial_id = f"trial-{uuid4().hex}"
    if not TRIAL_ID_PATTERN.fullmatch(trial_id):
        raise ExperienceError(
            "Campaign trial ID contains unsupported characters",
            code="experience_campaign_trial_invalid",
        )
    if case_id is not None and not CASE_ID_PATTERN.fullmatch(case_id):
        raise ExperienceError(
            "Campaign case ID is invalid",
            code="experience_case_id_invalid",
        )
    existing = next(
        (item for item in design["trials"] if item["trial_id"] == trial_id), None
    )
    trial = {
        "trial_id": trial_id,
        "workspace": workspace,
        "status": status,
        "case_id": case_id,
        "reason": reason,
        "recorded_at": _timestamp(),
    }
    if existing is not None:
        comparable = {key: existing.get(key) for key in trial if key != "recorded_at"}
        requested = {key: trial.get(key) for key in trial if key != "recorded_at"}
        if comparable != requested:
            raise ExperienceError(
                f"Campaign trial already exists with different data: {trial_id}",
                code="experience_campaign_trial_conflict",
            )
        return {"status": "already_present", "trial": existing, "ledger": str(destination)}
    design["trials"].append(trial)
    ledger["updated_at"] = _timestamp()
    _write_json(destination, ledger)
    return {"status": "recorded", "trial": trial, "ledger": str(destination)}


def status(manifest_path: str | Path, ledger_path: str | Path | None = None) -> dict:
    _manifest, summary = load_manifest(manifest_path)
    destination = _ledger_path(manifest_path, _manifest, ledger_path)
    if not destination.exists():
        raise ExperienceError(
            f"Campaign ledger does not exist: {destination}",
            code="experience_campaign_ledger_missing",
        )
    ledger = _read_ledger(destination)
    _assert_identity(ledger, summary)
    return _status(ledger, destination, summary, created=False)


def _status(ledger: dict, destination: Path, summary: dict, *, created: bool) -> dict:
    designs = []
    counts = {"pending": 0, "running": 0, "pass": 0, "fail": 0, "blocked": 0, "cancelled": 0}
    for item in ledger["designs"]:
        trials = item["trials"]
        current = trials[-1]["status"] if trials else "pending"
        counts[current] += 1
        designs.append(
            {
                "id": item["id"],
                "workspace": item["workspace"],
                "status": current,
                "trial_count": len(trials),
                "latest_trial": trials[-1] if trials else None,
            }
        )
    return {
        "ledger": str(destination),
        "created": created,
        "campaign_id": ledger["campaign_id"],
        "manifest_fingerprint": summary["fingerprint"],
        "manifest_match": ledger["manifest_fingerprint"] == summary["fingerprint"],
        "updated_at": ledger["updated_at"],
        "counts": counts,
        "designs": designs,
    }


def _ledger_path(
    manifest_path: str | Path, manifest: CampaignManifest, requested: str | Path | None
) -> Path:
    output_root = _manifest_output_root(manifest_path, manifest)
    destination = (
        Path(requested).expanduser().absolute().resolve()
        if requested is not None
        else output_root / "campaign-ledger.json"
    )
    if requested is not None and not destination.is_relative_to(output_root):
        raise ExperienceError(
            "Campaign ledger must be inside output_root",
            code="experience_campaign_ledger_invalid",
        )
    if destination == output_root:
        raise ExperienceError(
            "Campaign ledger must be a file below output_root",
            code="experience_campaign_ledger_invalid",
        )
    return destination


def _validated_ledger_path(path: str | Path) -> Path:
    requested = Path(path).expanduser().absolute()
    if requested.is_symlink() or not requested.is_file():
        raise ExperienceError(
            f"Campaign ledger does not exist: {requested}",
            code="experience_campaign_ledger_missing",
        )
    return requested.resolve()


def _read_ledger(path: Path) -> dict:
    try:
        if path.stat().st_size > _MAX_LEDGER_BYTES:
            raise ExperienceError(
                "Campaign ledger is oversized", code="experience_campaign_ledger_invalid"
            )
        payload = read_json(path, _MAX_LEDGER_BYTES)
    except OSError as exc:
        raise ExperienceError(
            "Unable to read campaign ledger", code="experience_campaign_ledger_invalid"
        ) from exc
    if (
        payload.get("schema_version") != LEDGER_SCHEMA_VERSION
        or payload.get("kind") != LEDGER_KIND
        or not isinstance(payload.get("designs"), list)
    ):
        raise ExperienceError(
            "Campaign ledger is invalid", code="experience_campaign_ledger_invalid"
        )
    try:
        _validate_ledger_shape(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperienceError(
            "Campaign ledger is invalid", code="experience_campaign_ledger_invalid"
        ) from exc
    return payload


def _validate_ledger_shape(ledger: dict) -> None:
    if not isinstance(ledger["campaign_id"], str) or not TRIAL_ID_PATTERN.fullmatch(
        ledger["campaign_id"]
    ):
        raise ValueError("invalid campaign ID")
    if not isinstance(ledger["manifest_fingerprint"], str) or len(
        ledger["manifest_fingerprint"]
    ) != 64:
        raise ValueError("invalid manifest fingerprint")
    ids = set()
    for design in ledger["designs"]:
        design_id = design["id"]
        if not isinstance(design_id, str) or design_id in ids:
            raise ValueError("invalid design")
        ids.add(design_id)
        if not isinstance(design["trials"], list):
            raise ValueError("invalid trials")
        trial_ids = set()
        for trial in design["trials"]:
            trial_id = trial["trial_id"]
            if (
                not isinstance(trial_id, str)
                or not TRIAL_ID_PATTERN.fullmatch(trial_id)
                or trial_id in trial_ids
            ):
                raise ValueError("invalid trial")
            if trial["status"] not in _STATUSES:
                raise ValueError("invalid status")
            trial_ids.add(trial_id)


def _assert_identity(ledger: dict, summary: dict) -> None:
    if ledger.get("campaign_id") != summary["campaign_id"] or ledger.get(
        "manifest_fingerprint"
    ) != summary["fingerprint"]:
        raise ExperienceError(
            "Campaign manifest changed after ledger initialization",
            code="experience_campaign_manifest_changed",
        )


def _manifest_output_root(manifest_path: str | Path, manifest: CampaignManifest) -> Path:
    root = Path(manifest_path).expanduser().absolute().resolve().parent
    return (root / manifest.output_root).resolve()


def _write_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{path.name}.", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(canonical_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()
