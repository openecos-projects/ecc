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
    config = project / "ecc.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace('root = ""', f'root = "{pdk}"'),
        encoding="utf-8",
    )
    return project


def test_project_parameter_apply_is_atomic(tmp_path, monkeypatch):
    project = _ready_project(tmp_path, monkeypatch)

    rc = cli_main.run(
        [
            "param",
            "apply",
            "--project",
            str(project),
            "--set",
            "design.frequency_mhz=250",
            "--set",
            "place.target_density=0.65",
        ]
    )

    assert rc == 0
    text = (project / "ecc.toml").read_text(encoding="utf-8")
    assert "frequency_mhz = 250.0" in text
    assert "target_density = 0.65" in text


def test_parameter_apply_rejects_conflicting_batch_without_writes(tmp_path, monkeypatch):
    project = _ready_project(tmp_path, monkeypatch)
    before = (project / "ecc.toml").read_bytes()

    rc = cli_main.run(
        [
            "param",
            "apply",
            "--project",
            str(project),
            "--set",
            "place.target_density=0.65",
            "--unset",
            "place.target_density",
        ]
    )

    assert rc == 1
    assert (project / "ecc.toml").read_bytes() == before
