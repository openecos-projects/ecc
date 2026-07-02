from __future__ import annotations

from jsonrpcserver import Error

import chipcompiler
from chipcompiler.runtime.requests import RequestValidationError, parse_request
from chipcompiler.runtime.rpc_dispatch import RpcDispatcher
from chipcompiler.runtime.workspace_api import RuntimeApiError, WorkspaceRuntimeApi

PROTOCOL_VERSION = 1
BASE_CAPABILITIES = (
    "rpc.hello",
    "rpc.ping",
    "rpc.shutdown",
)
RUNTIME_METHODS = {
    "workspace.create": "create_workspace",
    "workspace.open": "open_workspace",
    "workspace.close": "close_workspace",
    "workspace.home": "workspace_home",
    "workspace.info": "workspace_info",
    "workspace.refresh_config": "refresh_config",
    "workspace.sync_config": "sync_config",
    "workspace.reset_flow": "reset_flow",
    "flow.run": "flow_run",
    "flow.run_step": "flow_run_step",
}
CAPABILITIES = (*BASE_CAPABILITIES, *RUNTIME_METHODS)

ERROR_CODES = {
    "workspace_session_not_found": -32010,
    "command_failed": -32020,
    "invalid_request": -32602,
}


class RuntimeServer:
    def __init__(self, api: WorkspaceRuntimeApi | None = None):
        self.dispatcher = RpcDispatcher()
        self.api = api or WorkspaceRuntimeApi()
        self.should_exit = False
        self._register_base_methods()
        self._register_runtime_methods()

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
            "capabilities": list(CAPABILITIES),
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
        for method_name, api_method_name in RUNTIME_METHODS.items():
            self.dispatcher.add_method(
                method_name,
                self._runtime_method_handler(method_name, api_method_name),
            )

    def _runtime_method_handler(self, method_name: str, api_method_name: str):
        def handler(**params):
            try:
                request = parse_request(method_name, params)
            except RequestValidationError as exc:
                return Error(
                    -32602,
                    "invalid_request",
                    {"message": exc.reason},
                )

            api_method = getattr(self.api, api_method_name)
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
