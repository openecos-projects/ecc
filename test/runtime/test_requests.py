from dataclasses import is_dataclass

import pytest

from chipcompiler.runtime.methods import runtime_method_by_name
from chipcompiler.runtime.requests import (
    CandidateBindInputRequest,
    CandidateMaterializeRequest,
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
    RequestValidationError,
    WorkspaceCloseRequest,
    WorkspaceCreateRequest,
    WorkspaceExportSignoffRequest,
    WorkspaceIdRequest,
    WorkspaceInfoRequest,
    WorkspaceInspectSignoffRequest,
    WorkspaceOpenRequest,
    WorkspaceSyncConfigRequest,
    parse_request_model,
)


def _parse_runtime_request(method: str, params: object, *, persistent_db_enabled=False):
    spec = runtime_method_by_name(method, persistent_db_enabled=persistent_db_enabled)
    assert spec is not None
    return parse_request_model(spec.request_model, params)


def test_workspace_create_maps_camel_case_fields_and_preserves_pdk_json():
    pdk_json = {"name": "ics55", "lef": ["tech.lef"]}
    flow_config = {
        "start_step": "Synthesis",
        "end_step": "Harden",
        "steps": ["Synthesis", "RCX", "sta", "Harden"],
    }

    request = _parse_runtime_request(
        "workspace.create",
        {
            "directory": "/work/ws",
            "pdk": "ics55",
            "pdkRoot": "/pdk",
            "pdkJson": pdk_json,
            "originDef": "/in.def",
            "originVerilog": "/in.v",
            "paramJson": {"Design": "gcd"},
            "rtlList": ["a.v"],
            "sdc": "/constraints/top.sdc",
            "flowConfig": flow_config,
        },
    )

    assert isinstance(request, WorkspaceCreateRequest)
    assert is_dataclass(request)
    assert request.directory == "/work/ws"
    assert request.pdk_root == "/pdk"
    assert request.pdk_json == pdk_json
    assert request.origin_def == "/in.def"
    assert request.origin_verilog == "/in.v"
    assert request.parameters == {"Design": "gcd"}
    assert request.rtl_list == ["a.v"]
    assert request.sdc == "/constraints/top.sdc"
    assert request.flow_config == flow_config


@pytest.mark.parametrize(
    ("method", "params", "request_type"),
    [
        (
            "candidate.export_capabilities",
            {"workspaceId": "ws-1"},
            WorkspaceIdRequest,
        ),
        (
            "candidate.bind_input",
            {
                "workspaceId": "ws-1",
                "targetStep": "place",
                "sourceStep": "fixFanout",
                "candidateId": "candidate_0001",
            },
            CandidateBindInputRequest,
        ),
        (
            "candidate.materialize",
            {
                "workspaceId": "ws-1",
                "targetStep": "place",
                "candidateId": "candidate_0001",
                "patch": [{"knob_id": "place.target_density", "value": 0.6}],
            },
            CandidateMaterializeRequest,
        ),
    ],
)
def test_candidate_payloads_parse_to_typed_request_models(method, params, request_type):
    request = _parse_runtime_request(method, params)

    assert isinstance(request, request_type)
    assert is_dataclass(request)


@pytest.mark.parametrize(
    ("method", "params", "request_type"),
    [
        ("workspace.open", {"directory": "/work/ws"}, WorkspaceOpenRequest),
        ("workspace.close", {"workspaceId": "ws-1"}, WorkspaceCloseRequest),
        ("workspace.home", {"workspaceId": "ws-1"}, WorkspaceIdRequest),
        ("workspace.refresh_config", {"workspaceId": "ws-1"}, WorkspaceIdRequest),
        ("workspace.reset_flow", {"workspaceId": "ws-1"}, WorkspaceIdRequest),
        (
            "workspace.export_signoff",
            {"workspaceId": "ws-1", "outputPath": "/exports/custom.tar.gz"},
            WorkspaceExportSignoffRequest,
        ),
        (
            "workspace.inspect_signoff",
            {"workspaceId": "ws-1"},
            WorkspaceInspectSignoffRequest,
        ),
        (
            "workspace.sync_config",
            {"workspaceId": "ws-1", "configPath": "/work/ws/config/route.json"},
            WorkspaceSyncConfigRequest,
        ),
        (
            "workspace.info",
            {"workspaceId": "ws-1", "step": "Synthesis", "id": "layout"},
            WorkspaceInfoRequest,
        ),
        ("flow.run", {"workspaceId": "ws-1", "rerun": True}, FlowRunRequest),
        (
            "flow.run_step",
            {"workspaceId": "ws-1", "step": "Synthesis", "rerun": True},
            FlowRunStepRequest,
        ),
    ],
)
def test_first_slice_payloads_parse_to_typed_request_models(method, params, request_type):
    request = _parse_runtime_request(method, params)

    assert isinstance(request, request_type)
    assert is_dataclass(request)


