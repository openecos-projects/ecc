"""Validate a generic, execution-neutral benchmark specification."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ecc_experience.files import digest
from ecc_experience.models import ExperienceError


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BenchmarkBudget(_Model):
    max_concurrent_flows: int = Field(default=1, ge=1, le=1024)
    max_trials_per_design: int = Field(default=1, ge=1, le=100000)
    timeout_seconds_per_trial: int = Field(default=3600, ge=1, le=31_536_000)


class BenchmarkDesign(_Model):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    project: str = Field(min_length=1, max_length=4096)
    workspace: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    family: str | None = Field(default=None, max_length=128)
    plans: dict[str, str] = Field(default_factory=dict)

    @property
    def valid_plan_keys(self) -> bool:
        return all(key in {"baseline", "grid", "adaptive", "warm"} for key in self.plans)


class BenchmarkAcceptance(_Model):
    min_independent_designs: int = Field(default=3, ge=1, le=10000)
    min_families: int = Field(default=2, ge=1, le=10000)
    min_candidate_configurations: int = Field(default=2, ge=1, le=100000)


class BenchmarkSpec(_Model):
    schema_version: Literal[1]
    benchmark_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    process_profile: str = Field(min_length=1, max_length=128)
    strategies: list[Literal["baseline", "grid", "adaptive", "warm"]] = Field(
        min_length=1, max_length=4
    )
    budget: BenchmarkBudget = BenchmarkBudget()
    acceptance: BenchmarkAcceptance = BenchmarkAcceptance()
    designs: list[BenchmarkDesign] = Field(min_length=1, max_length=10000)


def validate(path: str | Path) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        model = BenchmarkSpec.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ExperienceError(
            "Benchmark spec is invalid", code="experience_benchmark_invalid"
        ) from exc
    if len(set(model.strategies)) != len(model.strategies):
        raise ExperienceError(
            "Benchmark strategies must be unique", code="experience_benchmark_invalid"
        )
    if len({design.id for design in model.designs}) != len(model.designs):
        raise ExperienceError(
            "Benchmark design IDs must be unique", code="experience_benchmark_invalid"
        )
    if model.budget.max_concurrent_flows != 1:
        raise ExperienceError(
            "Only serial benchmark execution is currently supported",
            code="experience_benchmark_invalid",
        )
    if any(not design.valid_plan_keys for design in model.designs):
        raise ExperienceError(
            "Benchmark plan keys are invalid", code="experience_benchmark_invalid"
        )
    for design in model.designs:
        if any(strategy not in model.strategies for strategy in design.plans):
            raise ExperienceError(
                f"Design plan is not declared in strategies: {design.id}",
                code="experience_benchmark_invalid",
            )
    family_count = len({design.family for design in model.designs if design.family is not None})
    return {
        "schema": "ecc-experience-benchmark-spec/1",
        "status": "valid",
        "spec": str(source),
        "spec_sha256": digest(model.model_dump()),
        "benchmark_id": model.benchmark_id,
        "process_profile": model.process_profile,
        "strategies": list(model.strategies),
        "design_count": len(model.designs),
        "family_count": family_count,
        "declared_family_count": sum(design.family is not None for design in model.designs),
        "budget": model.budget.model_dump(),
        "acceptance": model.acceptance.model_dump(),
        "designs": [
            {
                "id": design.id,
                "project": design.project,
                "workspace": design.workspace,
                "family": design.family,
                "plans": design.plans,
            }
            for design in model.designs
        ],
        "execution": {
            "mode": "serial",
            "eda_started": False,
            "plans_only": True,
        },
    }
