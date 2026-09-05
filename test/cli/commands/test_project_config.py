import json

from chipcompiler.cli import main as cli_main


def _records(capsys):
    return json.loads(capsys.readouterr().out)["records"]


def test_project_set_and_show_design_resource(capsys, create_cli_project):
    project_dir = create_cli_project()

    rc = cli_main.run(
        ["project", "set", "design.def", "inputs/gcd.def", "--project", project_dir, "--json"]
    )

    assert rc == 0
    assert _records(capsys) == [
        {
            "project_field": "design.def",
            "value": "inputs/gcd.def",
            "status": "set",
            "source": "ecc.toml",
        }
    ]

    rc = cli_main.run(["project", "show", "design.def", "--project", project_dir, "--json"])

    assert rc == 0
    assert _records(capsys)[0]["value"] == "inputs/gcd.def"


def test_project_rtl_list_replacement_and_incremental_changes(capsys, create_cli_project):
    project_dir = create_cli_project()

    rc = cli_main.run(
        [
            "project",
            "set",
            "design.rtl",
            "rtl/gcd.sv",
            "rtl/alu.sv",
            "--project",
            project_dir,
            "--json",
        ]
    )
    assert rc == 0
    assert _records(capsys)[0]["value"] == ["rtl/gcd.sv", "rtl/alu.sv"]

    rc = cli_main.run(
        ["project", "add", "design.rtl", "rtl/fifo.sv", "--project", project_dir, "--json"]
    )
    assert rc == 0
    assert _records(capsys)[0]["value"] == ["rtl/gcd.sv", "rtl/alu.sv", "rtl/fifo.sv"]

    rc = cli_main.run(
        ["project", "remove", "design.rtl", "rtl/alu.sv", "--project", project_dir, "--json"]
    )
    assert rc == 0
    assert _records(capsys)[0]["value"] == ["rtl/gcd.sv", "rtl/fifo.sv"]


def test_project_set_rejects_unknown_field(capsys, create_cli_project):
    project_dir = create_cli_project()

    rc = cli_main.run(
        ["project", "set", "design.unknown", "value", "--project", project_dir, "--json"]
    )

    assert rc == 1
    assert _records(capsys) == [
        {"kind": "error", "error": "unknown_project_field", "key": "design.unknown"}
    ]
