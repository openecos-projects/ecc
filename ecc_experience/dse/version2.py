"""Versioned DSE specification and frozen-plan compatibility boundary."""

import math
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ecc_experience.dse.multiobjective import resolve_objectives
from ecc_experience.dse.patience import resolve_patience
from ecc_experience.dse.plan import (
    _Plan,
    invalid,
    parse_limits,
    plan_dse,
    validate_parameter_boundary,
)
from ecc_experience.dse.space import Axis, candidate, expand_space, grid_candidates
from ecc_experience.dse.warm_start import freeze_warm_start
from ecc_experience.files import digest, read_json
from ecc_experience.knowledge.features import case_features
from ecc_experience.optimization.plan import write_plan


class ObjectiveSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    metric: str
    unit: str
    direction: Literal["minimize", "maximize"]
    step: str | None = None
    scope: str | None = None
    corner: str | None = None


class RungSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    through_step: str
    promote_count: int = Field(ge=1, le=98)
    objectives: list[ObjectiveSpec] | None = Field(default=None, min_length=1, max_length=3)


class DseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[2]
    strategy: Literal["grid", "adaptive"] = "grid"
    seed: int = Field(ge=0, le=2**32 - 1)
    space: dict[str, Axis]
    objectives: list[ObjectiveSpec] = Field(min_length=1, max_length=3)
    rungs: list[RungSpec] = Field(min_length=1, max_length=3)
    limits: dict
    warm_start: str | None = None
    warm_start_limit: int = Field(default=3, ge=1, le=20)
    baseline_case_id: str | None = None


