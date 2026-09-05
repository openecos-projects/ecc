import json
from pathlib import Path

from chipcompiler.cli import main as cli_main


def _set_design_inputs(project_dir: str) -> tuple[Path, Path]:
    project = Path(project_dir)
    design_def = project / "input" / "gcd.def"
    netlist = project / "input" / "gcd.v"
    design_def.parent.mkdir()
    design_def.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")
    netlist.write_text("module gcd; endmodule\n")
    config_path = project / "ecc.toml"
    config_path.write_text(
        config_path.read_text()
        .replace('run = "default"\n', "")
        .replace(
            'clock_port = "clk"',
            'def = "input/gcd.def"\nnetlist = "input/gcd.v"\nclock_port = "clk"',
        )
    )
    return design_def, netlist


def test_new_workspace_range_uses_ecc_toml_inputs_and_registers_before_execution(
    monkeypatch, tmp_path, capsys, create_cli_project, flow_mocks
):
    project_dir = create_cli_project()
    design_def, netlist = _set_design_inputs(project_dir)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
        lambda: [("CTS", "ecc", "Unstart")],
    )

    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--workspace",
            "cts-only",
            "--from",
            "CTS",
            "--to",
            "CTS",
            "--json",
        ]
    )

    assert rc == 0
    create_kwargs = flow_mocks.capture["create_kwargs"]
    assert create_kwargs["directory"] == str(Path(project_dir) / "cts-only")
    assert create_kwargs["origin_def"] == str(design_def)
    assert create_kwargs["origin_verilog"] == str(netlist)
    assert create_kwargs["flow_config"] == {"start_step": "CTS", "end_step": "CTS"}
    manifest = json.loads((Path(project_dir) / "project.json").read_text())
    entry = manifest["workspaces"][0]
    assert entry["workspace_id"] == "cts-only"
    assert entry["status"] == "success"
    assert "input_snapshot" not in entry
    result = json.loads(capsys.readouterr().out)["records"][0]
    assert result["workspace_id"] == "cts-only"
    assert result["status"] == "success"


def test_fresh_workspace_requires_a_complete_flow_range(tmp_path, capsys, create_cli_project):
    project_dir = create_cli_project()

    rc = cli_main.run(
        ["run", "--project", project_dir, "--workspace", "cts-only", "--from", "CTS", "--json"]
    )

    assert rc == 1
    assert json.loads(capsys.readouterr().out)["records"] == [
        {"kind": "error", "error": "flow_range_requires_pair"}
    ]
    assert not (Path(project_dir) / "project.json").exists()


def test_flow_range_rejects_overwrite(tmp_path, capsys, create_cli_project):
    project_dir = create_cli_project()

    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--workspace",
            "cts-only",
            "--from",
            "CTS",
            "--to",
            "CTS",
            "--overwrite",
            "--json",
        ]
    )

    assert rc == 1
    assert json.loads(capsys.readouterr().out)["records"] == [
        {"kind": "error", "error": "selector_conflict"}
    ]
