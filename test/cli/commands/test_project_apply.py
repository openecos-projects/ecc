import json

from chipcompiler.cli import main as cli_main


def _ready_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    pdk = tmp_path / "pdk"
    pdk.mkdir()
    assert cli_main.run(["init", str(project)]) == 0
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    return project, pdk


def test_project_apply_commits_config_and_manifest_together(tmp_path, monkeypatch):
    project, pdk = _ready_project(tmp_path, monkeypatch)

    rc = cli_main.run(
        [
            "project",
            "apply",
            "--project",
            str(project),
            "--set",
            f"pdk.root={pdk}",
            "--set",
            "design.frequency_mhz=250",
            "--set",
            "place.target_density=0.7",
            "--add-rtl",
            "rtl/extra.v",
        ]
    )

    assert rc == 0
    config = (project / "ecc.toml").read_text()
    manifest = json.loads((project / "project.json").read_text())
    assert "frequency_mhz = 250.0" in config
    assert "target_density = 0.7" in config
    assert manifest["base_design"]["pdk_root"] == str(pdk)
    assert manifest["base_design"]["parameters"]["frequency_max"] == 250.0


def test_project_apply_invalid_batch_changes_nothing(tmp_path, monkeypatch):
    project, pdk = _ready_project(tmp_path, monkeypatch)
    before_config = (project / "ecc.toml").read_text()
    before_manifest = (project / "project.json").read_text()

    rc = cli_main.run(
        [
            "project",
            "apply",
            "--project",
            str(project),
            "--set",
            f"pdk.root={pdk}",
            "--set",
            "place.target_density=2.0",
        ]
    )

    assert rc == 1
    assert (project / "ecc.toml").read_text() == before_config
    assert (project / "project.json").read_text() == before_manifest


def test_project_reconcile_repairs_stale_base_design(tmp_path, monkeypatch):
    project, pdk = _ready_project(tmp_path, monkeypatch)
    text = (project / "ecc.toml").read_text().replace('root = ""', f'root = "{pdk}"')
    (project / "ecc.toml").write_text(text)

    assert cli_main.run(["project", "reconcile", "--project", str(project), "--no-wait"]) == 0

    manifest = json.loads((project / "project.json").read_text())
    assert manifest["base_design"]["pdk_root"] == str(pdk)


def test_project_reconcile_accepts_fresh_project_before_pdk_binding(tmp_path):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project)]) == 0

    assert cli_main.run(["project", "reconcile", "--project", str(project), "--no-wait"]) == 0

    manifest = json.loads((project / "project.json").read_text())
    assert manifest["workspaces"] == []
    assert manifest["base_design"].get("pdk_root", "") == ""


def test_project_apply_no_wait_returns_busy_without_changes(tmp_path, monkeypatch):
    from chipcompiler.project.manifest_write import manifest_lock

    project, _pdk = _ready_project(tmp_path, monkeypatch)
    before_config = (project / "ecc.toml").read_text()
    before_manifest = (project / "project.json").read_text()

    with manifest_lock(project):
        rc = cli_main.run(
            [
                "project",
                "apply",
                "--project",
                str(project),
                "--set",
                "design.frequency_mhz=250",
                "--no-wait",
            ]
        )

    assert rc == 20
    assert (project / "ecc.toml").read_text() == before_config
    assert (project / "project.json").read_text() == before_manifest
