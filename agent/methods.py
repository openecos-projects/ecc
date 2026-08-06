from typing import Any, Final

from chipcompiler.runtime.methods import RuntimeMethodSpec
from chipcompiler.runtime.requests import WorkspaceIdRequest

from .requests import (
    CandidateBindInputRequest,
    CandidateMaterializeRequest,
    CandidateRerunRequest,
    WorkspaceExtractFoundationRequest,
)

AGENT_RUNTIME_METHODS: Final[tuple[RuntimeMethodSpec[Any], ...]] = (
    RuntimeMethodSpec(
        method_name="workspace.extract_foundation",
        request_model=WorkspaceExtractFoundationRequest,
        handler_name="extract_foundation",
    ),
    RuntimeMethodSpec(
        method_name="candidate.export_capabilities",
        request_model=WorkspaceIdRequest,
        handler_name="export_candidate_capabilities",
    ),
    RuntimeMethodSpec(
        method_name="candidate.bind_input",
        request_model=CandidateBindInputRequest,
        handler_name="bind_candidate_input",
    ),
    RuntimeMethodSpec(
        method_name="candidate.materialize",
        request_model=CandidateMaterializeRequest,
        handler_name="materialize_candidate",
    ),
    RuntimeMethodSpec(
        method_name="candidate.rerun",
        request_model=CandidateRerunRequest,
        handler_name="candidate_rerun",
    ),
)


def agent_method_names() -> tuple[str, ...]:
    return tuple(spec.method_name for spec in AGENT_RUNTIME_METHODS)
