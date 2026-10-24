"""Prepare explicitly selected project workspaces for an isolated campaign."""

import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chipcompiler.project.manifest import CONFIG_FILENAME
from chipcompiler.project.manifest import load_manifest as load_project
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.benchmark.manifest import (
    CampaignBudget,
    CampaignDesign,
    CampaignInput,
    CampaignManifest,
    load_manifest,
)
from ecc_experience.files import read_json
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.process import CliRunner, cancellation_signals


class SourceDesign(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    project: str
    workspace: str
    labels: list[str] = Field(default_factory=list)
    evaluation_group: str | None = None


class CampaignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int
    campaign_id: str
    process_profile: str
    budget: CampaignBudget
    designs: list[SourceDesign] = Field(min_length=1, max_length=10000)


def create_campaign(spec: str | Path, output: str | Path) -> dict:
    spec_path = Path(spec).expanduser().resolve()
    destination = Path(output).expanduser().absolute()
    try:
        settings = CampaignSpec.model_validate(read_json(spec_path, 1024 * 1024))
    except ValidationError as exc:
        raise ExperienceError(str(exc), code="experience_manifest_invalid") from exc
    if settings.schema_version != 1 or settings.budget.max_concurrent_flows != 1:
        raise ExperienceError(
            "Campaign creation requires schema_version=1 and serial execution",
            code="experience_manifest_invalid",
        )
    if destination.exists() or destination.is_symlink():
        raise ExperienceError("Campaign output must be new", code="experience_manifest_invalid")
    designs = []
    sources = []
    for source in settings.designs:
        try:
            design = CampaignDesign(
                id=source.id,
                input=CampaignInput(kind="ecc-project", path=f"inputs/{source.id}"),
                workspace="baseline",
                labels=source.labels,
                evaluation_group=source.evaluation_group,
            )
        except ValidationError as exc:
            raise ExperienceError(str(exc), code="experience_manifest_invalid") from exc
        project = (spec_path.parent / Path(source.project).expanduser()).resolve()
        try:
            manifest = load_project(str(project))
        except ValueError as exc:
            raise ExperienceError(str(exc), code="experience_project_invalid") from exc
        entry = manifest.find_workspace(source.workspace)
        if entry is None:
            raise ExperienceError(
                f"Source workspace is not declared: {source.id}",
                code="experience_campaign_design_invalid",
            )
        workspace = Path(entry.workspace_path).resolve()
        if any(
            destination.resolve().is_relative_to(root) or root.is_relative_to(destination.resolve())
            for root in (project, workspace)
        ):
            raise ExperienceError(
                "Campaign output overlaps a source project or workspace",
                code="experience_manifest_invalid",
            )
        observation = read_workspace_observation(workspace)
        if (
            observation.source.snapshot_digest is None
            or observation.facts.get("workspaceSpec", {}).get("pdk", {}).get("familyId")
            != settings.process_profile
        ):
            raise ExperienceError(
                "Source requires a committed snapshot and matching process profile",
                code="experience_campaign_design_invalid",
            )
        if not observation.inputs or any(item.status != "available" for item in observation.inputs):
            raise ExperienceError(
                "Source inputs must be readable", code="experience_campaign_design_invalid"
            )
        sources.append((manifest.design_name, workspace, observation))
        designs.append(design.model_dump())
    if len({item["id"] for item in designs}) != len(designs):
        raise ExperienceError("Design IDs must be unique", code="experience_manifest_invalid")
    manifest_payload = {
        "schema_version": 1,
        "campaign_id": settings.campaign_id,
        "process_profile": settings.process_profile,
        "mode": "baseline",
        "store": "store",
        "output_root": "runs",
        "budget": settings.budget.model_dump(),
        "designs": designs,
    }
    try:
        CampaignManifest.model_validate(manifest_payload)
    except ValidationError as exc:
        raise ExperienceError(str(exc), code="experience_manifest_invalid") from exc
    destination.mkdir(parents=True, exist_ok=False)
    for directory in (
        "inputs",
        "store",
        "runs",
        "reports",
        "logs",
        "artifacts/releases",
        "artifacts/datasets",
        "artifacts/models",
        "artifacts/packages",
    ):
        (destination / directory).mkdir(parents=True, exist_ok=True)
    audit: dict = {
        "schema": "ecc-experience-campaign-creation/1",
        "status": "preparing",
        "commands": [],
    }
    audit_path = destination / "logs/create.json"
    write_plan(audit_path, audit)
    runner = CliRunner(destination / "logs", time.monotonic() + 3600)
    try:
        with cancellation_signals():
            for design, (name, workspace, observation) in zip(designs, sources, strict=True):
                project = destination / design["input"]["path"]
                commands = [
                    ["init", str(project), "--design-name", name, "--plain"],
                    [
                        "workspace",
                        "import",
                        "source",
                        "--path",
                        str(workspace),
                        "--project",
                        str(project),
                        "--no-wait",
                        "--plain",
                    ],
                    [
                        "workspace",
                        "derive",
                        "source",
                        "baseline",
                        "--project",
                        str(project),
                        "--no-wait",
                        "--plain",
                    ],
                ]
                for arguments in commands:
                    result = runner.invoke(arguments, deadline=runner.deadline)
                    audit["commands"].append(
                        {
                            "design_id": design["id"],
                            "arguments": arguments,
                            "exit_code": result.exit_code,
                            "stdout": str(result.stdout),
                            "stderr": str(result.stderr),
                        }
                    )
                    write_plan(audit_path, audit)
                    if result.exit_code != 0:
                        raise ExperienceError(
                            f"Campaign preparation failed; see {audit_path}",
                            code="experience_campaign_creation_failed",
                        )
                    if arguments[0] == "init":
                        (project / CONFIG_FILENAME).unlink()
                current = read_workspace_observation(workspace)
                if (current.source.snapshot_digest, current.inputs) != (
                    observation.source.snapshot_digest,
                    observation.inputs,
                ):
                    raise ExperienceError(
                        "Source changed during creation", code="experience_source_changed"
                    )
            write_plan(destination / "campaign.json", manifest_payload)
            _model, summary = load_manifest(destination / "campaign.json")
            (destination / "README.md").write_text(
                "# ECC experience campaign\n\n"
                "campaign.json is the manifest; inputs/ contains prepared projects.\n"
                "runs/ and store/ are managed by ECC. reports/, logs/ and artifacts/ "
                "separate reports, command evidence and reusable knowledge.\n\n"
                "Validate, then run with `ecc experience campaign run --manifest campaign.json`.\n"
                "Export a matrix with `ecc experience campaign report --manifest campaign.json "
                "--output reports/matrix`.\n"
                "Declared RTL/PDK inputs may still reference external files; this is not a "
                "self-contained reproducible archive. Do not move active campaign paths.\n",
                encoding="utf-8",
            )
            audit.update(status="complete", manifest=summary["manifest"])
            return {
                **summary,
                "status": "created",
                "directory": str(destination),
                "eda_executed": False,
            }
    except BaseException:
        audit["status"] = "failed"
        raise
    finally:
        write_plan(audit_path, audit)
