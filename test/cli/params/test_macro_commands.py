import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter import Parameters


class _Flow:
    def __init__(self, workspace):
        self.workspace = workspace

    def save(self):
        return True


def _workspace(workspace_dir):
    parameters_path = workspace_dir / "home" / "params.toml"
    parameters_path.parent.mkdir(parents=True)
    return SimpleNamespace(
        directory=workspace_dir,
        parameters=Parameters(
            path=parameters_path,
            data={
                "pdk": "ics55",
                "design": "gcd",
                "top_module": "gcd",
                "clock": "clk",
            },
        ),
        config={},
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "Synthesis", "state": "Success", "runtime": "", "peak memory (mb)": 0},
                    {
                        "name": "macroPlacement",
                        "state": "Success",
                        "runtime": "",
                        "peak memory (mb)": 0,
                    },
                    {"name": "place", "state": "Success", "runtime": "", "peak memory (mb)": 0},
                ]
            }
        ),
    )


def _write_manifest(project_dir: str) -> None:
    project_path = Path(project_dir)
    (project_path / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "design_name": "gcd",
                "root_path": project_dir,
                "base_design": {
                    "pdk": "ics55",
                    "pdk_root": str(project_path / "ics55"),
                    "top_module": "gcd",
                    "clock": "clk",
                    "rtl_list": ["rtl/gcd.v"],
                    "parameters": {"design": "gcd", "frequency_max": 100},
                },
                "workspaces": [
                    {
                        "workspace_id": "baseline",
                        "workspace_path": str(project_path / "baseline"),
                        "status": "success",
                    }
                ],
            }
        )
    )


def _read_macro_placements(project_dir: str) -> list:
    config_path = Path(project_dir) / "ecc.toml"
    with config_path.open("rb") as f:
        return tomllib.load(f)["params"]["macro"]["placements"]


