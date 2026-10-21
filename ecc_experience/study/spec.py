from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ecc_experience.files import digest, read_json
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError


class Pair(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pair_id: str = Field(min_length=1, max_length=128)
    baseline_case_id: str
    candidate_case_id: str
    baseline_result: str | None = None
    candidate_result: str | None = None


class StudySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    release: str
    groups: dict[str, str]
    pairs: list[Pair] = Field(min_length=1, max_length=10000)
    feedback_case_ids: list[str] = Field(default_factory=list, max_length=10000)


def load_spec(path: str | Path) -> tuple[StudySpec, Path, str]:
    source = Path(path).expanduser().absolute()
    try:
        payload = read_json(source, 4 * 1024 * 1024)
        spec = StudySpec.model_validate(payload)
    except (ExperienceError, ValidationError) as exc:
        raise invalid(str(exc)) from exc
    if (
        len({item.pair_id for item in spec.pairs}) != len(spec.pairs)
        or len(set(spec.feedback_case_ids)) != len(spec.feedback_case_ids)
        or len(spec.groups) > 30000
        or not all(0 < len(value) <= 128 for value in spec.groups.values())
    ):
        raise invalid("Study IDs must be unique and groups must be explicit bounded labels")
    return spec, source.parent, digest(payload)


def invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_study_invalid")


def resolve(root: Path, value: str) -> Path:
    return (root / Path(value).expanduser()).absolute()


def check_output(destination: Path, repository: ExperienceStore, case_ids: set[str]) -> None:
    protected = [repository.root]
    for case_id in case_ids:
        try:
            protected.append(Path(repository.read(case_id).source.workspace_root).resolve())
        except (ExperienceError, OSError):
            continue
    if (
        destination.exists()
        or destination.is_symlink()
        or any(destination.resolve().is_relative_to(root) for root in protected)
    ):
        raise invalid("Study output must be a new file outside the store and source workspaces")
