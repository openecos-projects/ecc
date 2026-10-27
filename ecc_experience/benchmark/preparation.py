"""Read-only campaign input and observed-runtime identity checks."""

import sys
from dataclasses import dataclass
from pathlib import Path

from chipcompiler import __version__
from chipcompiler.cli.core.version_info import distribution_version
from chipcompiler.cli.inspection.tool_versions import tool_versions
from chipcompiler.project.manifest import (
    CONFIG_FILENAME,
    MANIFEST_FILENAME,
    ManifestError,
    load_manifest,
)
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.adapters.process_context import process_context
from ecc_experience.benchmark.manifest import CampaignManifest
from ecc_experience.files import digest, file_digest
from ecc_experience.models import ExperienceError, WorkspaceObservation


@dataclass(frozen=True)
class PreparedDesign:
    design_id: str
    project: Path
    workspace: Path
    design_name: str
    observation: WorkspaceObservation
    fingerprint: str
    process_context: dict


def prepare(
    manifest: CampaignManifest,
    summary: dict,
    *,
    design_id: str | None = None,
) -> list[PreparedDesign]:
    if manifest.budget.max_concurrent_flows != 1 or manifest.knowledge_release_id is not None:
        raise ExperienceError(
            "Baseline execution requires max_concurrent_flows=1 and no knowledge_release_id",
            code="experience_manifest_invalid",
        )
    prepared = []
    for design in manifest.designs:
        if design_id is not None and design.id != design_id:
            continue
        project = (Path(summary["manifest_root"]) / design.input.path).resolve()
        try:
            source = load_manifest(str(project))
        except (ManifestError, OSError) as exc:
            raise ExperienceError(str(exc), code="experience_manifest_invalid") from exc
        entry = source.find_workspace(design.workspace)
        if entry is None:
            raise ExperienceError(
                f"Source workspace is not declared: {design.id}/{design.workspace}",
                code="experience_campaign_design_invalid",
            )
        workspace = Path(entry.workspace_path).resolve()
        if any(
            workspace.is_relative_to(Path(summary[key]))
            or Path(summary[key]).is_relative_to(workspace)
            for key in ("store", "output_root")
        ):
            raise ExperienceError(
                "Campaign store/output overlaps a source workspace",
                code="experience_manifest_invalid",
            )
        observation = read_workspace_observation(workspace)
        for reference in observation.facts.get("workspaceBindings", {}).get("inputs", {}).values():
            if isinstance(reference, str) and any(
                Path(reference).resolve().is_relative_to(Path(summary[key]))
                for key in ("store", "output_root")
            ):
                raise ExperienceError(
                    "Campaign output/store overlaps a declared source input",
                    code="experience_manifest_invalid",
                )
        spec = observation.facts.get("workspaceSpec", {})
        if (
            observation.source.snapshot_digest is None
            or not observation.inputs
            or any(item.sha256 is None for item in observation.inputs)
            or spec.get("pdk", {}).get("familyId") != manifest.process_profile
        ):
            raise ExperienceError(
                "Source requires a committed snapshot, readable inputs and matching PDK: "
                f"{design.id}",
                code="experience_campaign_design_invalid",
            )
        files = {
            name: file_digest(project / name)[0] if (project / name).exists() else None
            for name in (MANIFEST_FILENAME, CONFIG_FILENAME)
        }
        process = process_context(observation.facts)
        prepared.append(
            PreparedDesign(
                design.id,
                project,
                workspace,
                source.design_name,
                observation,
                digest(
                    {
                        "project": str(project),
                        "workspace": str(workspace),
                        "files": files,
                        "snapshot": observation.source.snapshot_digest,
                        "inputs": [item.model_dump() for item in observation.inputs],
                        "process": process,
                    }
                ),
                process,
            )
        )
    return prepared


def runtime_identity() -> dict:
    import chipcompiler
    import ecc_experience

    sources = {}
    for package in (chipcompiler, ecc_experience):
        filename = package.__file__
        if filename is None:
            raise ExperienceError("ECC package source identity is unavailable")
        root = Path(filename).parent
        sources[package.__name__] = digest(
            {
                str(path.relative_to(root)): file_digest(path)[0]
                for path in sorted(root.rglob("*.py"))
                if "thirdparty" not in path.relative_to(root).parts
            }
        )
    return {
        "ecc": __version__,
        "sources": sources,
        "frozen_binary_sha256": file_digest(Path(sys.executable))[0]
        if getattr(sys, "frozen", False)
        else None,
        "tools": tool_versions(),
        "native_packages": {
            name: distribution_version(name) for name in ("ecc-tools-bin", "ecc-dreamplace")
        },
    }


def assert_inputs(
    manifest: CampaignManifest,
    summary: dict,
    expected: dict,
    *,
    design_id: str,
) -> None:
    try:
        actual = {
            item.design_id: item.fingerprint
            for item in prepare(manifest, summary, design_id=design_id)
        }
    except (ExperienceError, OSError) as exc:
        if isinstance(exc, ExperienceError) and exc.code == "experience_workspace_busy":
            raise
        raise ExperienceError(
            "Campaign source is no longer readable", code="experience_source_changed"
        ) from exc
    if actual != {design_id: expected[design_id]}:
        raise ExperienceError(
            "Campaign source configuration or declared inputs changed",
            code="experience_source_changed",
        )
