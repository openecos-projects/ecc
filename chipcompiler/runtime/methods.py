from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Generic, TypeVar

from chipcompiler.runtime.requests import (
    FlowRunRequest,
    FlowRunStepRequest,
    WorkspaceCloseRequest,
    WorkspaceCreateRequest,
    WorkspaceIdRequest,
    WorkspaceInfoRequest,
    WorkspaceOpenRequest,
    WorkspaceSyncConfigRequest,
)

RequestT = TypeVar("RequestT")


@dataclass(frozen=True)
class RuntimeMethodSpec(Generic[RequestT]):
    method_name: str
    request_model: type[RequestT]
    handler_name: str


RUNTIME_METHODS: Final[tuple[RuntimeMethodSpec[Any], ...]] = (
    RuntimeMethodSpec(
        method_name="workspace.create",
        request_model=WorkspaceCreateRequest,
        handler_name="create_workspace",
    ),
    RuntimeMethodSpec(
        method_name="workspace.open",
        request_model=WorkspaceOpenRequest,
        handler_name="open_workspace",
    ),
    RuntimeMethodSpec(
        method_name="workspace.close",
        request_model=WorkspaceCloseRequest,
        handler_name="close_workspace",
    ),
    RuntimeMethodSpec(
        method_name="workspace.home",
        request_model=WorkspaceIdRequest,
        handler_name="workspace_home",
    ),
    RuntimeMethodSpec(
        method_name="workspace.info",
        request_model=WorkspaceInfoRequest,
        handler_name="workspace_info",
    ),
    RuntimeMethodSpec(
        method_name="workspace.refresh_config",
        request_model=WorkspaceIdRequest,
        handler_name="refresh_config",
    ),
    RuntimeMethodSpec(
        method_name="workspace.sync_config",
        request_model=WorkspaceSyncConfigRequest,
        handler_name="sync_config",
    ),
    RuntimeMethodSpec(
        method_name="workspace.reset_flow",
        request_model=WorkspaceIdRequest,
        handler_name="reset_flow",
    ),
    RuntimeMethodSpec(
        method_name="flow.run",
        request_model=FlowRunRequest,
        handler_name="flow_run",
    ),
    RuntimeMethodSpec(
        method_name="flow.run_step",
        request_model=FlowRunStepRequest,
        handler_name="flow_run_step",
    ),
)


def runtime_method_names() -> tuple[str, ...]:
    return tuple(spec.method_name for spec in RUNTIME_METHODS)


def runtime_method_by_name(method_name: str) -> RuntimeMethodSpec[Any] | None:
    for spec in RUNTIME_METHODS:
        if spec.method_name == method_name:
            return spec
    return None
