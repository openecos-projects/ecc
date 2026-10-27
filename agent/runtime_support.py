from typing import Any


class AgentApplicationError(RuntimeError):
    def __init__(self, code: str, message: str, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


def state_value(state: Any) -> str:
    return getattr(state, "value", str(state))
