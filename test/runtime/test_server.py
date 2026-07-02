import json

import pytest

from chipcompiler.runtime.requests import WorkspaceOpenRequest
from chipcompiler.runtime.server import RuntimeServer
from chipcompiler.runtime.workspace_api import RuntimeApiError


def _dispatch(server: RuntimeServer, payload: str) -> dict:
    return json.loads(server.dispatch(payload))


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


def test_unknown_method_keeps_request_id():
    server = RuntimeServer()

    response = _dispatch(server, '{"jsonrpc":"2.0","method":"missing","id":"req"}')

    assert response["id"] == "req"
    assert response["error"]["code"] == -32601


def test_workspace_method_dispatches_typed_request_to_runtime_api():
    class FakeApi:
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
    class FakeApi:
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
    class FakeApi:
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
    [
        "workspace.create",
        "workspace.open",
        "workspace.close",
        "workspace.home",
        "workspace.info",
        "workspace.refresh_config",
        "workspace.sync_config",
        "workspace.reset_flow",
        "flow.run",
        "flow.run_step",
    ],
)
def test_first_slice_methods_are_registered(method):
    server = RuntimeServer()

    response = _dispatch(server, f'{{"jsonrpc":"2.0","method":"{method}","id":1}}')

    assert response["error"]["code"] != -32601
