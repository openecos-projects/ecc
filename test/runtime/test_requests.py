from dataclasses import is_dataclass

import pytest

from chipcompiler.runtime.methods import runtime_method_by_name
from chipcompiler.runtime.requests import (
    FlowRunRequest,
    FlowRunStepRequest,
    RequestValidationError,
    WorkspaceCloseRequest,
    WorkspaceCreateRequest,
    WorkspaceIdRequest,
    WorkspaceInfoRequest,
    WorkspaceOpenRequest,
    WorkspaceSyncConfigRequest,
    parse_request_model,
)


def _parse_runtime_request(method: str, params: object):
    spec = runtime_method_by_name(method)
    assert spec is not None
    return parse_request_model(spec.request_model, params)


def test_workspace_create_maps_camel_case_fields_and_preserves_pdk_json():
    pdk_json = {"name": "ics55", "lef": ["tech.lef"]}

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


@pytest.mark.parametrize(
    ("method", "params", "request_type"),
    [
        ("workspace.open", {"directory": "/work/ws"}, WorkspaceOpenRequest),
        ("workspace.close", {"workspaceId": "ws-1"}, WorkspaceCloseRequest),
        ("workspace.home", {"workspaceId": "ws-1"}, WorkspaceIdRequest),
        ("workspace.refresh_config", {"workspaceId": "ws-1"}, WorkspaceIdRequest),
        ("workspace.reset_flow", {"workspaceId": "ws-1"}, WorkspaceIdRequest),
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


def test_missing_required_field_reports_field_name():
    with pytest.raises(RequestValidationError) as exc_info:
        _parse_runtime_request("flow.run_step", {"workspaceId": "ws-1"})

    assert exc_info.value.reason == "missing required field: step"


def test_unknown_fields_are_rejected():
    with pytest.raises(RequestValidationError) as exc_info:
        _parse_runtime_request("workspace.open", {"directory": "/work/ws", "extra": True})

    assert exc_info.value.reason == "unknown field: extra"


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


def test_unknown_runtime_method_has_no_request_model():
    assert runtime_method_by_name("workspace.signoff") is None
