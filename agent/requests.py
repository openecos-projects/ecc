from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkspaceIdRequest:
    workspace_id: str


@dataclass(frozen=True)
class WorkspaceExtractFoundationRequest:
    workspace_id: str


@dataclass(frozen=True)
class CandidateRerunRequest:
    workspace_id: str
    target_step: str
    end_step: str
    candidate_id: str
    patch: list[dict[str, Any]]
    execution_scope: str
    idempotency_key: str
    context_sha256: str
    parameter_card_sha256: str
    seed: int
    expected_workspace_revision: int | None = None
    parent_candidate_root_ref: str | None = None
    floorplan_mode: str | None = None


@dataclass(frozen=True)
class CandidateResumeRequest:
    workspace_id: str
    candidate_id: str
    idempotency_key: str
    context_sha256: str
    parameter_card_sha256: str
    seed: int
    expected_workspace_revision: int | None = None
