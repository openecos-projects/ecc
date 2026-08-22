from jsonrpcserver import Error

from chipcompiler.runtime.requests import RequestValidationError
from chipcompiler.runtime.server import ERROR_CODES, RuntimeServer
from chipcompiler.runtime.workspace_api import RuntimeApiError, WorkspaceRuntimeApi

from .methods import AGENT_RUNTIME_METHODS, agent_method_names
from .requests import parse_agent_request_model
from .workspace_api import FlowAgentRuntimeApi


class AgentRuntimeServer(RuntimeServer):
    def __init__(
        self,
        api: WorkspaceRuntimeApi | None = None,
        *,
        persistent_db_enabled: bool = False,
    ):
        super().__init__(api=api, persistent_db_enabled=persistent_db_enabled)
        self.agent_api = FlowAgentRuntimeApi(self.api)
        self._register_agent_methods()

    @property
    def capabilities(self) -> tuple[str, ...]:
        return (*super().capabilities, *agent_method_names())

    def _register_agent_methods(self) -> None:
        for spec in AGENT_RUNTIME_METHODS:
            handler = getattr(self.agent_api, spec.handler_name)
            self.dispatcher.add_method(spec.method_name, self._agent_method_handler(spec, handler))

    @staticmethod
    def _agent_method_handler(spec, handler):
        def dispatch(**params):
            try:
                request = parse_agent_request_model(spec.request_model, params)
                return handler(request)
            except RequestValidationError as exc:
                return Error(
                    ERROR_CODES["invalid_request"],
                    "invalid_request",
                    {"message": exc.reason},
                )
            except RuntimeApiError as exc:
                return Error(
                    ERROR_CODES.get(exc.code, -32000),
                    exc.code,
                    {"message": exc.message, **exc.data},
                )
            except Exception as exc:
                return Error(
                    ERROR_CODES["command_failed"],
                    "command_failed",
                    {"message": str(exc)},
                )

        return dispatch
