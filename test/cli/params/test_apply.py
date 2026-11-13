from chipcompiler.cli import main as cli_main


def test_project_parameter_apply_is_atomic(ready_project):
    project = ready_project

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


def test_parameter_apply_rejects_conflicting_batch_without_writes(ready_project):
    project = ready_project
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
