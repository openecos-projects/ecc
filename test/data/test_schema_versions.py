"""Only current workspace schemas load; older files fail with a recreate error."""

import json

import pytest

from chipcompiler.data import Workspace, load_workspace
from chipcompiler.data.flow.document import load_flow_document
from chipcompiler.data.schema_versions import (
    PARAMS_TOML,
    UnsupportedSchemaVersionError,
    ensure_supported_schema_version,
)
from chipcompiler.data.workspace.config import load_workspace_config


def test_current_params_and_flow_documents_load(tmp_path):
    from chipcompiler.data import OriginDesign
    from chipcompiler.data.workspace.config import save_workspace_config
    from chipcompiler.engine.flow import EngineFlow

    workspace_dir = tmp_path / "workspace"
    assert save_workspace_config(workspace_dir, {"design": "gcd", "pdk": "ics55"})
    workspace = Workspace(directory=workspace_dir, design=OriginDesign(name="gcd"))
    workspace.flow.path = workspace_dir / "home" / "flow.json"
    flow = EngineFlow(workspace)
    flow.add_step("placement", "dreamplace", "Unstart")

    assert load_workspace_config(workspace_dir)["design"] == "gcd"
    document = load_flow_document(workspace.flow.path)
    assert document.get("schema_version") == 3
    assert document.get("steps", [])[0]["directory"] == "01_placement_dreamplace"


@pytest.mark.parametrize("version", [0, 1])
def test_old_params_and_flow_versions_fail_with_recreate_error(tmp_path, version):
    home = tmp_path / "home"
    home.mkdir()
    (home / "params.toml").write_text(f"schema_version = {version}\n[params]\n")
    (home / "flow.json").write_text(json.dumps({"schema_version": version, "steps": []}))

    with pytest.raises(UnsupportedSchemaVersionError, match="create a new workspace"):
        load_workspace_config(tmp_path)
    with pytest.raises(UnsupportedSchemaVersionError, match="create a new workspace"):
        load_flow_document(home / "flow.json")


def test_newer_params_and_flow_versions_fail_closed(tmp_path):
    with pytest.raises(UnsupportedSchemaVersionError, match="upgrade ECC"):
        ensure_supported_schema_version(
            PARAMS_TOML, tmp_path / "params.toml", {"schema_version": 99}
        )
    (tmp_path / "flow.json").write_text(json.dumps({"schema_version": 99, "steps": []}))

    with pytest.raises(UnsupportedSchemaVersionError, match="upgrade ECC"):
        load_flow_document(tmp_path / "flow.json")


def test_missing_step_metadata_fails_instead_of_being_repaired(tmp_path):
    path = tmp_path / "flow.json"
    path.write_text(
        json.dumps({"schema_version": 3, "steps": [{"name": "placement", "tool": "ecc"}]})
    )

    with pytest.raises(ValueError, match="missing state, directory, category"):
        load_flow_document(path)


def test_a_step_with_an_unknown_state_fails_to_load(tmp_path):
    from test.flow_fixture import current_flow_document

    path = tmp_path / "flow.json"
    path.write_text(
        json.dumps(current_flow_document([{"name": "placement", "tool": "ecc", "state": "Done"}]))
    )

    with pytest.raises(ValueError, match="placement has unknown state 'Done'"):
        load_flow_document(path)


def test_a_step_whose_results_hold_an_unknown_state_fails_to_load(tmp_path):
    from chipcompiler.data.flow.document import STEP_RESULTS_DIGEST_FIELD
    from chipcompiler.data.step.results import STATE_FILE, results_digest
    from test.flow_fixture import current_flow_document

    steps = current_flow_document([{"name": "placement", "tool": "ecc", "state": "Success"}]).get(
        "steps", []
    )
    ledger = {"schema_version": 3, "steps": steps, STEP_RESULTS_DIGEST_FIELD: results_digest(steps)}
    path = tmp_path / "home" / "flow.json"
    path.parent.mkdir()
    path.write_text(json.dumps(ledger))
    step_directory = tmp_path / steps[0]["directory"]
    step_directory.mkdir()
    (step_directory / STATE_FILE).write_text(
        json.dumps({"schema_version": 1, "step": "placement", "tool": "ecc", "state": "Done"})
    )

    with pytest.raises(ValueError, match="placement has unknown state 'Done'"):
        load_flow_document(path)


def test_legacy_parameters_json_is_not_used(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "parameters.json").write_text(json.dumps({"design": "gcd"}))

    with pytest.raises(UnsupportedSchemaVersionError, match="create a new workspace"):
        load_workspace(tmp_path)
