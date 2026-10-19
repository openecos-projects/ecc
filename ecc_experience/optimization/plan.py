"""Build and persist conservative, human-reviewable optimization plans."""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.files import canonical_bytes, digest
from ecc_experience.knowledge.recommend import recommend
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.policy import OptimizationLimits


def build_plan(
    workspace: str | Path,
    store: str | Path,
    *,
    limit: int = 10,
    release: str | Path | None = None,
    optimization: OptimizationLimits | None = None,
) -> dict:
    recommendation = recommend(workspace, store, limit=limit, release=release)
    query = recommendation["query"]
    candidates = recommendation["recommendations"]
    plan = {
        "schema_version": 1,
        "kind": "ecc-experience-optimization-plan",
        "created_at": datetime.now(UTC).isoformat(),
        "status": recommendation["status"],
        "query": query,
        "baseline": {
            "workspace": query["workspace"],
            "case_id": None,
            "snapshot_digest": read_workspace_observation(workspace).source.snapshot_digest,
        },
        "candidates": [
            {
                "candidate_id": f"observed-{index:04d}",
                "case_id": item["case_id"],
                "parameters": item["parameters"],
                "qor": item.get("qor", {}),
                "confidence": item["confidence"],
                "safe_to_apply": False,
            }
            for index, item in enumerate(candidates, 1)
        ],
        "execution_policy": {
            "mode": "manual_review",
            "requires_new_workspace": True,
            "auto_apply": False,
            "requires_case_verification": True,
            "required_evidence": [
                "parameter_application_receipt",
                "committed_workspace_snapshot",
                "flow_and_checklist",
                "qor_and_signoff_reports",
            ],
        },
    }
    if not candidates:
        plan["reason"] = recommendation.get("reason", "No verified recommendation")
    if release is not None:
        plan["release_id"] = recommendation.get("release_verification", {}).get("release_id")
    if optimization is not None:
        plan["optimization"] = optimization.checked().model_dump()
    identity = {key: value for key, value in plan.items() if key != "created_at"}
    plan["plan_fingerprint"] = digest(identity)
    return plan


def write_plan(path: str | Path, plan: dict) -> dict:
    destination = Path(path).expanduser().absolute()
    if destination.exists() and destination.is_symlink():
        raise ExperienceError("Plan output must not be a symlink", code="experience_plan_invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{destination.name}.", dir=destination.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(canonical_bytes(plan))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"plan": str(destination.resolve()), **plan}
