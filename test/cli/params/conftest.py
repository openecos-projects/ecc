"""CLI parameter-output expectations from the production catalog."""

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter_schema import list_schemas


@pytest.fixture
def semantic_parameter_ids():
    return [schema.param for schema in list_schemas() if not schema.has_direct_target]


@pytest.fixture
def synthesis_parameter_ids():
    return [schema.param for schema in list_schemas() if schema.applies in {"synthesis", "all"}]


@pytest.fixture
def ready_project(tmp_path, monkeypatch):
    """A new ecc.toml project whose PDK root is accepted."""
    project = tmp_path / "project"
    pdk = tmp_path / "pdk"
    pdk.mkdir()
    assert cli_main.run(["init", str(project)]) == 0
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    config = project / "ecc.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace('root = ""', f'root = "{pdk}"'),
        encoding="utf-8",
    )
    return project
