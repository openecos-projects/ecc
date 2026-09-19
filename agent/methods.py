from typing import Any, Final

from chipcompiler.runtime.methods import RuntimeMethodSpec
from chipcompiler.runtime.requests import WorkspaceIdRequest

from .requests import (
    CandidateRerunRequest,
    CandidateResumeRequest,
    WorkspaceExtractFoundationRequest,
)

AGENT_RUNTIME_METHODS: Final[tuple[RuntimeMethodSpec[Any], ...]] = (
    RuntimeMethodSpec(
        method_name="workspace.extract_foundation",
        request_model=WorkspaceExtractFoundationRequest,
        handler_name="extract_foundation",
    ),
    RuntimeMethodSpec(
        method_name="candidate.capabilities",
        request_model=WorkspaceIdRequest,
        handler_name="candidate_capabilities",
    ),
    RuntimeMethodSpec(
        method_name="candidate.rerun",
        request_model=CandidateRerunRequest,
        handler_name="candidate_rerun",
    ),
    RuntimeMethodSpec(
        method_name="candidate.resume",
        request_model=CandidateResumeRequest,
        handler_name="candidate_resume",
    ),
)


def agent_method_names() -> tuple[str, ...]:
    return tuple(spec.method_name for spec in AGENT_RUNTIME_METHODS)
