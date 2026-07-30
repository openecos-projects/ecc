import json

import pytest

from chipcompiler.runtime.methods import RUNTIME_METHODS, runtime_methods
from chipcompiler.runtime.requests import (
    CandidateRerunRequest,
    DbEnsureRequest,
    DbReleaseRequest,
    WorkspaceExportSignoffRequest,
    WorkspaceExtractFoundationRequest,
    WorkspaceInspectSignoffRequest,
    WorkspaceOpenRequest,
)
from chipcompiler.runtime.server import RuntimeServer
from chipcompiler.runtime.workspace_api import RuntimeApiError


def _dispatch(server: RuntimeServer, payload: str) -> dict:
    return json.loads(server.dispatch(payload))


class CompleteFakeApi:
    def create_workspace(self, _request):
        raise AssertionError("unexpected create_workspace call")

    def open_workspace(self, _request):
        raise AssertionError("unexpected open_workspace call")

    def close_workspace(self, _request):
        raise AssertionError("unexpected close_workspace call")

    def workspace_home(self, _request):
        raise AssertionError("unexpected workspace_home call")

    def workspace_info(self, _request):
        raise AssertionError("unexpected workspace_info call")

    def refresh_config(self, _request):
        raise AssertionError("unexpected refresh_config call")

    def sync_config(self, _request):
        raise AssertionError("unexpected sync_config call")

    def reset_flow(self, _request):
        raise AssertionError("unexpected reset_flow call")

    def export_signoff(self, _request):
        raise AssertionError("unexpected export_signoff call")

    def inspect_signoff(self, _request):
        raise AssertionError("unexpected inspect_signoff call")

    def extract_foundation(self, _request):
        raise AssertionError("unexpected extract_foundation call")

    def export_candidate_capabilities(self, _request):
        raise AssertionError("unexpected export_candidate_capabilities call")

    def bind_candidate_input(self, _request):
        raise AssertionError("unexpected bind_candidate_input call")

    def materialize_candidate(self, _request):
        raise AssertionError("unexpected materialize_candidate call")

    def candidate_rerun(self, _request):
        raise AssertionError("unexpected candidate_rerun call")

    def flow_run(self, _request):
        raise AssertionError("unexpected flow_run call")

    def flow_run_step(self, _request):
        raise AssertionError("unexpected flow_run_step call")

    def db_ensure(self, _request):
        raise AssertionError("unexpected db_ensure call")

    def db_release(self, _request):
        raise AssertionError("unexpected db_release call")

    def layout_edit_begin(self, _request):
        raise AssertionError("unexpected layout_edit_begin call")

    def layout_edit_apply(self, _request):
        raise AssertionError("unexpected layout_edit_apply call")

    def layout_edit_save(self, _request):
        raise AssertionError("unexpected layout_edit_save call")

    def layout_edit_discard(self, _request):
        raise AssertionError("unexpected layout_edit_discard call")

    def floorplan_edit_inspect(self, _request):
        raise AssertionError("unexpected floorplan_edit_inspect call")

    def floorplan_edit_run_auto(self, _request):
        raise AssertionError("unexpected floorplan_edit_run_auto call")

    def floorplan_edit_validate(self, _request):
        raise AssertionError("unexpected floorplan_edit_validate call")


def test_rpc_hello_returns_version_and_capabilities():
    server = RuntimeServer()

    response = _dispatch(
        server,
        '{"jsonrpc":"2.0","method":"rpc.hello","params":{"version":1},"id":"hello"}',
    )

    assert response["id"] == "hello"
    assert response["result"]["version"] == 1
    assert response["result"]["eccVersion"]
    assert "rpc.ping" in response["result"]["capabilities"]
    assert "rpc.shutdown" in response["result"]["capabilities"]
    assert "db.ensure" not in response["result"]["capabilities"]
    assert "db.release" not in response["result"]["capabilities"]


def test_rpc_hello_reports_persistent_db_capabilities_when_enabled():
    server = RuntimeServer(persistent_db_enabled=True)

    response = _dispatch(
        server,
        '{"jsonrpc":"2.0","method":"rpc.hello","params":{"version":1},"id":"hello"}',
    )

    assert "db.ensure" in response["result"]["capabilities"]
    assert "db.release" in response["result"]["capabilities"]


def test_rpc_hello_rejects_incompatible_version():
    server = RuntimeServer()

    response = _dispatch(
        server,
        '{"jsonrpc":"2.0","method":"rpc.hello","params":{"version":2},"id":1}',
    )

    assert response["id"] == 1
    assert response["error"]["code"] == -32001
    assert response["error"]["message"] == "unsupported_version"


def test_rpc_ping_returns_correlated_result():
    server = RuntimeServer()

    response = _dispatch(server, '{"jsonrpc":"2.0","method":"rpc.ping","id":"p"}')

    assert response == {"jsonrpc": "2.0", "result": {"ok": True}, "id": "p"}


