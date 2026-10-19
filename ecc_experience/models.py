from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ExperienceError(ValueError):
    def __init__(self, message: str, *, code: str = "experience_invalid"):
        super().__init__(message)
        self.code = code


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SourceObservation(Model):
    workspace_root: str
    workspace_id: str | None
    workspace_revision: int | None = Field(default=None, ge=1)
    snapshot_schema: int | None
    snapshot_digest: str | None
    cause: str | None
    observation_type: Literal["committed_import", "legacy_import"]
    attempt_id: str | None = None


class Evidence(Model):
    reference: str
    status: Literal["available", "missing", "stale", "unavailable", "invalid"]
    sha256: str | None = None
    bytes: int | None = Field(default=None, ge=0)
    stored_path: str | None = None
    reason: str | None = None


class InputDigest(Model):
    input_id: str
    role: str
    status: Literal["available", "unavailable"]
    sha256: str | None


class ExperienceCase(Model):
    schema_version: Literal[1] = 1
    case_id: str
    collector_version: str
    collected_at: str
    source: SourceObservation
    input_content_fingerprint: str | None
    design_fingerprint: str | None = None
    process_fingerprint: str | None = None
    inputs: list[InputDigest]
    facts: dict[str, JsonValue]
    evidence: list[Evidence]
    limitations: list[str]
    parameter_evidence: Literal["configured", "unknown"]
    validation_scope: Literal["committed_observation", "legacy_import"]


class Finding(Model):
    status: Literal["pass", "fail", "unknown"]
    check: str
    reference: str | None = None
    reason: str | None = None


class Verification(Model):
    case_id: str
    status: Literal["pass", "fail", "unknown"]
    integrity: Literal["pass", "fail"]
    findings: list[Finding]


@dataclass(frozen=True)
class WorkspaceObservation:
    source: SourceObservation
    facts: dict
    inputs: list[InputDigest]
    evidence: list[Evidence]
    copies: dict[str, bytes]
    limitations: list[str]


@dataclass(frozen=True)
class CaseContents:
    case: ExperienceCase
    copies: dict[str, bytes]
