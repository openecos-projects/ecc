import json
import shlex

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter_schema import list_schemas
from chipcompiler.engine.workspace_spec import describe_workspace_spec


def _records(output: str) -> list[dict[str, str]]:
    return [
        dict(field.split("=", 1) for field in shlex.split(line)) for line in output.splitlines()
    ]


def test_parameter_catalog_is_context_free_and_typed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert cli_main.run(["param", "list", "--all", "--plain"]) == 0

    records = _records(capsys.readouterr().out)
    assert [record["id"] for record in records] == sorted(schema.param for schema in list_schemas())
    assert all(record["record"] == "parameter" for record in records)
    density = next(record for record in records if record["id"] == "place.target_density")
    assert json.loads(density["default_literal"]) == 0.2
    assert json.loads(density["range_literal"]) == [0.1, 0.95]
    assert json.loads(density["maps_to_literal"]) == {"dreamplace": "target_density"}


def test_flow_catalog_is_context_free_and_ordered(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert cli_main.run(["flow", "list", "--plain"]) == 0

    records = _records(capsys.readouterr().out)
    expected = describe_workspace_spec()["flowDefinitions"]
    assert {record["flow_id"] for record in records} == {flow["flowId"] for flow in expected}
    for flow in expected:
        actual = [record for record in records if record["flow_id"] == flow["flowId"]]
        assert [record["step_id"] for record in actual] == flow["stepIds"]
        assert [int(record["ordinal"]) for record in actual] == list(range(len(actual)))