def test_macro_set_project_writes_params_table(capsys, create_cli_project, plain_records):
    project_dir = create_cli_project()

    rc = cli_main.run(
        [
            "macro",
            "set",
            "u_ram0",
            "--x",
            "10",
            "--y",
            "20.5",
            "--orient",
            "R0",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert record["status"] == "set"
    assert record["source"] == "ecc.toml"
    assert "'u_ram0'" in record["placements"]
    assert _read_macro_placements(project_dir) == [
        {"instance": "u_ram0", "x": 10.0, "y": 20.5, "orientation": "R0"}
    ]


def test_macro_set_upserts_by_instance(capsys, create_cli_project):
    project_dir = create_cli_project()
    for args in (
        ["u_ram0", "--x", "10", "--y", "20", "--orient", "R0"],
        ["u_ram0", "--x", "30", "--y", "40", "--orient", "MY"],
        ["u_ram1", "--x", "1", "--y", "2", "--orient", "MX"],
    ):
        assert cli_main.run(["macro", "set", *args, "--project", project_dir, "--plain"]) == 0

    assert _read_macro_placements(project_dir) == [
        {"instance": "u_ram0", "x": 30.0, "y": 40.0, "orientation": "MY"},
        {"instance": "u_ram1", "x": 1.0, "y": 2.0, "orientation": "MX"},
    ]


def test_macro_remove_project_filters_and_deletes_empty(capsys, create_cli_project):
    project_dir = create_cli_project()
    cli_main.run(
        [
            "macro",
            "set",
            "u_ram0",
            "--x",
            "1",
            "--y",
            "2",
            "--orient",
            "R0",
            "--project",
            project_dir,
            "--plain",
        ]
    )
    cli_main.run(
        [
            "macro",
            "set",
            "u_ram1",
            "--x",
            "3",
            "--y",
            "4",
            "--orient",
            "R0",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert cli_main.run(["macro", "remove", "u_ram0", "--project", project_dir, "--plain"]) == 0
    assert _read_macro_placements(project_dir) == [
        {"instance": "u_ram1", "x": 3.0, "y": 4.0, "orientation": "R0"}
    ]

    assert cli_main.run(["macro", "remove", "u_ram1", "--project", project_dir, "--plain"]) == 0
    with (Path(project_dir) / "ecc.toml").open("rb") as f:
        document = tomllib.load(f)
    assert "macro" not in document.get("params", {})


def test_macro_set_rejects_bad_orientation(capsys, create_cli_project, plain_records):
    project_dir = create_cli_project()
    before = (Path(project_dir) / "ecc.toml").read_bytes()

    rc = cli_main.run(
        [
            "macro",
            "set",
            "u_ram0",
            "--x",
            "1",
            "--y",
            "2",
            "--orient",
            "r0",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 1
    record = plain_records(capsys.readouterr().out)[0]
    assert record["kind"] == "error"
    assert record["error"] == "invalid_value"
    assert (Path(project_dir) / "ecc.toml").read_bytes() == before


def test_macro_set_workspace_persists_and_invalidates_suffix(
    capsys, create_cli_project, monkeypatch, plain_records
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda _workspace: None)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)

    rc = cli_main.run(
        [
            "macro",
            "set",
            "u_ram0",
            "--x",
            "10",
            "--y",
            "20",
            "--orient",
            "R0",
            "--workspace",
            "baseline",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert record["status"] == "set"
    assert record["instance"] == "u_ram0"
    assert record["from_step"] == "macroPlacement"
    assert "'u_ram0'" in record["placements"]
    assert workspace.parameters.data["macro"]["placements"] == [
        {"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}
    ]
    assert [step["state"] for step in workspace.flow.data["steps"]] == [
        "Success",
        "Unstart",
        "Unstart",
    ]
    assert "workspace_param_overrides" in workspace.parameters.path.read_text()


def test_macro_remove_workspace_absent_instance_is_noop(
    capsys, create_cli_project, monkeypatch, plain_records
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda _workspace: None)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)
    workspace.parameters.path.write_text("# baseline params\n")
    before = workspace.parameters.path.read_bytes()

    rc = cli_main.run(
        [
            "macro",
            "remove",
            "u_missing",
            "--workspace",
            "baseline",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert record["status"] == "absent"
    assert record["placements"] == "[]"
    assert workspace.parameters.path.read_bytes() == before


def test_macro_show_lists_entries_and_file(capsys, create_cli_project, monkeypatch, plain_records):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    workspace.parameters.data["macro"] = {
        "placements": [{"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}]
    }
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)

    rc = cli_main.run(
        ["macro", "show", "--workspace", "baseline", "--project", project_dir, "--plain"]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert "'u_ram0'" in record["placements"]
    assert record["file"] == str(workspace_dir / "config" / "macro_location.tcl")


def test_macro_import_project_replaces_placements_wholesale(
    capsys, create_cli_project, plain_records, tmp_path
):
    project_dir = create_cli_project()
    cli_main.run(
        [
            "macro",
            "set",
            "u_old",
            "--x",
            "1",
            "--y",
            "2",
            "--orient",
            "R0",
            "--project",
            project_dir,
            "--plain",
        ]
    )
    capsys.readouterr()
    handoff = tmp_path / "macro_location.tcl"
    handoff.write_text(
        "# Hard-macro placement commands generated by saveMacroTCL().\n"
        "placeInstance u_a 10 20.5 R0\n"
        "setInstancePlacementStatus -status fixed -name u_a\n"
        "placeInstance u_b 1 2 MY90\n"
    )

    rc = cli_main.run(["macro", "import", str(handoff), "--project", project_dir, "--plain"])

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert record["status"] == "imported"
    assert record["source"] == "ecc.toml"
    assert record["source_file"] == str(handoff)
    assert _read_macro_placements(project_dir) == [
        {"instance": "u_a", "x": 10.0, "y": 20.5, "orientation": "R0"},
        {"instance": "u_b", "x": 1.0, "y": 2.0, "orientation": "MY90"},
    ]


def test_macro_import_workspace_replaces_placements_and_invalidates_suffix(
    capsys, create_cli_project, monkeypatch, plain_records, tmp_path
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    workspace.parameters.data["macro"] = {
        "placements": [{"instance": "u_old", "x": 1.0, "y": 2.0, "orientation": "R0"}]
    }
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda _workspace: None)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)
    handoff = tmp_path / "macro_location.tcl"
    handoff.write_text("placeInstance u_a 10 20.5 R0\n")

    rc = cli_main.run(
        [
            "macro",
            "import",
            str(handoff),
            "--workspace",
            "baseline",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert record["status"] == "imported"
    assert record["from_step"] == "macroPlacement"
    assert "'u_a'" in record["placements"]
    assert workspace.parameters.data["macro"]["placements"] == [
        {"instance": "u_a", "x": 10.0, "y": 20.5, "orientation": "R0"}
    ]
    assert [step["state"] for step in workspace.flow.data["steps"]] == [
        "Success",
        "Unstart",
        "Unstart",
    ]


def test_macro_import_empty_handoff_clears_project_placements(
    capsys, create_cli_project, plain_records, tmp_path
):
    project_dir = create_cli_project()
    cli_main.run(
        [
            "macro",
            "set",
            "u_old",
            "--x",
            "1",
            "--y",
            "2",
            "--orient",
            "R0",
            "--project",
            project_dir,
            "--plain",
        ]
    )
    capsys.readouterr()
    handoff = tmp_path / "macro_location.tcl"
    handoff.write_text("# Auto-generated macro location file\n\n")

    rc = cli_main.run(["macro", "import", str(handoff), "--project", project_dir, "--plain"])

    assert rc == 0
    with (Path(project_dir) / "ecc.toml").open("rb") as f:
        document = tomllib.load(f)
    assert "macro" not in document.get("params", {})


def test_macro_import_rejects_unreadable_file(capsys, create_cli_project, plain_records):
    project_dir = create_cli_project()
    before = (Path(project_dir) / "ecc.toml").read_bytes()

    rc = cli_main.run(
        [
            "macro",
            "import",
            str(Path(project_dir) / "missing.tcl"),
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 1
    record = plain_records(capsys.readouterr().out)[0]
    assert record["error"] == "file_unreadable"
    assert (Path(project_dir) / "ecc.toml").read_bytes() == before


def test_macro_import_rejects_malformed_handoff(
    capsys, create_cli_project, plain_records, tmp_path
):
    project_dir = create_cli_project()
    before = (Path(project_dir) / "ecc.toml").read_bytes()
    handoff = tmp_path / "macro_location.tcl"
    handoff.write_text("moveInstance u0 1 2 R0\n")

    rc = cli_main.run(["macro", "import", str(handoff), "--project", project_dir, "--plain"])

    assert rc == 1
    record = plain_records(capsys.readouterr().out)[0]
    assert record["error"] == "invalid_value"
    assert (Path(project_dir) / "ecc.toml").read_bytes() == before


def test_macro_show_reports_file_placements_and_divergence(
    capsys, create_cli_project, monkeypatch, plain_records
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    workspace.parameters.data["macro"] = {
        "placements": [{"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}]
    }
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)
    tcl_path = workspace_dir / "config" / "macro_location.tcl"
    tcl_path.parent.mkdir(parents=True)
    tcl_path.write_text("placeInstance u_ram0 10.000000 20.000000 R0\n")

    rc = cli_main.run(
        ["macro", "show", "--workspace", "baseline", "--project", project_dir, "--plain"]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert "'u_ram0'" in record["file_placements"]
    assert record["diverged"] == "False"

    tcl_path.write_text("placeInstance u_ram0 11 20 R0\n")
    capsys.readouterr()

    rc = cli_main.run(
        ["macro", "show", "--workspace", "baseline", "--project", project_dir, "--plain"]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert record["diverged"] == "True"


def test_macro_show_reports_missing_handoff_file(
    capsys, create_cli_project, monkeypatch, plain_records
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    workspace.parameters.data["macro"] = {
        "placements": [{"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}]
    }
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)

    rc = cli_main.run(
        ["macro", "show", "--workspace", "baseline", "--project", project_dir, "--plain"]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert "macro_location.tcl is missing or unreadable" in record["file_error"]
