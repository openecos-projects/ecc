import itertools
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chipcompiler.cli.experiments.operations import parse_parameters
from chipcompiler.data.parameter_schema import lookup_schema, parse_cli_overrides
from chipcompiler.data.workspace_parameters import workspace_param_step
from chipcompiler.project.manifest import load_manifest
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.adapters.process_context import process_context
from ecc_experience.benchmark.preparation import runtime_identity
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.files import digest, read_json
from ecc_experience.knowledge.features import case_features
from ecc_experience.knowledge.release import verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.policy import SUPPORTED_PARAMETERS, validate_reviewed_values

STAGE_PARAMETERS = frozenset(key for key in SUPPORTED_PARAMETERS if not key.startswith("route."))


class DseLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_trials: int = Field(ge=3, le=100)
    max_seconds: int = Field(ge=1)
    trial_timeout_seconds: int = Field(ge=1)
    patience: int = Field(default=3, ge=1)


class _Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidate_id: str
    parameters: dict
    sets: list[str]


class _Objective(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    unit: str
    scope: str | None
    corner: str | None


class _Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_id: Literal["ecc-experience-stage-dse-plan/1"] = Field(alias="schema")
    project: str
    source_workspace_id: str
    baseline_workspace: str
    baseline_case_id: str
    snapshot_digest: str
    input_content_fingerprint: str
    process: dict
    runtime: dict
    project_configuration: str
    store: str
    first_step: str
    through_step: str
    objective: _Objective
    direction: Literal["minimize", "maximize"]
    baseline_stage_value: float
    limits: DseLimits
    candidates: list[_Candidate]
    release: str | None
    release_id: str | None
    validation_policy: Literal["stage_screen_then_independent_full_and_fresh"]
    plan_fingerprint: str


def invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_plan_invalid")


def plan_dse(
    project: str | Path,
    workspace: str | Path,
    store: str | Path,
    output: str | Path,
    *,
    parameters: list[str],
    through_step: str,
    metric: str,
    unit: str,
    direction: str,
    limits: dict,
    release: str | Path | None = None,
) -> dict:
    root = Path(project).expanduser().resolve()
    source = Path(workspace).expanduser().resolve()
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise invalid("DSE plan output must be a new file")
    if any(
        destination.resolve().is_relative_to(item)
        for item in (source, Path(store).expanduser().resolve())
    ):
        raise invalid("DSE plan output must be outside the source workspace and store")
    manifest = load_manifest(str(root))
    entry = next(
        (item for item in manifest.workspaces if Path(item.workspace_path).resolve() == source),
        None,
    )
    if entry is None:
        raise invalid("DSE source must be a declared project workspace")
    bounded = parse_limits(limits)
    if direction not in {"minimize", "maximize"}:
        raise invalid("Direction must be minimize or maximize")
    keys = [item.split("=", 1)[0] for item in parameters]
    if len(set(keys)) != len(keys) or not set(keys) <= STAGE_PARAMETERS:
        raise invalid("Parameters must be unique reviewed floorplan, placement or CTS keys")
    try:
        grid = parse_parameters(parameters)
    except ValueError as exc:
        raise invalid(str(exc)) from exc
    count = math.prod(len(values) for values in grid.values())
    if count > bounded.max_trials - 2:
        raise invalid("Grid exceeds screening budget; reserve two full-flow validation trials")
    captured = collect_committed_case(source, ExperienceStore(store), read_workspace_observation)
    baseline = captured.case
    features = case_features(baseline.case_id, store, through_step=through_step)
    names = [item["step"] for item in features["steps"]]
    if through_step.casefold() not in {
        "postfloorplan",
        "floorplan",
        "place",
        "cts",
        "legalization",
    }:
        raise invalid("DSE currently supports early floorplan, placement and CTS boundaries")
    validate_parameter_boundary(keys, names)
    selected = [
        item
        for item in features["steps"][-1]["metrics"]
        if item["id"] == metric and item["unit"] == unit and item["status"] == "available"
    ]
    if len(selected) != 1:
        raise invalid(
            "Objective must uniquely identify an available baseline stage metric and unit"
        )
    candidates = []
    ordered = sorted(grid)
    for index, values in enumerate(itertools.product(*(grid[key] for key in ordered)), 1):
        pairs = [f"{key}={value}" for key, value in zip(ordered, values, strict=True)]
        parsed, errors = parse_cli_overrides(pairs)
        if errors:
            raise invalid("; ".join(errors))
        validate_reviewed_values(parsed, baseline.facts)
        candidates.append(
            {"candidate_id": f"candidate-{index:04d}", "parameters": parsed, "sets": pairs}
        )
    frozen = verify_release(release, store) if release else None
    if frozen and frozen["status"] != "pass":
        raise invalid("Knowledge release must pass verification")
    payload = {
        "schema": "ecc-experience-stage-dse-plan/1",
        "project": str(root),
        "source_workspace_id": entry.workspace_id,
        "baseline_workspace": str(source),
        "baseline_case_id": baseline.case_id,
        "snapshot_digest": baseline.source.snapshot_digest,
        "input_content_fingerprint": baseline.input_content_fingerprint,
        "process": process_context(baseline.facts),
        "runtime": runtime_identity(),
        "project_configuration": project_configuration(root),
        "store": str(Path(store).expanduser().resolve()),
        "first_step": names[0],
        "through_step": through_step,
        "objective": {key: selected[0][key] for key in ("id", "unit", "scope", "corner")},
        "direction": direction,
        "baseline_stage_value": selected[0]["value"],
        "limits": bounded.model_dump(),
        "candidates": candidates,
        "release": str(Path(release).expanduser().resolve()) if release else None,
        "release_id": frozen["release_id"] if frozen else None,
        "validation_policy": "stage_screen_then_independent_full_and_fresh",
    }
    payload["plan_fingerprint"] = digest(payload)
    return write_plan(output, payload)


def parse_limits(value: dict) -> DseLimits:
    try:
        limits = DseLimits.model_validate(value)
    except ValidationError as exc:
        raise invalid(str(exc)) from exc
    if limits.trial_timeout_seconds > limits.max_seconds:
        raise invalid("Per-trial timeout must not exceed total time budget")
    return limits


def read_dse_plan(path: str | Path) -> tuple[dict, DseLimits]:
    payload = read_json(Path(path).expanduser())
    if payload.get("schema") == "ecc-experience-stage-dse-plan/2":
        from ecc_experience.dse.version2 import validate_version2

        if payload.get("plan_fingerprint") != digest(
            {key: value for key, value in payload.items() if key != "plan_fingerprint"}
        ):
            raise invalid("Invalid version 2 DSE plan fingerprint")
        return payload, validate_version2(payload)
    try:
        _Plan.model_validate(payload)
    except ValidationError as exc:
        raise invalid(str(exc)) from exc
    if payload.get("schema") != "ecc-experience-stage-dse-plan/1" or payload.get(
        "plan_fingerprint"
    ) != digest({key: value for key, value in payload.items() if key != "plan_fingerprint"}):
        raise invalid("Invalid stage DSE plan or fingerprint")
    limits = parse_limits(payload["limits"])
    if (
        not isinstance(payload.get("candidates"), list)
        or not 1 <= len(payload["candidates"]) <= limits.max_trials - 2
    ):
        raise invalid("DSE candidate count exceeds the reserved budget")
    for candidate in payload["candidates"]:
        if (
            not isinstance(candidate, dict)
            or not isinstance(candidate.get("parameters"), dict)
            or not isinstance(candidate.get("sets"), list)
        ):
            raise invalid("Invalid DSE candidate")
        if not set(candidate["parameters"]) <= STAGE_PARAMETERS or not candidate["parameters"]:
            raise invalid("DSE candidate has unsupported parameters")
        parsed, errors = parse_cli_overrides(candidate["sets"])
        if errors or parsed != candidate["parameters"]:
            raise invalid("DSE candidate values do not match validated parameter arguments")
        validate_reviewed_values(parsed, {})
    if payload.get("direction") not in {"minimize", "maximize"}:
        raise invalid("Invalid DSE objective direction")
    return payload, limits


def project_configuration(root: Path) -> str:
    from ecc_experience.files import file_digest

    manifest = read_json(root / "project.json")
    settings = root / "ecc.toml"
    return digest(
        {
            "project": {
                key: value
                for key, value in manifest.items()
                if key not in {"workspaces", "updated_at"}
            },
            "ecc_toml": file_digest(settings)[0] if settings.is_file() else None,
        }
    )


def validate_parameter_boundary(keys: list[str], names: list[str]) -> None:
    aliases = {item.casefold().replace(" ", "") for item in names}
    if not names or names[-1].casefold() not in {
        "postfloorplan",
        "floorplan",
        "place",
        "cts",
        "legalization",
    }:
        raise invalid("Unsupported early PNR boundary")
    for key in keys:
        schema = lookup_schema(key)
        if schema is None:
            raise invalid("Parameter is absent from the current catalog")
        affected = workspace_param_step(schema).casefold().replace(" ", "")
        present = (
            bool(aliases & {"floorplan", "prefloorplan", "postfloorplan"})
            if affected == "floorplan"
            else affected in aliases
        )
        if not present:
            raise invalid(f"Parameter {key} is not active before the selected boundary")
