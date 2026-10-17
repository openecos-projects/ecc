"""Materialize an execution-neutral benchmark plan without running EDA."""

from pathlib import Path

from ecc_experience.benchmark.spec import validate
from ecc_experience.files import canonical_bytes, digest
from ecc_experience.models import ExperienceError


def materialize(spec: str | Path, output: str | Path) -> dict:
    source = Path(spec).expanduser().resolve()
    destination = Path(output).expanduser().absolute()
    validated = validate(source)
    if destination.exists() or destination.is_symlink():
        raise ExperienceError(
            "Benchmark plan output must be new", code="experience_benchmark_invalid"
        )
    designs = validated["designs"]
    _reject_project_overlap(source, destination, designs)
    strategies = validated["strategies"]
    entries = []
    missing_plans = []
    for design in designs:
        for strategy in strategies:
            plan_ref = design["plans"].get(strategy)
            plan_path = _plan_path(source, plan_ref, design["id"], strategy)
            status = "ready"
            if (strategy != "baseline" and plan_path is None) or (
                plan_path is not None and not plan_path.is_file()
            ):
                status = "pending_plan"
                missing_plans.append(f"{design['id']}/{strategy}")
            observation_id = f"{design['id']}--{strategy}"
            entries.append(
                {
                    "observation_id": observation_id,
                    "design_id": design["id"],
                    "strategy": strategy,
                    "family": design["family"],
                    "project": design["project"],
                    "workspace": design["workspace"],
                    "source_plan": plan_ref,
                    "source_plan_sha256": (
                        _sha256(plan_path) if plan_path and plan_path.is_file() else None
                    ),
                    "status": status,
                    "execution": {
                        "mode": "manual_review",
                        "eda_started": False,
                        "output_root": f"runs/{strategy}/{design['id']}",
                        "command": _command(strategy, plan_ref, observation_id),
                    },
                }
            )
    plan = {
        "schema": "ecc-experience-benchmark-plan/1",
        "status": "ready" if not missing_plans else "pending",
        "exit_code": 0 if not missing_plans else 7,
        "spec": str(source),
        "spec_sha256": validated["spec_sha256"],
        "benchmark_id": validated["benchmark_id"],
        "process_profile": validated["process_profile"],
        "strategies": strategies,
        "budget": validated["budget"],
        "acceptance": validated["acceptance"],
        "entries": entries,
        "missing_plans": missing_plans,
        "execution": {"mode": "serial", "eda_started": False, "plans_only": True},
        "safe_to_apply": False,
    }
    plan["plan_sha256"] = digest(plan)
    destination.mkdir(parents=True)
    _write_json(destination / "benchmark-plan.json", plan)
    _write_json(destination / "expected-designs.json", [item["observation_id"] for item in entries])
    _write_json(
        destination / "families.json",
        {item["observation_id"]: item["family"] for item in entries if item["family"] is not None},
    )
    if "baseline" in strategies:
        _write_json(destination / "baseline-sources.json", _baseline_sources(validated))
    (destination / "README.md").write_text(_readme(plan), encoding="utf-8")
    return {**plan, "output": str(destination)}


def _plan_path(source: Path, value: str | None, design: str, strategy: str) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ExperienceError(
            f"Benchmark plan path is invalid: {design}/{strategy}",
            code="experience_benchmark_invalid",
        )
    return (source.parent / path).resolve()


def _reject_project_overlap(source: Path, destination: Path, designs: list[dict]) -> None:
    destination = destination.resolve()
    for design in designs:
        project = Path(design["project"]).expanduser()
        project = (source.parent / project if not project.is_absolute() else project).resolve()
        if destination.is_relative_to(project) or project.is_relative_to(destination):
            raise ExperienceError(
                "Benchmark plan output overlaps a design project",
                code="experience_benchmark_invalid",
            )


def _baseline_sources(validated: dict) -> dict:
    return {
        "schema_version": 1,
        "campaign_id": f"{validated['benchmark_id']}-baseline",
        "process_profile": validated["process_profile"],
        "budget": validated["budget"],
        "designs": [
            {
                "id": item["id"],
                "project": item["project"],
                "workspace": item["workspace"],
                "labels": ["strategy:baseline"],
                "evaluation_group": item["family"],
            }
            for item in validated["designs"]
        ],
    }


def _command(strategy: str, plan: str | None, observation_id: str) -> list[str]:
    if strategy == "baseline":
        return [
            "ecc",
            "experience",
            "campaign",
            "create",
            "--spec",
            "./baseline-sources.json",
            "--output",
            "./runs/baseline/campaign",
        ]
    return [
        "ecc",
        "experience",
        "dse",
        "run",
        "--plan",
        plan or f"<missing-plan:{observation_id}>",
        "--output",
        f"./runs/{strategy}/{observation_id}",
    ]


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_bytes(value))


def _readme(plan: dict) -> str:
    status = plan["status"]
    lines = [
        "# ECC benchmark plan",
        "",
        f"Status: {status}; exit_code: {plan['exit_code']}",
        "",
        "This directory contains a frozen, execution-neutral plan. It does not copy design",
        "inputs, modify projects, create workspaces, or start EDA.",
        "",
        "1. Review benchmark-plan.json and resolve every pending_plan entry.",
        "2. Run each strategy in an independent output directory using its recorded command.",
        "3. Collect observations under the observation IDs in expected-designs.json.",
        "4. Run campaign matrix, readiness, effect, and archive after evidence is verified.",
        "",
        "The generated baseline-sources.json is an input to campaign create; it is not a run",
        "result. Keep this directory outside source projects and preserve it with the reports.",
        "",
    ]
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    import hashlib

    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()
