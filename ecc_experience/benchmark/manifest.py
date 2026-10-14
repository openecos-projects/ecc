"""Validate the generic campaign input contract used by AI-driven testing."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ecc_experience.files import digest
from ecc_experience.models import ExperienceError

_MAX_MANIFEST_BYTES = 1024 * 1024


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CampaignBudget(_Model):
    max_concurrent_flows: int = Field(ge=1, le=1024)
    max_trials_per_design: int = Field(ge=1, le=100000)
    timeout_seconds_per_trial: int = Field(ge=1, le=31_536_000)


class CampaignInput(_Model):
    kind: Literal["ecc-project"]
    path: str

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("input path must be a non-empty relative path without . or ..")
        return value


class CampaignDesign(_Model):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    input: CampaignInput
    workspace: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    labels: list[str] = Field(default_factory=list, max_length=64)
    evaluation_group: str | None = Field(default=None, max_length=128)

    @field_validator("id", "workspace")
    @classmethod
    def single_segment(cls, value: str) -> str:
        if value in {".", ".."}:
            raise ValueError("design and workspace IDs must name a single path segment")
        return value


class CampaignManifest(_Model):
    schema_version: Literal[1]
    campaign_id: str = Field(min_length=1, max_length=128, pattern=r"[A-Za-z0-9._-]+")
    process_profile: str = Field(min_length=1, max_length=128)
    store: str = Field(min_length=1, max_length=4096)
    output_root: str = Field(min_length=1, max_length=4096)
    knowledge_release_id: str | None = None
    mode: Literal["baseline"]
    budget: CampaignBudget
    designs: list[CampaignDesign] = Field(min_length=1, max_length=10000)


def load_manifest(path: str | Path) -> tuple[CampaignManifest, dict]:
    manifest_path = Path(path).expanduser()
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ExperienceError(
            "Campaign manifest does not exist", code="experience_manifest_invalid"
        )
    try:
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise ExperienceError(
                "Campaign manifest is oversized", code="experience_manifest_invalid"
            )
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = CampaignManifest.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        if isinstance(exc, ExperienceError):
            raise
        raise ExperienceError(
            "Campaign manifest is invalid", code="experience_manifest_invalid"
        ) from exc

    root = manifest_path.parent.resolve()
    designs = list(manifest.designs)
    ids = [design.id for design in designs]
    if len(set(ids)) != len(ids):
        raise ExperienceError(
            "Campaign design IDs must be unique", code="experience_manifest_invalid"
        )
    input_paths = []
    for design in designs:
        source = _contained_path(root, design.input.path, "input")
        if not source.is_dir():
            raise ExperienceError(
                f"Campaign input does not exist: {design.input.path}",
                code="experience_manifest_input_missing",
            )
        input_paths.append(source)
    output_root = _contained_path(root, manifest.output_root, "output_root")
    store = _contained_path(root, manifest.store, "store")
    if any(_overlap(output_root, source) for source in input_paths):
        raise ExperienceError(
            "Campaign output_root overlaps an input", code="experience_manifest_invalid"
        )
    if any(_overlap(store, source) for source in input_paths):
        raise ExperienceError(
            "Campaign store overlaps an input", code="experience_manifest_invalid"
        )
    if _overlap(store, output_root):
        raise ExperienceError(
            "Campaign store overlaps output_root", code="experience_manifest_invalid"
        )
    return manifest, {
        "manifest": str(manifest_path.resolve()),
        "manifest_root": str(root),
        "campaign_id": manifest.campaign_id,
        "process_profile": manifest.process_profile,
        "mode": manifest.mode,
        "design_count": len(designs),
        "design_ids": ids,
        "budget": manifest.budget.model_dump(),
        "store": str(store),
        "output_root": str(output_root),
        "fingerprint": digest(manifest.model_dump()),
    }


def _contained_path(root: Path, value: str, field: str) -> Path:
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ExperienceError(
            f"Campaign {field} must be a relative path without . or ..",
            code="experience_manifest_invalid",
        )
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ExperienceError(
            f"Campaign {field} escapes the manifest directory",
            code="experience_manifest_invalid",
        )
    return resolved


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)