@pytest.mark.parametrize(
    ("method", "params", "request_type"),
    [
        (
            "db.ensure",
            {"workspaceId": "ws-1", "step": "Floorplan"},
            DbEnsureRequest,
        ),
        ("db.ensure", {"workspaceId": "ws-1"}, DbEnsureRequest),
        ("db.release", {"workspaceId": "ws-1"}, DbReleaseRequest),
        (
            "layout.edit.begin",
            {"workspaceId": "ws-1", "step": "Floorplan"},
            LayoutEditBeginRequest,
        ),
        (
            "layout.edit.apply",
            {
                "editSessionId": "layout-edit-1",
                "commandId": "move-1",
                "baseRevision": 0,
                "operation": {"kind": "place_instance"},
            },
            LayoutEditApplyRequest,
        ),
        (
            "layout.edit.save",
            {"editSessionId": "layout-edit-1", "expectedRevision": 1},
            LayoutEditSaveRequest,
        ),
        (
            "layout.edit.discard",
            {"editSessionId": "layout-edit-1"},
            LayoutEditDiscardRequest,
        ),
        (
            "floorplan.edit.inspect",
            {"editSessionId": "layout-edit-1"},
            FloorplanEditInspectRequest,
        ),
        (
            "floorplan.edit.run_auto",
            {
                "editSessionId": "layout-edit-1",
                "commandId": "auto-1",
                "baseRevision": 1,
                "request": {"mode": "macro"},
            },
            FloorplanEditRunAutoRequest,
        ),
        (
            "floorplan.edit.validate",
            {"editSessionId": "layout-edit-1", "scope": "pdn"},
            FloorplanEditValidateRequest,
        ),
    ],
)
def test_persistent_db_payloads_parse_to_typed_request_models(method, params, request_type):
    request = _parse_runtime_request(method, params, persistent_db_enabled=True)

    assert isinstance(request, request_type)
    assert is_dataclass(request)
    if hasattr(request, "workspace_id"):
        assert request.workspace_id == "ws-1"
    else:
        assert request.edit_session_id == "layout-edit-1"


def test_db_ensure_step_is_optional():
    request = _parse_runtime_request(
        "db.ensure",
        {"workspaceId": "ws-1"},
        persistent_db_enabled=True,
    )

    assert isinstance(request, DbEnsureRequest)
    assert request.step == ""


def test_layout_edit_begin_accepts_source_fingerprint_alias():
    request = _parse_runtime_request(
        "layout.edit.begin",
        {
            "workspaceId": "ws-1",
            "step": "Floorplan",
            "expectedSourceFingerprint": "abc123",
        },
        persistent_db_enabled=True,
    )

    assert isinstance(request, LayoutEditBeginRequest)
    assert request.expected_source_fingerprint == "abc123"


def test_missing_required_field_reports_field_name():
    with pytest.raises(RequestValidationError) as exc_info:
        _parse_runtime_request("flow.run_step", {"workspaceId": "ws-1"})

    assert exc_info.value.reason == "missing required field: step"


def test_unknown_fields_are_rejected():
    with pytest.raises(RequestValidationError) as exc_info:
        _parse_runtime_request("workspace.open", {"directory": "/work/ws", "extra": True})

    assert exc_info.value.reason == "unknown field: extra"


def test_db_method_unknown_fields_are_rejected():
    with pytest.raises(RequestValidationError) as exc_info:
        _parse_runtime_request(
            "db.ensure",
            {"workspaceId": "ws-1", "extra": True},
            persistent_db_enabled=True,
        )

    assert exc_info.value.reason == "unknown field: extra"


def test_db_method_blank_workspace_id_is_rejected():
    with pytest.raises(RequestValidationError) as exc_info:
        _parse_runtime_request(
            "db.release",
            {"workspaceId": "  "},
            persistent_db_enabled=True,
        )

    assert exc_info.value.reason == "missing required field: workspace_id"


def test_params_must_be_an_object():
    with pytest.raises(RequestValidationError, match="params must be an object"):
        _parse_runtime_request("workspace.open", None)


def test_workspace_info_accepts_info_id_alias():
    request = _parse_runtime_request(
        "workspace.info",
        {"workspaceId": "ws-1", "step": "Synthesis", "infoId": "timing"},
    )

    assert isinstance(request, WorkspaceInfoRequest)
    assert request.info_id == "timing"


def test_workspace_export_signoff_preserves_exact_output_path():
    request = _parse_runtime_request(
        "workspace.export_signoff",
        {
            "workspaceId": "ws-1",
            "outputPath": "/exports/custom.tar.gz ",
        },
    )

    assert isinstance(request, WorkspaceExportSignoffRequest)
    assert request.output_path == "/exports/custom.tar.gz "


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("flow.run", {"workspaceId": "ws-1", "rerun": "false"}),
        ("flow.run_step", {"workspaceId": "ws-1", "step": "Synthesis", "rerun": "true"}),
    ],
)
def test_rerun_must_be_boolean(method, params):
    with pytest.raises(RequestValidationError) as exc_info:
        _parse_runtime_request(method, params)

    assert exc_info.value.reason == "rerun must be a boolean"


def test_unknown_runtime_method_has_no_request_model():
    assert runtime_method_by_name("workspace.signoff") is None
    assert runtime_method_by_name("db.ensure") is None
