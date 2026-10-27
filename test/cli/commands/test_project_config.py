import json

from chipcompiler.cli import main as cli_main
from chipcompiler.project.manifest_write import manifest_workspace_entry


def _records(capsys, plain_records):
    return plain_records(capsys.readouterr().out)


def _manifest_project(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    assert cli_main.run(["init", str(project_dir)]) == 0
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    return project_dir


def _manifest(project_dir):
    return json.loads((project_dir / "project.json").read_text())


def _run_project(project_dir, *args):
    assert cli_main.run(["project", *args, "--project", str(project_dir), "--plain"]) == 0


def test_project_set_and_show_design_resource(capsys, create_cli_project, plain_records):
    project_dir = create_cli_project()

    rc = cli_main.run(
        ["project", "set", "design.def", "inputs/gcd.def", "--project", project_dir, "--plain"]
    )

    assert rc == 0
    assert _records(capsys, plain_records) == [
        {
            "project_field": "design.def",
            "value": "inputs/gcd.def",
            "status": "set",
            "source": "ecc.toml",
        }
    ]

    rc = cli_main.run(["project", "show", "design.def", "--project", project_dir, "--plain"])

    assert rc == 0
    assert _records(capsys, plain_records)[0]["value"] == "inputs/gcd.def"


def test_project_rtl_list_replacement_and_incremental_changes(
    capsys, create_cli_project, plain_records
):
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
            "--plain",
        ]
    )
    assert rc == 0
    assert _records(capsys, plain_records)[0]["value"] == "['rtl/gcd.sv', 'rtl/alu.sv']"

    rc = cli_main.run(
        ["project", "add", "design.rtl", "rtl/fifo.sv", "--project", project_dir, "--plain"]
    )
    assert rc == 0
    assert (
        _records(capsys, plain_records)[0]["value"] == "['rtl/gcd.sv', 'rtl/alu.sv', 'rtl/fifo.sv']"
    )

    rc = cli_main.run(
        ["project", "remove", "design.rtl", "rtl/alu.sv", "--project", project_dir, "--plain"]
    )
    assert rc == 0
    assert _records(capsys, plain_records)[0]["value"] == "['rtl/gcd.sv', 'rtl/fifo.sv']"


def test_project_set_rejects_unknown_field(capsys, create_cli_project, plain_records):
    project_dir = create_cli_project()

    rc = cli_main.run(
        ["project", "set", "design.unknown", "value", "--project", project_dir, "--plain"]
    )

    assert rc == 1
    assert _records(capsys, plain_records) == [
        {"kind": "error", "error": "unknown_project_field", "key": "design.unknown"}
    ]


def test_project_set_syncs_manifest_base_design(tmp_path, monkeypatch):
    project_dir = _manifest_project(tmp_path, monkeypatch)
    pdk = tmp_path / "pdk"
    pdk.mkdir()

    _run_project(project_dir, "set", "design.top", "gcd_top")
    _run_project(project_dir, "set", "design.frequency_mhz", "250")
    _run_project(project_dir, "set", "pdk.root", str(pdk))

    base = _manifest(project_dir)["base_design"]
    assert base["top_module"] == "gcd_top"
    assert base["parameters"]["top_module"] == "gcd_top"
    assert base["parameters"]["frequency_max"] == 250.0
    assert base["pdk_root"] == str(pdk)


def test_project_rtl_changes_sync_manifest_base_design(tmp_path, monkeypatch):
    project_dir = _manifest_project(tmp_path, monkeypatch)

    _run_project(project_dir, "set", "design.rtl", "rtl/gcd.sv", "rtl/alu.sv")
    assert _manifest(project_dir)["base_design"]["rtl_list"] == [
        "rtl/gcd.sv",
        "rtl/alu.sv",
    ]

    _run_project(project_dir, "add", "design.rtl", "rtl/fifo.sv")
    assert _manifest(project_dir)["base_design"]["rtl_list"] == [
        "rtl/gcd.sv",
        "rtl/alu.sv",
        "rtl/fifo.sv",
    ]

    _run_project(project_dir, "remove", "design.rtl", "rtl/alu.sv")
    assert _manifest(project_dir)["base_design"]["rtl_list"] == [
        "rtl/gcd.sv",
        "rtl/fifo.sv",
    ]


def test_project_unset_syncs_manifest_base_design(tmp_path, monkeypatch):
    project_dir = _manifest_project(tmp_path, monkeypatch)

    _run_project(project_dir, "set", "design.def", "inputs/top.def")
    assert _manifest(project_dir)["base_design"]["origin_def"] == "inputs/top.def"

    _run_project(project_dir, "unset", "design.def")
    assert _manifest(project_dir)["base_design"].get("origin_def", "") == ""


def test_project_set_repairs_stale_manifest_when_toml_is_unchanged(tmp_path, monkeypatch):
    project_dir = _manifest_project(tmp_path, monkeypatch)
    command = ("set", "design.top", "gcd_top")
    _run_project(project_dir, *command)

    document = _manifest(project_dir)
    document["base_design"]["top_module"] = "stale"
    (project_dir / "project.json").write_text(json.dumps(document))

    _run_project(project_dir, *command)
    assert _manifest(project_dir)["base_design"]["top_module"] == "gcd_top"


def test_project_set_prevents_config_layer_divergence(tmp_path, monkeypatch, capsys, plain_records):
    project_dir = _manifest_project(tmp_path, monkeypatch)
    pdk = tmp_path / "pdk"
    pdk.mkdir()
    (project_dir / "rtl" / "demo.v").write_text("module demo(input clk); endmodule\n")

    for key, value in (
        ("pdk.root", str(pdk)),
        ("design.top", "demo_top"),
        ("design.rtl", "rtl/demo.v"),
    ):
        _run_project(project_dir, "set", key, value)

    document = _manifest(project_dir)
    document["workspaces"].append(
        manifest_workspace_entry(
            "ws1",
            name="project",
            workspace_path=str(project_dir / "ws1"),
            start_step="Synth",
            end_step="Harden",
            status="not_started",
            now="2026-01-01T00:00:00+00:00",
        )
    )
    (project_dir / "project.json").write_text(json.dumps(document))
    capsys.readouterr()
    assert (
        cli_main.run(["check", "--workspace", "ws1", "--project", str(project_dir), "--plain"]) == 0
    )
    records = _records(capsys, plain_records)
    assert not [record for record in records if record.get("warning") == "config_layer_diverged"]
