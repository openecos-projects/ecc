import importlib

import pytest

LEGACY_MODULES = (
    "artifacts",
    "command_inputs",
    "config",
    "config_view",
    "diagnose",
    "inspect",
    "invocation",
    "log_view",
    "options",
    "output",
    "param_app",
    "param_handler",
    "params",
    "pretty",
    "progress",
    "project_app",
    "records",
    "render",
    "renderers",
    "types",
    "version_info",
    "workspace_app",
    "workspace_config_view",
    "workspace_request",
    "workspace_response",
    "workspace_service",
)


def test_core_modules_live_under_core_package():
    for module_name in (
        "inputs",
        "invocation",
        "options",
        "output",
        "records",
        "types",
        "version_info",
    ):
        module = importlib.import_module(f"chipcompiler.cli.core.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.core.{module_name}"


def test_command_registration_modules_live_under_commands_package():
    for module_name in ("project", "param", "workspace"):
        module = importlib.import_module(f"chipcompiler.cli.commands.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.commands.{module_name}"


def test_project_modules_live_under_project_package():
    for module_name in ("config", "params"):
        module = importlib.import_module(f"chipcompiler.cli.project.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.project.{module_name}"


def test_param_handler_lives_under_handlers_package():
    module = importlib.import_module("chipcompiler.cli.handlers.param")
    assert module.__name__ == "chipcompiler.cli.handlers.param"


def test_inspection_modules_live_under_inspection_package():
    for module_name in ("discovery", "artifacts", "config_view", "diagnose", "log_view"):
        module = importlib.import_module(f"chipcompiler.cli.inspection.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.inspection.{module_name}"


def test_rendering_modules_live_under_rendering_package():
    for module_name in ("render", "renderers", "pretty", "progress"):
        module = importlib.import_module(f"chipcompiler.cli.rendering.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.rendering.{module_name}"


def test_workspace_modules_live_under_workspace_package():
    for module_name in ("request", "response", "service", "config_view"):
        module = importlib.import_module(f"chipcompiler.cli.workspace.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.workspace.{module_name}"


def test_legacy_root_modules_are_not_importable():
    for module_name in LEGACY_MODULES:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"chipcompiler.cli.{module_name}")