def test_rpc_shutdown_marks_server_for_graceful_exit():
    server = RuntimeServer()

    response = _dispatch(server, '{"jsonrpc":"2.0","method":"rpc.shutdown","id":3}')

    assert response == {"jsonrpc": "2.0", "result": {"ok": True}, "id": 3}
    assert server.should_exit


def test_rpc_shutdown_releases_runtime_sessions():
    class FakeSessions:
        def __init__(self):
            self.closed = False

        def close_all(self):
            self.closed = True

    class FakeApi(CompleteFakeApi):
        sessions = FakeSessions()

    api = FakeApi()
    server = RuntimeServer(api=api)

    response = _dispatch(server, '{"jsonrpc":"2.0","method":"rpc.shutdown","id":3}')

    assert response == {"jsonrpc": "2.0", "result": {"ok": True}, "id": 3}
    assert api.sessions.closed


def test_unknown_method_keeps_request_id():
    server = RuntimeServer()

    response = _dispatch(server, '{"jsonrpc":"2.0","method":"missing","id":"req"}')

    assert response["id"] == "req"
    assert response["error"]["code"] == -32601


def test_workspace_method_dispatches_typed_request_to_runtime_api():
    class FakeApi(CompleteFakeApi):
        def open_workspace(self, request):
            assert isinstance(request, WorkspaceOpenRequest)
            return {"workspaceId": "workspace-1", "directory": request.directory}

    server = RuntimeServer(api=FakeApi())

    response = _dispatch(
        server,
        '{"jsonrpc":"2.0","method":"workspace.open","params":{"directory":"/ws"},"id":4}',
    )

    assert response == {
        "jsonrpc": "2.0",
        "result": {"workspaceId": "workspace-1", "directory": "/ws"},
        "id": 4,
    }


def test_workspace_extract_foundation_dispatches_typed_request():
    class FakeApi(CompleteFakeApi):
        def extract_foundation(self, request):
            assert isinstance(request, WorkspaceExtractFoundationRequest)
            return {"manifestRef": "foundation_data/ecc/manifest.json"}

    server = RuntimeServer(api=FakeApi())

    response = _dispatch(
        server,
        (
            '{"jsonrpc":"2.0","method":"workspace.extract_foundation",'
            '"params":{"workspaceId":"workspace-1"},"id":5}'
        ),
    )

    assert response == {
        "jsonrpc": "2.0",
        "result": {"manifestRef": "foundation_data/ecc/manifest.json"},
        "id": 5,
    }


def test_candidate_rerun_dispatches_typed_request():
    class FakeApi(CompleteFakeApi):
        def candidate_rerun(self, request):
            assert isinstance(request, CandidateRerunRequest)
            return {
                "end_step": request.end_step,
                "execution_scope": request.execution_scope,
                "target_step": request.target_step,
            }

    server = RuntimeServer(api=FakeApi())

    response = _dispatch(
        server,
        (
            '{"jsonrpc":"2.0","method":"candidate.rerun","params":'
            '{"workspaceId":"workspace-1","candidateId":"gcd-rerun-place",'
            '"targetStep":"place","patch":[{"knob_id":"place.target_density",'
            '"value":0.55}],"executionScope":"full_flow","endStep":"CTS"},"id":5}'
        ),
    )

    assert response == {
        "jsonrpc": "2.0",
        "result": {
            "end_step": "CTS",
            "execution_scope": "full_flow",
            "target_step": "place",
        },
        "id": 5,
    }


def test_workspace_export_signoff_dispatches_exact_output_path():
    class FakeApi(CompleteFakeApi):
        def export_signoff(self, request):
            assert isinstance(request, WorkspaceExportSignoffRequest)
            return {"outputPath": request.output_path}

    server = RuntimeServer(api=FakeApi())

    response = _dispatch(
        server,
        (
            '{"jsonrpc":"2.0","method":"workspace.export_signoff",'
            '"params":{"workspaceId":"workspace-1",'
            '"outputPath":"/exports/custom.tar.gz "},"id":5}'
        ),
    )

    assert response == {
        "jsonrpc": "2.0",
        "result": {"outputPath": "/exports/custom.tar.gz "},
        "id": 5,
    }


def test_workspace_inspect_signoff_dispatches_typed_request():
    class FakeApi(CompleteFakeApi):
        def inspect_signoff(self, request):
            assert isinstance(request, WorkspaceInspectSignoffRequest)
            return {"status": "ready", "groups": [], "risks": []}

    server = RuntimeServer(api=FakeApi())

    response = _dispatch(
        server,
        (
            '{"jsonrpc":"2.0","method":"workspace.inspect_signoff",'
            '"params":{"workspaceId":"workspace-1"},"id":6}'
        ),
    )

    assert response == {
        "jsonrpc": "2.0",
        "result": {"status": "ready", "groups": [], "risks": []},
        "id": 6,
    }


