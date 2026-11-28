from typing import Any, Protocol


class CandidateHost(Protocol):
    """Minimal workspace host interface required by FlowAgentRuntimeApi."""

    operations: Any

    def _get_session(self, workspace_id: str, /) -> Any: ...
    def _validate_workspace_revision(self, session: Any, expected: int | None, /) -> None: ...
    def _close_transient_flow_db(self, flow: Any, /) -> None: ...
    def _with_session_mutation_lock(self, workspace_id: str, operation: Any, /) -> Any: ...


class AgentApplicationError(RuntimeError):
    def __init__(self, code: str, message: str, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


def state_value(state: Any) -> str:
    return getattr(state, "value", str(state))