class FrozenObjective(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    step: str
    id: str
    unit: str
    scope: str | None
    corner: str | None
    direction: Literal["minimize", "maximize"]


class FrozenRung(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    through_step: str
    promote_count: int = Field(ge=1, le=98)
    objectives: list[FrozenObjective] = Field(min_length=1, max_length=3)


def plan_version2(project, workspace, store, output, *, spec) -> dict:
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise invalid("DSE plan output must be new")
    try:
        settings = DseSpec.model_validate(read_json(Path(spec).expanduser()))
    except ValidationError as exc:
        raise invalid(str(exc)) from exc
    space = expand_space(settings.space)
    grid_size = math.prod(len(values) for values in space.values())
    requested_patience = settings.limits.get("patience", 3)
    planning_limits = {**settings.limits, "patience": requested_patience}
    if requested_patience == "auto":
        planning_limits["patience"] = 1
    limits = parse_limits(planning_limits)
    later_trials = sum(rung.promote_count for rung in settings.rungs[:-1])
    screens = min(grid_size, limits.max_trials - 2 - later_trials)
    if screens < 1 or (settings.strategy == "grid" and screens != grid_size):
        raise invalid("Reserve all rung trials and two independent full/fresh validations")
    if any(
        right.promote_count > left.promote_count
        for left, right in zip(settings.rungs[:-1], settings.rungs[1:], strict=True)
    ):
        raise invalid("Rung promotion counts must not increase")
    if settings.rungs[0].promote_count > screens:
        raise invalid("Rung promotion count exceeds first-rung candidates")
    resolved_patience, patience_resolution = resolve_patience(
        requested_patience,
        strategy=settings.strategy,
        domain_size=grid_size,
        screening_trials=screens,
    )
    limits = parse_limits({**planning_limits, "patience": resolved_patience})
    first = candidate({key: values[0] for key, values in space.items()}, "candidate-0001")
    main = settings.objectives[0]
    with tempfile.TemporaryDirectory(prefix="ecc-dse-plan-") as temporary:
        base = plan_dse(
            project,
            workspace,
            store,
            Path(temporary) / "base.json",
            parameters=first["sets"],
            through_step=settings.rungs[-1].through_step,
            metric=main.metric,
            unit=main.unit,
            direction=main.direction,
            limits=limits.model_dump(),
            release=(Path(spec).expanduser().resolve().parent / settings.warm_start).resolve()
            if settings.warm_start
            else None,
            baseline_case_id=settings.baseline_case_id,
        )
    base.pop("plan", None)
    if any(
        destination.resolve().is_relative_to(Path(base[key]))
        for key in ("baseline_workspace", "store")
    ):
        raise invalid("DSE plan output must be outside source and store")
    features = case_features(base["baseline_case_id"], store)
    names = [step["step"] for step in features["steps"]]
    rungs = []
    last_index = -1
    for rung in settings.rungs:
        if rung.through_step not in names or rung.through_step.casefold() not in {
            "postfloorplan",
            "place",
            "cts",
        }:
            raise invalid("Rungs must name existing postFloorplan, place or CTS steps")
        index = names.index(rung.through_step)
        if index <= last_index:
            raise invalid("Rungs must follow the source flow order")
        prefix = case_features(base["baseline_case_id"], store, through_step=rung.through_step)
        objective_specs = rung.objectives or settings.objectives
        objectives = resolve_objectives([item.model_dump() for item in objective_specs], prefix)
        if objectives[0]["step"] != rung.through_step:
            raise invalid("The first objective must measure the rung's final step")
        rungs.append(
            {
                "through_step": rung.through_step,
                "promote_count": rung.promote_count,
                "objectives": objectives,
            }
        )
        last_index = index
    validate_parameter_boundary(list(space), names[: last_index + 1])
    objectives = resolve_objectives(
        [item.model_dump() for item in settings.objectives],
        case_features(base["baseline_case_id"], store, through_step=base["through_step"]),
    )
    if objectives != rungs[-1]["objectives"]:
        raise invalid("Final rung objectives must equal the plan objectives")
    payload = {
        **base,
        "schema": "ecc-experience-stage-dse-plan/2",
        "strategy": settings.strategy,
        "space": space,
        "algorithm": {
            "name": "categorical_tpe" if settings.strategy == "adaptive" else "grid",
            "version": 1,
            "seed": settings.seed,
        },
        "objectives": objectives,
        "rungs": rungs,
        "screening_trials": screens,
        "patience_resolution": patience_resolution,
        "candidates": grid_candidates(space) if settings.strategy == "grid" else [],
        "warm_start": {
            "release": base["release"],
            "limit": settings.warm_start_limit,
            "seeds": [],
            "status": "not_requested",
        },
        "parameter_boundary": base["through_step"],
    }
    payload["warm_start"] = freeze_warm_start(payload, settings.warm_start_limit)
    payload["plan_fingerprint"] = digest(
        {key: value for key, value in payload.items() if key != "plan_fingerprint"}
    )
    validate_version2(payload)
    return write_plan(destination, payload)


def validate_version2(payload: dict):
    extensions = {
        "strategy",
        "space",
        "algorithm",
        "objectives",
        "rungs",
        "screening_trials",
        "patience_resolution",
        "warm_start",
        "parameter_boundary",
    }
    base = {key: value for key, value in payload.items() if key not in extensions}
    base["schema"] = "ecc-experience-stage-dse-plan/1"
    try:
        _Plan.model_validate(base)
        space = expand_space({key: Axis(values=values) for key, values in payload["space"].items()})
        if (
            payload["strategy"] not in {"grid", "adaptive"}
            or payload["algorithm"]
            != {
                "name": "categorical_tpe" if payload["strategy"] == "adaptive" else "grid",
                "version": 1,
                "seed": payload["algorithm"]["seed"],
            }
            or type(payload["algorithm"]["seed"]) is not int
            or not 0 <= payload["algorithm"]["seed"] <= 2**32 - 1
        ):
            raise invalid("Unsupported DSE strategy or algorithm")
        limits = parse_limits(payload["limits"])
        count = payload["screening_trials"]
        resolution = payload.get("patience_resolution")
        if resolution is not None:
            if not isinstance(resolution, dict):
                raise invalid("Frozen DSE patience resolution is invalid")
            requested = resolution.get("requested")
            if not isinstance(requested, (int, str)):
                raise invalid("Frozen DSE patience request is invalid")
            resolved, expected_resolution = resolve_patience(
                requested,
                strategy=payload["strategy"],
                domain_size=math.prod(len(values) for values in space.values()),
                screening_trials=count,
            )
            if resolved != limits.patience or resolution != expected_resolution:
                raise invalid("Frozen DSE patience resolution is inconsistent")
        rungs = [FrozenRung.model_validate(item).model_dump() for item in payload["rungs"]]
        if not isinstance(rungs, list) or not 1 <= len(rungs) <= 3:
            raise invalid("Invalid DSE rungs")
        if (
            type(count) is not int
            or count < 1
            or count + 2 + sum(rung["promote_count"] for rung in rungs[:-1]) > limits.max_trials
        ):
            raise invalid("DSE budget does not cover rungs and full/fresh validation")
        if payload["strategy"] == "grid" and (
            payload["candidates"] != grid_candidates(space) or count != len(payload["candidates"])
        ):
            raise invalid("Grid candidates differ from frozen space")
        if payload["strategy"] == "adaptive" and payload["candidates"]:
            raise invalid("Adaptive candidates are generated from recorded observations")
        if (
            count > math.prod(len(values) for values in space.values())
            or rungs[0]["promote_count"] > count
            or any(
                right["promote_count"] > left["promote_count"]
                for left, right in zip(rungs[:-1], rungs[1:], strict=True)
            )
            or rungs[-1]["through_step"] != payload["through_step"]
            or payload["parameter_boundary"] != payload["through_step"]
            or rungs[-1]["objectives"] != payload["objectives"]
        ):
            raise invalid("Frozen DSE objectives, rung order or budgets are inconsistent")
        from chipcompiler.analysis.qor.metric_registry import METRIC_REGISTRY

        features = case_features(payload["baseline_case_id"], payload["store"])
        names = [step["step"] for step in features["steps"]]
        previous = -1
        for rung in rungs:
            boundary = rung["through_step"]
            if boundary not in names or boundary.casefold() not in {
                "postfloorplan",
                "place",
                "cts",
            }:
                raise invalid("Unsupported rung boundary")
            index = names.index(boundary)
            if index <= previous:
                raise invalid("Frozen rungs must follow source flow order")
            previous = index
            if rung["objectives"][0]["step"] != rung["through_step"]:
                raise invalid("First objective must measure the rung boundary")
            if len({objective["id"] for objective in rung["objectives"]}) != len(
                rung["objectives"]
            ):
                raise invalid("Objective IDs must be unique")
            for objective in rung["objectives"]:
                if objective["step"] not in names[: index + 1]:
                    raise invalid("Frozen objective is outside its measured prefix")
                polarity = (
                    "lower_is_better"
                    if objective["direction"] == "minimize"
                    else "higher_is_better"
                )
                if METRIC_REGISTRY.get(objective["id"]) != (objective["unit"], polarity):
                    raise invalid("Frozen objective differs from the metric registry")
        validate_parameter_boundary(list(space), names[: previous + 1])
        warm = payload["warm_start"]
        if (
            set(warm) != {"release", "limit", "seeds", "status"}
            or warm["release"] != payload["release"]
            or type(warm["limit"]) is not int
            or not 1 <= warm["limit"] <= 20
            or not isinstance(warm["seeds"], list)
            or len(warm["seeds"]) > warm["limit"]
            or warm["status"] not in {"not_requested", "matches_available", "insufficient_evidence"}
        ):
            raise invalid("Invalid frozen warm-start provenance")
        for seed in warm["seeds"]:
            if (
                set(seed) != {"case_id", "distance", "parameters", "compatibility"}
                or not isinstance(seed["case_id"], str)
                or not seed["case_id"]
                or type(seed["distance"]) not in (int, float)
                or not math.isfinite(seed["distance"])
                or seed["distance"] < 0
                or seed["compatibility"] != "selected_process_tool_analysis_match"
                or set(seed["parameters"]) != set(space)
                or any(value not in space[key] for key, value in seed["parameters"].items())
            ):
                raise invalid("Warm-start seed is outside frozen space")
        if (warm["status"] == "matches_available") != bool(warm["seeds"]) or (
            (warm["status"] == "not_requested") != (warm["release"] is None)
        ):
            raise invalid("Warm-start status differs from frozen provenance")
    except (KeyError, TypeError, ValidationError) as exc:
        raise invalid("Invalid version 2 DSE plan") from exc
    return limits
