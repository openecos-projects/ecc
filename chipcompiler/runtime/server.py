from collections.abc import Callable

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
    "runtime.v2",
    "operation.events",
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
        self._notification_sink: Callable[[str, dict], None] | None = None
        set_event_publisher = getattr(self.api, "set_event_publisher", None)
        if callable(set_event_publisher):
            set_event_publisher(self._publish_runtime_event)
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

    def set_notification_sink(self, sink: Callable[[str, dict], None] | None) -> None:
        self._notification_sink = sink

    def _publish_runtime_event(self, event: dict) -> None:
        sink = self._notification_sink
        if sink is not None:
            sink("runtime.event", _project_runtime_event(event))

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
            "protocolVersion": PROTOCOL_VERSION,
            "eccVersion": getattr(chipcompiler, "__version__", "unknown"),
            "capabilities": list(self.capabilities),
        }

    def _ping(self) -> dict:
        return {"ok": True}

    def _shutdown(self) -> dict:
        operations = getattr(self.api, "operations", None)
        shutdown_barrier = getattr(operations, "shutdown_barrier", None)
        barrier = shutdown_barrier() if callable(shutdown_barrier) else None
        if barrier is not None:
            return {"ok": False, "deferred": True, "shutdownBarrier": barrier}
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
                if spec.method_name not in methods.OPTIONAL_RUNTIME_METHOD_NAMES:
                    raise TypeError(f"runtime API handler is not callable: {spec.handler_name}")
                self.dispatcher.add_method(
                    spec.method_name,
                    self._missing_optional_method_handler(spec),
                )
                continue
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
                stable_code = getattr(exc, "code", None)
                if isinstance(stable_code, str):
                    details = getattr(exc, "details", None)
                    if not isinstance(details, dict):
                        details = getattr(exc, "data", None)
                    return Error(
                        ERROR_CODES.get(stable_code, -32000),
                        stable_code,
                        {"message": str(exc), **(details if isinstance(details, dict) else {})},
                    )
                return Error(
                    ERROR_CODES["command_failed"],
                    "command_failed",
                    {"message": str(exc)},
                )

        return handler

    @staticmethod
    def _missing_optional_method_handler(spec):
        def handler(**_params):
            return Error(
                -32602,
                "invalid_request",
                {"message": f"runtime API does not support {spec.method_name}"},
            )

        return handler


def _project_runtime_event(event: dict) -> dict:
    source_type = str(event.get("type", ""))
    payload = {**event.get("payload", {}), "sourceType": source_type}
    if source_type == "step.completed":
        event_type = "workspace.committed"
    elif source_type in {
        "step.started",
        "step.log",
        "subflow.stage",
        "operation.rerun_prepared",
    }:
        event_type = "execution.progress"
    else:
        event_type = "operation.changed"
        state = {
            "operation.queued": "queued",
            "operation.started": "running",
            "operation.cancel_requested": "cancelling",
            "operation.completed": "succeeded",
            "operation.failed": "failed",
            "operation.cancelled": "cancelled",
            "operation.interrupted": "interrupted",
        }.get(source_type)
        if state:
            payload["state"] = state
    return {
        **event,
        "type": event_type,
        "payload": payload,
        **(
            {"workspaceRevision": payload["workspaceRevision"]}
            if "workspaceRevision" in payload
            else {}
        ),
    }
