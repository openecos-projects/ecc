"""Validated limits and provenance for explicitly authorized optimization runs."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chipcompiler.cli.inspection.evidence_summary import qor_score
from chipcompiler.data.parameter_schema import lookup_schema, parse_cli_overrides
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.files import digest, read_json
from ecc_experience.knowledge.recommend import _input_fingerprint, _sanitize
from ecc_experience.knowledge.release import verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceError, WorkspaceObservation

SUPPORTED_PARAMETERS = frozenset(
    {
        "floorplan.core_util",
        "floorplan.core_margin",
        "floorplan.aspect_ratio",
        "place.target_density",
        "place.target_overflow",
        "place.global_right_padding",
        "place.cell_padding_x",
        "place.routability_opt",
        "cts.max_fanout",
        "cts.skew_bound",
        "cts.max_buf_tran",
        "cts.max_sink_tran",
        "cts.max_cap",
    }
)


class OptimizationLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    allow_parameters: list[str] = Field(min_length=1)
    max_trials: int = Field(ge=2, le=100)
    max_seconds: int = Field(ge=1)
    trial_timeout_seconds: int = Field(ge=1)
    patience: int = Field(default=3, ge=1)
    target_score: float | None = None

    def checked(self) -> "OptimizationLimits":
        if len(set(self.allow_parameters)) != len(self.allow_parameters):
            raise invalid_plan("Allowed parameters must be unique")
        if not set(self.allow_parameters) <= SUPPORTED_PARAMETERS:
            raise invalid_plan(
                "Only reviewed floorplan, placement and CTS parameters are supported"
            )
        if any(lookup_schema(key) is None for key in self.allow_parameters):
            raise invalid_plan("Allowed parameter is absent from the current ECC catalog")
        if self.trial_timeout_seconds > self.max_seconds:
            raise invalid_plan("Trial timeout must not exceed the total time budget")
        return self


def invalid_plan(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_plan_invalid")


def parse_limits(value: object) -> OptimizationLimits:
    try:
        return OptimizationLimits.model_validate(value).checked()
    except ValidationError as exc:
        raise invalid_plan(str(exc)) from exc


def plan_identity(plan: dict) -> str:
    return digest(
        {key: value for key, value in plan.items() if key not in {"created_at", "plan_fingerprint"}}
    )


def check_baseline(plan: dict) -> WorkspaceObservation:
    baseline = plan["baseline"]
    observation = read_workspace_observation(baseline["workspace"])
    fingerprint = _input_fingerprint(observation.facts, observation.inputs)
    if (
        observation.source.snapshot_digest is None
        or observation.source.snapshot_digest != baseline.get("snapshot_digest")
        or fingerprint is None
        or fingerprint != plan["query"].get("input_content_fingerprint")
    ):
        raise ExperienceError(
            "Baseline snapshot or input content changed", code="experience_source_changed"
        )
    return observation


def read_execution_plan(path: str | Path, store: str | Path) -> tuple[dict, OptimizationLimits]:
    try:
        plan = read_json(Path(path).expanduser())
    except ExperienceError as exc:
        raise invalid_plan(str(exc)) from exc
    if (
        plan.get("kind") != "ecc-experience-optimization-plan"
        or plan.get("schema_version") != 1
        or plan.get("plan_fingerprint") != plan_identity(plan)
        or not isinstance(plan.get("baseline"), dict)
        or not isinstance(plan.get("query"), dict)
        or not isinstance(plan.get("candidates"), list)
    ):
        raise invalid_plan("Invalid optimization plan or fingerprint")
    if not isinstance(plan["baseline"].get("workspace"), str):
        raise invalid_plan("Plan requires an absolute baseline workspace")
    if not Path(plan["baseline"]["workspace"]).is_absolute():
        raise invalid_plan("Baseline workspace must be absolute")
    limits = parse_limits(plan.get("optimization"))
    release = plan["query"].get("release")
    if release is not None:
        verified = verify_release(release, store)
        if verified["status"] != "pass" or verified["release_id"] != plan.get("release_id"):
            raise ExperienceError(
                "Experience release changed or failed verification",
                code="experience_release_unverified",
            )
        case_ids = {item["case_id"] for item in verified["cases"]}
        if any(
            not isinstance(candidate, dict) or candidate.get("case_id") not in case_ids
            for candidate in plan["candidates"]
        ):
            raise invalid_plan("Plan candidate is outside the bound experience release")
    return plan, limits


def eligible_candidates(
    plan: dict, limits: OptimizationLimits, baseline: WorkspaceObservation, store: str | Path
) -> tuple[list[dict], list[dict]]:
    repository = ExperienceStore(store)
    specification = baseline.facts.get("workspaceSpec", {})
    baseline_parameters = _sanitize(specification.get("parameters", {}))
    selected, skipped = [], []
    identities = set()
    for candidate in plan["candidates"]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("case_id"), str):
            raise invalid_plan("Invalid observed candidate")
        case = repository.read(candidate["case_id"])
        verification = verify_case(case, repository.case_directory(case.case_id))
        candidate_spec = case.facts.get("workspaceSpec", {})
        if not isinstance(candidate_spec, dict):
            raise invalid_plan("Case has no workspace specification")
        parameters = _sanitize(candidate_spec.get("parameters", {}))
        if not isinstance(parameters, dict) or not isinstance(baseline_parameters, dict):
            raise invalid_plan("Case or baseline has invalid parameters")
        if parameters != candidate.get("parameters"):
            raise invalid_plan("Candidate parameters do not match the stored observation")
        reason = None
        if verification.status == "fail" or verification.integrity != "pass":
            reason = "case_verification_failed"
        elif case.input_content_fingerprint != plan["query"]["input_content_fingerprint"]:
            reason = "incompatible_inputs"
        elif any(
            candidate_spec.get(key) != specification.get(key) for key in ("design", "pdk", "flow")
        ):
            reason = "incompatible_design_process_or_flow"
        elif configuration_differences(baseline_parameters, parameters) - set(
            limits.allow_parameters
        ):
            reason = "changes_outside_allowlist"
        if reason is not None:
            skipped.append({"case_id": case.case_id, "reason": reason})
            continue
        differences = configuration_differences(baseline_parameters, parameters)
        changes = {}
        for key in limits.allow_parameters:
            if key not in differences:
                continue
            schema = lookup_schema(key)
            if schema is None:
                raise invalid_plan("Allowed parameter is absent from the current ECC catalog")
            changes[key] = parameters.get(key, schema.default)
        pairs = [f"{key}={_literal(value)}" for key, value in changes.items()]
        _parsed, errors = parse_cli_overrides(pairs)
        if errors:
            raise invalid_plan("; ".join(errors))
        identity = digest(changes)
        if identity in identities:
            skipped.append({"case_id": case.case_id, "reason": "duplicate_configuration"})
            continue
        identities.add(identity)
        qor = case.facts.get("qorSnapshotExtension")
        score = qor_score(qor) if isinstance(qor, dict) else None
        selected.append(
            {
                "case_id": case.case_id,
                "parameters": changes,
                "sets": pairs,
                "observed_score": score,
            }
        )
    selected.sort(
        key=lambda candidate: candidate["observed_score"]
        if candidate["observed_score"] is not None
        else float("-inf"),
        reverse=True,
    )
    return selected, skipped


def configuration_differences(baseline: dict, candidate: dict) -> set[str]:
    changed = set()
    missing = object()
    for key in set(baseline) | set(candidate):
        schema = lookup_schema(key)
        default = schema.default if schema is not None else missing
        if baseline.get(key, default) != candidate.get(key, default):
            changed.add(key)
    return changed


def _literal(value: object) -> str:
    import json

    return value if isinstance(value, str) else json.dumps(value, allow_nan=False)
