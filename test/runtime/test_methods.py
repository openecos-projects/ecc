from dataclasses import is_dataclass

import chipcompiler.runtime.requests as requests
from chipcompiler.runtime.requests import WorkspaceOpenRequest
from chipcompiler.runtime.server import BASE_CAPABILITIES, CAPABILITIES


def test_runtime_method_registry_contains_current_methods_once():
    from chipcompiler.runtime.methods import RUNTIME_METHODS, runtime_method_names

    expected_methods = (
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
    )

    assert runtime_method_names() == expected_methods
    assert len(runtime_method_names()) == len(set(runtime_method_names()))
    assert len(RUNTIME_METHODS) == len(expected_methods)


def test_runtime_method_registry_entries_are_typed():
    from chipcompiler.runtime.methods import RUNTIME_METHODS

    for spec in RUNTIME_METHODS:
        assert spec.method_name
        assert isinstance(spec.request_model, type)
        assert is_dataclass(spec.request_model)
        assert spec.handler_name


def test_runtime_method_lookup_returns_spec():
    from chipcompiler.runtime.methods import runtime_method_by_name

    spec = runtime_method_by_name("workspace.open")

    assert spec is not None
    assert spec.request_model is WorkspaceOpenRequest
    assert spec.handler_name == "open_workspace"
    assert runtime_method_by_name("workspace.signoff") is None


def test_server_capabilities_are_generated_from_runtime_registry():
    from chipcompiler.runtime.methods import runtime_method_names

    assert (*BASE_CAPABILITIES, *runtime_method_names()) == CAPABILITIES


def test_requests_module_does_not_own_runtime_method_table():
    assert not hasattr(requests, "REQUEST_MODELS")


def test_server_module_does_not_own_runtime_method_table():
    import chipcompiler.runtime.server as server

    assert not hasattr(server, "RUNTIME_METHODS")
