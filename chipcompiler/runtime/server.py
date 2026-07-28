from __future__ import annotations

from jsonrpcserver import Error

import chipcompiler
from chipcompiler.runtime import methods
from chipcompiler.runtime.requests import RequestValidationError, parse_request_model
from chipcompiler.runtime.rpc_dispatch import RpcDispatcher
from chipcompiler.runtime.workspace_api import RuntimeApiError, WorkspaceRuntimeApi

PROTOCOL_VERSION = 1
BASE_CAPABILITIES = (
    "rpc.hello",
    "rpc.ping",
    "rpc.shutdown",
)

ERROR_CODES = {
    "workspace_session_not_found": -32010,
    "command_failed": -32020,
    "invalid_request": -32602,
}


class RuntimeServer:
    def __init__(
        self,
        api: WorkspaceRuntimeApi | None = None,
        *,
        persistent_db_enabled: bool = False,
    ):
        self.persistent_db_enabled = persistent_db_enabled
        self.dispatcher = RpcDispatcher()
        self.api = api or WorkspaceRuntimeApi(persistent_db_enabled=persistent_db_enabled)
        self.should_exit = False
        self._register_base_methods()
        self._register_runtime_methods()

    @property
    def capabilities(self) -> tuple[str, ...]:
        return (
            *BASE_CAPABILITIES,
            *methods.runtime_method_names(
                persistent_db_enabled=self.persistent_db_enabled,
            ),
        )

    def dispatch(self, payload: bytes | str) -> str:
        return self.dispatcher.dispatch(payload)

    def _register_base_methods(self) -> None:
        self.dispatcher.add_method("rpc.hello", self._hello)
        self.dispatcher.add_method("rpc.ping", self._ping)
        self.dispatcher.add_method("rpc.shutdown", self._shutdown)

    def _hello(self, version: int):
        if version != PROTOCOL_VERSION:
            return Error(
                -32001,
                "unsupported_version",
                {"supportedVersion": PROTOCOL_VERSION, "requestedVersion": version},
            )
        return {
            "version": PROTOCOL_VERSION,
            "eccVersion": getattr(chipcompiler, "__version__", "unknown"),
            "capabilities": list(self.capabilities),
        }

    def _ping(self) -> dict:
        return {"ok": True}

    def _shutdown(self) -> dict:
        self.should_exit = True
        sessions = getattr(self.api, "sessions", None)
        if sessions is not None and hasattr(sessions, "close_all"):
            sessions.close_all()
        return {"ok": True}

    def _register_runtime_methods(self) -> None:
        for spec in methods.runtime_methods(
            persistent_db_enabled=self.persistent_db_enabled,
        ):
            api_method = getattr(self.api, spec.handler_name, None)
            if not callable(api_method):
                raise TypeError(
                    f"runtime method {spec.method_name} handler {spec.handler_name} is not callable"
                )
            self.dispatcher.add_method(
                spec.method_name,
                self._runtime_method_handler(spec, api_method),
            )

    def _runtime_method_handler(self, spec, api_method):
        def handler(**params):
            try:
                request = parse_request_model(spec.request_model, params)
            except RequestValidationError as exc:
                return Error(
                    -32602,
                    "invalid_request",
                    {"message": exc.reason},
                )

            try:
                return api_method(request)
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

        return handler
