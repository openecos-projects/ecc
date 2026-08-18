from dataclasses import MISSING, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class WorkspaceCreateRequest:
    directory: str
    pdk: str = ""
    pdk_root: str = ""
    pdk_json: Any = None
    parameters: dict[str, Any] | None = None
    origin_def: str = ""
    origin_verilog: str = ""
    filelist: str = ""
    rtl_list: list[str] | None = None
    sdc: str = ""
    flow_config: dict[str, Any] | None = None


@dataclass(frozen=True)
class WorkspaceOpenRequest:
    directory: str


@dataclass(frozen=True)
class WorkspaceIdRequest:
    workspace_id: str


@dataclass(frozen=True)
class WorkspaceCloseRequest:
    workspace_id: str


@dataclass(frozen=True)
class WorkspaceSyncConfigRequest:
    workspace_id: str
    config_path: str


@dataclass(frozen=True)
class WorkspaceExportSignoffRequest:
    workspace_id: str
    output_path: str


@dataclass(frozen=True)
class WorkspaceInspectSignoffRequest:
    workspace_id: str


@dataclass(frozen=True)
class WorkspaceInfoRequest:
    workspace_id: str
    step: str
    info_id: str


@dataclass(frozen=True)
class FlowRunRequest:
    workspace_id: str
    rerun: bool = False


@dataclass(frozen=True)
class FlowRunStepRequest:
    workspace_id: str
    step: str
    rerun: bool = False
    reset_dependents: bool = False
    invalidate_dependents: bool = False


@dataclass(frozen=True)
class OperationStartFlowRequest:
    workspace_id: str
    rerun: bool = False
    origin: str = "gui"
    idempotency_key: str = ""


@dataclass(frozen=True)
class OperationStartStepRequest:
    workspace_id: str
    step: str
    rerun: bool = False
    reset_dependents: bool = False
    origin: str = "gui"
    idempotency_key: str = ""


@dataclass(frozen=True)
class OperationIdRequest:
    operation_id: str


@dataclass(frozen=True)
class OperationAckStepRenderedRequest:
    operation_id: str
    event_id: str
    step_commit_id: str = ""
    workspace_revision: int | None = None


@dataclass(frozen=True)
class DbEnsureRequest:
    workspace_id: str
    step: str = ""


@dataclass(frozen=True)
class DbReleaseRequest:
    workspace_id: str


@dataclass(frozen=True)
class LayoutEditBeginRequest:
    workspace_id: str
    step: str
    expected_source_fingerprint: str = ""


@dataclass(frozen=True)
class LayoutEditApplyRequest:
    edit_session_id: str
    command_id: str
    base_revision: int
    operation: dict[str, Any]


@dataclass(frozen=True)
class LayoutEditSaveRequest:
    edit_session_id: str
    expected_revision: int


@dataclass(frozen=True)
class LayoutEditDiscardRequest:
    edit_session_id: str


@dataclass(frozen=True)
class FloorplanEditInspectRequest:
    edit_session_id: str


@dataclass(frozen=True)
class FloorplanEditRunAutoRequest:
    edit_session_id: str
    command_id: str
    base_revision: int
    request: dict[str, Any]


@dataclass(frozen=True)
class FloorplanEditValidateRequest:
    edit_session_id: str
    scope: str = "all"


class RequestValidationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


FIELD_ALIASES = {
    "flowConfig": "flow_config",
    "pdkRoot": "pdk_root",
    "pdkJson": "pdk_json",
    "originDef": "origin_def",
    "originVerilog": "origin_verilog",
    "paramJson": "parameters",
    "rtlList": "rtl_list",
    "workspaceId": "workspace_id",
    "operationId": "operation_id",
    "eventId": "event_id",
    "stepCommitId": "step_commit_id",
    "workspaceRevision": "workspace_revision",
    "idempotencyKey": "idempotency_key",
    "resetDependents": "reset_dependents",
    "invalidateDependents": "invalidate_dependents",
    "configPath": "config_path",
    "outputPath": "output_path",
    "infoId": "info_id",
    "editSessionId": "edit_session_id",
    "commandId": "command_id",
    "baseRevision": "base_revision",
    "expectedRevision": "expected_revision",
    "expectedSourceFingerprint": "expected_source_fingerprint",
    "id": "info_id",
}


def parse_request_model(model: type, params: object):
    if not isinstance(params, dict):
        raise RequestValidationError("params must be an object")

    normalized = _normalize_fields(params)
    model_fields = {field.name: field for field in fields(model)}
    for key in normalized:
        if key not in model_fields:
            raise RequestValidationError(f"unknown field: {key}")

    values: dict[str, Any] = {}
    for field in fields(model):
        required = field.default is MISSING and field.default_factory is MISSING

        if field.name in normalized:
            values[field.name] = normalized[field.name]
        elif not required:
            values[field.name] = field.default
        else:
            raise RequestValidationError(f"missing required field: {field.name}")

        if required and _is_missing(values[field.name]):
            raise RequestValidationError(f"missing required field: {field.name}")

        bool_fields = {"rerun", "reset_dependents", "invalidate_dependents"}
        if field.name in bool_fields and not isinstance(values[field.name], bool):
            raise RequestValidationError(f"{field.name} must be a boolean")

    return model(**values)


def _normalize_fields(params: dict) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in params.items():
        normalized_key = FIELD_ALIASES.get(str(key), str(key))
        if normalized_key in normalized:
            raise RequestValidationError(f"duplicate field: {normalized_key}")
        normalized[normalized_key] = value
    return normalized


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