def test_persistent_db_methods_dispatch_typed_requests_to_runtime_api():
    seen = []

    class FakeApi(CompleteFakeApi):
        def db_ensure(self, request):
            seen.append(request)
            assert isinstance(request, DbEnsureRequest)
            return {
                "workspaceId": request.workspace_id,
                "enabled": True,
                "active": True,
                "reused": False,
                "step": request.step,
            }

        def db_release(self, request):
            seen.append(request)
            assert isinstance(request, DbReleaseRequest)
            return {"workspaceId": request.workspace_id, "released": True}

    server = RuntimeServer(api=FakeApi(), persistent_db_enabled=True)

    ensure_response = _dispatch(
        server,
        (
            '{"jsonrpc":"2.0","method":"db.ensure",'
            '"params":{"workspaceId":"workspace-1","step":"Floorplan"},"id":8}'
        ),
    )
    release_response = _dispatch(
        server,
        ('{"jsonrpc":"2.0","method":"db.release","params":{"workspaceId":"workspace-1"},"id":9}'),
    )

    assert ensure_response["result"] == {
        "workspaceId": "workspace-1",
        "enabled": True,
        "active": True,
        "reused": False,
        "step": "Floorplan",
    }
    assert release_response["result"] == {
        "workspaceId": "workspace-1",
        "released": True,
    }
    assert [type(request) for request in seen] == [DbEnsureRequest, DbReleaseRequest]


def test_persistent_db_methods_are_not_registered_by_default():
    server = RuntimeServer()

    response = _dispatch(
        server,
        ('{"jsonrpc":"2.0","method":"db.ensure","params":{"workspaceId":"workspace-1"},"id":10}'),
    )

    assert response["id"] == 10
    assert response["error"]["code"] == -32601


def test_request_validation_errors_map_to_json_rpc_invalid_params():
    server = RuntimeServer()

    response = _dispatch(
        server,
        '{"jsonrpc":"2.0","method":"workspace.home","params":{"directory":"/ws"},"id":5}',
    )

    assert response["id"] == 5
    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "invalid_request"
    assert response["error"]["data"]["message"] == "unknown field: directory"


def test_workspace_session_errors_map_to_json_rpc_runtime_error():
    class FakeApi(CompleteFakeApi):
        def workspace_home(self, _request):
            raise RuntimeApiError(
                "workspace_session_not_found",
                "workspace session not found: missing",
            )

    server = RuntimeServer(api=FakeApi())

    response = _dispatch(
        server,
        '{"jsonrpc":"2.0","method":"workspace.home","params":{"workspaceId":"missing"},"id":6}',
    )

    assert response["id"] == 6
    assert response["error"]["code"] == -32010
    assert response["error"]["message"] == "workspace_session_not_found"


def test_workspace_api_user_exceptions_map_to_command_failed():
    class FakeApi(CompleteFakeApi):
        def open_workspace(self, _request):
            raise ValueError("PDK tech LEF is missing")

    server = RuntimeServer(api=FakeApi())

    response = _dispatch(
        server,
        '{"jsonrpc":"2.0","method":"workspace.open","params":{"directory":"/ws"},"id":7}',
    )

    assert response["id"] == 7
    assert response["error"]["code"] == -32020
    assert response["error"]["message"] == "command_failed"
    assert response["error"]["data"]["message"] == "PDK tech LEF is missing"


@pytest.mark.parametrize(
    "method",
    [spec.method_name for spec in RUNTIME_METHODS],
)
def test_first_slice_methods_are_registered(method):
    server = RuntimeServer()

    response = _dispatch(server, f'{{"jsonrpc":"2.0","method":"{method}","id":1}}')

    assert response["error"]["code"] != -32601


@pytest.mark.parametrize(
    "method",
    [spec.method_name for spec in runtime_methods(persistent_db_enabled=True)],
)
def test_enabled_persistent_db_runtime_methods_are_registered(method):
    server = RuntimeServer(api=CompleteFakeApi(), persistent_db_enabled=True)

    response = _dispatch(server, f'{{"jsonrpc":"2.0","method":"{method}","id":1}}')

    assert response["error"]["code"] != -32601


def test_runtime_server_fails_when_registered_api_handler_is_missing(monkeypatch):
    from chipcompiler.runtime import methods

    missing_spec = methods.RuntimeMethodSpec(
        method_name="workspace.missing_handler",
        request_model=WorkspaceOpenRequest,
        handler_name="missing_handler",
    )
    monkeypatch.setattr(methods, "RUNTIME_METHODS", (missing_spec,))

    with pytest.raises(TypeError, match="missing_handler"):
        RuntimeServer()


def test_runtime_server_fails_when_registered_api_handler_is_not_callable(monkeypatch):
    from chipcompiler.runtime import methods

    class FakeApi:
        open_workspace = object()

    spec = methods.RuntimeMethodSpec(
        method_name="workspace.open",
        request_model=WorkspaceOpenRequest,
        handler_name="open_workspace",
    )
    monkeypatch.setattr(methods, "RUNTIME_METHODS", (spec,))

    with pytest.raises(TypeError, match="open_workspace"):
        RuntimeServer(api=FakeApi())
