import importlib
from pathlib import Path

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
    for module_name in ("project", "doctor", "param", "signoff", "report", "rpc"):
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
    for module_name in (
        "discovery",
        "config_view",
        "log_view",
    ):
        module = importlib.import_module(f"chipcompiler.cli.inspection.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.inspection.{module_name}"


def test_rendering_modules_live_under_rendering_package():
    for module_name in ("render", "renderers", "pretty", "progress"):
        module = importlib.import_module(f"chipcompiler.cli.rendering.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.rendering.{module_name}"


def test_legacy_root_modules_are_not_importable():
    for module_name in LEGACY_MODULES:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"chipcompiler.cli.{module_name}")


def test_workspace_config_view_module_is_not_importable():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("chipcompiler.cli.workspace.config_view")


def test_inspection_step_config_module_is_not_importable():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("chipcompiler.cli.inspection.step_config")


def test_removed_inspection_command_modules_are_not_importable():
    for module_name in ("artifacts", "diagnose"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"chipcompiler.cli.inspection.{module_name}")


def test_project_command_module_does_not_expose_removed_command_wrappers():
    module = importlib.import_module("chipcompiler.cli.commands.project")

    for name in ("metrics_cmd", "artifacts_cmd", "diagnose_cmd"):
        assert not hasattr(module, name)


def test_removed_command_input_dataclasses_are_not_exposed():
    module = importlib.import_module("chipcompiler.cli.core.inputs")

    for name in ("StepInspectInput", "DiagnoseInput"):
        assert not hasattr(module, name)


def test_pretty_renderers_do_not_expose_removed_commands():
    module = importlib.import_module("chipcompiler.cli.rendering.pretty")

    for name in ("render_metrics", "render_artifacts", "render_diagnose"):
        assert not hasattr(module, name)
    for command in ("metrics", "artifacts", "diagnose"):
        assert module.get_pretty_renderer(command) is None


def test_production_code_does_not_import_inspection_step_config():
    package_root = Path(__file__).parents[2] / "chipcompiler"

    for source_path in package_root.rglob("*.py"):
        source = source_path.read_text()
        assert "chipcompiler.cli.inspection.step_config" not in source, source_path


def test_cli_does_not_import_workspace_config_metadata_maps():
    package_root = Path(__file__).parents[2] / "chipcompiler" / "cli"
    forbidden_names = (
        "WORKSPACE_CONFIG_FILENAMES",
        "STEP_CONFIG_KEYS",
        "WORKSPACE_STEP_BY_LOWER_NAME",
        "WORKSPACE_STEP_ALIASES",
        "_WORKSPACE_CONFIG_FILENAMES",
        "_STEP_CONFIG_KEYS",
    )

    for source_path in package_root.rglob("*.py"):
        source = source_path.read_text()
        for name in forbidden_names:
            assert name not in source, source_path


def test_production_code_does_not_import_removed_inspection_modules():
    package_root = Path(__file__).parents[2] / "chipcompiler"
    forbidden_imports = (
        "chipcompiler.cli.inspection.artifacts",
        "chipcompiler.cli.inspection.diagnose",
    )

    for source_path in package_root.rglob("*.py"):
        source = source_path.read_text()
        for name in forbidden_imports:
            assert name not in source, source_path
