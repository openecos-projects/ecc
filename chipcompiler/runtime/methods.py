from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Generic, TypeVar

from chipcompiler.runtime.requests import (
    CandidateBindInputRequest,
    CandidateMaterializeRequest,
    CandidateRerunRequest,
    DbEnsureRequest,
    DbReleaseRequest,
    FloorplanEditInspectRequest,
    FloorplanEditRunAutoRequest,
    FloorplanEditValidateRequest,
    FlowRunRequest,
    FlowRunStepRequest,
    LayoutEditApplyRequest,
    LayoutEditBeginRequest,
    LayoutEditDiscardRequest,
    LayoutEditSaveRequest,
    WorkspaceCloseRequest,
    WorkspaceCreateRequest,
    WorkspaceExportSignoffRequest,
    WorkspaceExtractFoundationRequest,
    WorkspaceIdRequest,
    WorkspaceInfoRequest,
    WorkspaceInspectSignoffRequest,
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
        method_name="workspace.export_signoff",
        request_model=WorkspaceExportSignoffRequest,
        handler_name="export_signoff",
    ),
    RuntimeMethodSpec(
        method_name="workspace.inspect_signoff",
        request_model=WorkspaceInspectSignoffRequest,
        handler_name="inspect_signoff",
    ),
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


PERSISTENT_DB_METHODS: Final[tuple[RuntimeMethodSpec[Any], ...]] = (
    RuntimeMethodSpec(
        method_name="db.ensure",
        request_model=DbEnsureRequest,
        handler_name="db_ensure",
    ),
    RuntimeMethodSpec(
        method_name="db.release",
        request_model=DbReleaseRequest,
        handler_name="db_release",
    ),
    RuntimeMethodSpec(
        method_name="layout.edit.begin",
        request_model=LayoutEditBeginRequest,
        handler_name="layout_edit_begin",
    ),
    RuntimeMethodSpec(
        method_name="layout.edit.apply",
        request_model=LayoutEditApplyRequest,
        handler_name="layout_edit_apply",
    ),
    RuntimeMethodSpec(
        method_name="layout.edit.save",
        request_model=LayoutEditSaveRequest,
        handler_name="layout_edit_save",
    ),
    RuntimeMethodSpec(
        method_name="layout.edit.discard",
        request_model=LayoutEditDiscardRequest,
        handler_name="layout_edit_discard",
    ),
    RuntimeMethodSpec(
        method_name="floorplan.edit.inspect",
        request_model=FloorplanEditInspectRequest,
        handler_name="floorplan_edit_inspect",
    ),
    RuntimeMethodSpec(
        method_name="floorplan.edit.run_auto",
        request_model=FloorplanEditRunAutoRequest,
        handler_name="floorplan_edit_run_auto",
    ),
    RuntimeMethodSpec(
        method_name="floorplan.edit.validate",
        request_model=FloorplanEditValidateRequest,
        handler_name="floorplan_edit_validate",
    ),
)


def runtime_methods(*, persistent_db_enabled: bool = False) -> tuple[RuntimeMethodSpec[Any], ...]:
    if persistent_db_enabled:
        return (*RUNTIME_METHODS, *PERSISTENT_DB_METHODS)
    return RUNTIME_METHODS


def runtime_method_names(*, persistent_db_enabled: bool = False) -> tuple[str, ...]:
    return tuple(
        spec.method_name for spec in runtime_methods(persistent_db_enabled=persistent_db_enabled)
    )


def persistent_db_method_names() -> tuple[str, ...]:
    return tuple(spec.method_name for spec in PERSISTENT_DB_METHODS)


def runtime_method_by_name(
    method_name: str,
    *,
    persistent_db_enabled: bool = False,
) -> RuntimeMethodSpec[Any] | None:
    for spec in runtime_methods(persistent_db_enabled=persistent_db_enabled):
        if spec.method_name == method_name:
            return spec
    return None
