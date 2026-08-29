from dataclasses import dataclass
from typing import Any

from chipcompiler.runtime.requests import RequestValidationError, parse_request_model


@dataclass(frozen=True)
class WorkspaceExtractFoundationRequest:
    workspace_id: str


@dataclass(frozen=True)
class CandidateBindInputRequest:
    workspace_id: str
    target_step: str
    source_step: str
    candidate_id: str


@dataclass(frozen=True)
class CandidateMaterializeRequest:
    workspace_id: str
    target_step: str
    candidate_id: str
    patch: list[dict[str, Any]]


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
    seed: int
    parent_candidate_root_ref: str | None = None


_FIELD_ALIASES = {
    "workspaceId": "workspace_id",
    "targetStep": "target_step",
    "endStep": "end_step",
    "sourceStep": "source_step",
    "candidateId": "candidate_id",
    "executionScope": "execution_scope",
    "idempotencyKey": "idempotency_key",
    "contextSha256": "context_sha256",
    "parentCandidateRootRef": "parent_candidate_root_ref",
}


def parse_agent_request_model(model: type, params: object):
    if not isinstance(params, dict):
        raise RequestValidationError("params must be an object")
    normalized = {}
    for key, value in params.items():
        name = _FIELD_ALIASES.get(str(key), str(key))
        if name in normalized:
            raise RequestValidationError(f"duplicate field: {name}")
        normalized[name] = value
    return parse_request_model(model, normalized)
