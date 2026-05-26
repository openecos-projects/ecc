import importlib


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


def test_version_info_old_path_reexports_core_module_symbols():
    old_module = importlib.import_module("chipcompiler.cli.version_info")
    new_module = importlib.import_module("chipcompiler.cli.core.version_info")

    assert old_module.root_version_line is new_module.root_version_line
    assert old_module.version_payload is new_module.version_payload
    assert old_module.version_text is new_module.version_text


def test_command_registration_modules_live_under_commands_package():
    for module_name in ("project", "param", "workspace"):
        module = importlib.import_module(f"chipcompiler.cli.commands.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.commands.{module_name}"


def test_command_registration_old_paths_reexport_command_symbols():
    for old_name, new_name, symbol in (
        ("param_app", "param", "param_app"),
        ("workspace_app", "workspace", "workspace_app"),
    ):
        old_module = importlib.import_module(f"chipcompiler.cli.{old_name}")
        new_module = importlib.import_module(f"chipcompiler.cli.commands.{new_name}")

        assert getattr(old_module, symbol) is getattr(new_module, symbol)


def test_project_modules_live_under_project_package():
    for module_name in ("config", "params"):
        module = importlib.import_module(f"chipcompiler.cli.project.{module_name}")
        assert module.__name__ == f"chipcompiler.cli.project.{module_name}"


def test_param_handler_lives_under_handlers_package():
    module = importlib.import_module("chipcompiler.cli.handlers.param")
    assert module.__name__ == "chipcompiler.cli.handlers.param"


def test_project_and_param_old_paths_reexport_owner_modules():
    for old_name, new_name, symbol in (
        ("config", "project.config", "load_project_config"),
        ("params", "project.params", "resolve_parameters"),
        ("param_handler", "handlers.param", "param_show"),
    ):
        old_module = importlib.import_module(f"chipcompiler.cli.{old_name}")
        new_module = importlib.import_module(f"chipcompiler.cli.{new_name}")

        assert getattr(old_module, symbol) is getattr(new_module, symbol)
