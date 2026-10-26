from dataclasses import dataclass
from typing import Literal, TypeAlias

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
    closure: Literal["complete", "partial", "unknown"] = "unknown"
    closure_sha256: str | None = None
    resolved_files: int = Field(default=0, ge=0)


class DesignTag(Model):
    name: str = Field(min_length=1, max_length=128)
    source: Literal["user", "spec", "synthesis", "ai"]
    confidence: Literal["high", "medium", "low"]


class DesignIdentity(Model):
    fingerprint: str | None = None
    top_module: str | None = None
    tags: list[DesignTag] = Field(default_factory=list)
    memory_implementation: Literal["register", "mapped_macro", "mixed", "unknown"] = "unknown"
    memory_bits: int | None = Field(default=None, ge=0)
    macro_count: int | None = Field(default=None, ge=0)
    closure: Literal["complete", "partial", "unknown"] = "unknown"


class ConstraintIdentity(Model):
    fingerprint: str | None = None
    sdc_sha256: str | None = None
    clock_periods: list[float] = Field(default_factory=list)
    corners: list[str] = Field(default_factory=list)
    timing_constraints_status: Literal["available", "partial", "unknown"] = "unknown"


class ProcessFile(Model):
    role: str
    sha256: str
    bytes: int = Field(ge=0)


class ProcessIdentity(Model):
    fingerprint: str | None = None
    scope: str = "selected_tech_lef_liberty_mapping_not_complete_pdk_closure"
    status: Literal["available", "partial", "unknown"] = "unknown"
    files: list[ProcessFile] = Field(default_factory=list)
    reason: str | None = None


class ToolchainIdentity(Model):
    runtime_fingerprint: str | None = None
    status: Literal["available", "partial", "unknown"] = "unknown"
    sources: dict[str, JsonValue] = Field(default_factory=dict)
    tools: dict[str, JsonValue] = Field(default_factory=dict)
    native_packages: dict[str, JsonValue] = Field(default_factory=dict)


class ParameterApplication(Model):
    knob_id: str
    value: JsonValue
    actual_value: JsonValue | None = None
    unit: str | None = None
    status: Literal["effective", "inactive", "unknown"]
    candidate_id: str | None = None
    stage: str | None = None


class ParameterEvidence(Model):
    level: Literal["applied", "configured", "unknown"]
    receipt_sha256: str | None = None
    receipt_status: Literal["missing", "valid", "invalid", "not_applicable"] = "missing"
    applied_parameters: list[ParameterApplication] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


ParameterEvidenceValue: TypeAlias = Literal["configured", "unknown"] | ParameterEvidence


class FailureIdentity(Model):
    primary_category: Literal[
        "none",
        "design_constraint",
        "resource",
        "environment",
        "tool_failure",
        "evidence_invalid",
        "cancelled",
        "unknown",
    ] = "unknown"
    contributing_factors: list[str] = Field(default_factory=list)
    classifier_version: str = "failure-taxonomy/1"
    evidence: list[str] = Field(default_factory=list)


class ExperienceCase(Model):
    schema_version: Literal[1, 2] = 1
    case_id: str
    collector_version: str
    collected_at: str
    source: SourceObservation
    input_content_fingerprint: str | None
    design_fingerprint: str | None = None
    process_fingerprint: str | None = None
    design: DesignIdentity | None = None
    constraints: ConstraintIdentity | None = None
    process: ProcessIdentity | None = None
    toolchain: ToolchainIdentity | None = None
    inputs: list[InputDigest]
    facts: dict[str, JsonValue]
    evidence: list[Evidence]
    limitations: list[str]
    parameter_evidence: ParameterEvidenceValue
    failure: FailureIdentity | None = None
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
    design: dict | None = None
    constraints: dict | None = None
    parameter_evidence: dict | None = None


@dataclass(frozen=True)
class CaseContents:
    case: ExperienceCase
    copies: dict[str, bytes]


def parameter_evidence_level(case: ExperienceCase) -> Literal["applied", "configured", "unknown"]:
    value = case.parameter_evidence
    return value if isinstance(value, str) else value.level
