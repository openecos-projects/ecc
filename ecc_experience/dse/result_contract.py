"""Validate persisted DSE result shapes before replaying or reporting evidence."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from ecc_experience.models import ExperienceError


class TrialRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    candidate_id: str
    parameters: dict[str, JsonValue]
    workspace: str
    workspace_id: str
    run_id: str
    mode: Literal["screen", "full", "fresh"]
    status: Literal[
        "running", "stage_passed", "passed", "failed", "blocked", "unknown", "timeout", "cancelled"
    ]
    exit_code: int
    commands: list[dict]
    objective_values: list[float] | None = None
    elapsed_seconds: float = Field(default=0, ge=0)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidate: str
    rule: Literal["explicit", "single_objective"]


class DseResult(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    schema_id: Literal["ecc-experience-stage-dse-result/2"] = Field(alias="schema")
    plan_fingerprint: str
    status: Literal[
        "running",
        "complete",
        "selection_required",
        "cancelled",
        "stopped",
        "timeout",
        "no_valid_stage_candidate",
        "full_validation_failed",
        "fresh_validation_failed",
    ]
    exit_code: int
    trials: list[TrialRecord]
    promotions: list[dict]
    selection: Selection | None
    stage_winner: TrialRecord | None
    full_validation: TrialRecord | None
    fresh_validation: TrialRecord | None
    elapsed_seconds: float = Field(ge=0)
    budget_expires_at: float
    safe_to_apply: Literal[False]
    generalization_status: Literal["unproven"]


def validate_result(payload: dict) -> None:
    try:
        DseResult.model_validate(payload)
    except ValidationError as exc:
        raise ExperienceError(
            "Invalid version 2 DSE result", code="experience_plan_invalid"
        ) from exc
