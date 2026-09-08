import os

from chipcompiler.cli import main as cli_main


def _read_toml(project_dir):
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        return f.read()


class TestPdkSetRoot:
    def test_set_root_writes_absolute_path(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project(pdk_root="")
        target = tmp_path / "my-pdk"
        target.mkdir()

        rc = cli_main.run(["pdk", "set-root", str(target), "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert data[0]["status"] == "set"
        assert data[0]["path"] == str(target)
        assert f'root = "{target}"' in _read_toml(project_dir)

    def test_set_root_expands_relative_path(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        project_dir = create_cli_project(pdk_root="")
        target = tmp_path / "rel-pdk"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        rc = cli_main.run(["pdk", "set-root", "rel-pdk", "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert data[0]["path"] == str(target)
        assert f'root = "{target}"' in _read_toml(project_dir)

    def test_set_root_rejects_missing_directory(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project(pdk_root="")

        rc = cli_main.run(
            ["pdk", "set-root", str(tmp_path / "nope"), "--project", project_dir, "--plain"]
        )

        record = plain_records(capsys.readouterr().out)[0]
        assert rc == 1
        assert record["error"] == "invalid_pdk_path"

    def test_set_root_warns_on_incomplete_contents(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        project_dir = create_cli_project(pdk_root="")
        target = tmp_path / "bare-pdk"  # exists but has no LEF/liberty
        target.mkdir()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: "PDK has no liberty files",
        )

        rc = cli_main.run(["pdk", "set-root", str(target), "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0  # advisory: set-root still succeeds
        assert data[0]["status"] == "set"
        assert data[1]["status"] == "incomplete"
        assert "make unzip" in data[1]["hint"]

    def test_set_root_preserves_other_keys(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project(pdk_root="/old/location")

        rc = cli_main.run(["pdk", "set-root", str(tmp_path), "--project", project_dir, "--plain"])

        toml = _read_toml(project_dir)
        assert rc == 0
        assert 'name = "ics55"' in toml  # sibling keys untouched
        assert "/old/location" not in toml
        assert f'root = "{tmp_path}"' in toml


class TestPdkShow:
    def test_show_reports_ecc_toml_source(
        self, tmp_path, capsys, monkeypatch, create_cli_project, plain_records
    ):
        project_dir = create_cli_project(pdk_root=str(tmp_path / "pdk-a"))
        (tmp_path / "pdk-a").mkdir()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["pdk", "show", "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0
        record = data[0]
        assert record["name"] == "ics55"
        assert record["source"] == "ecc.toml"
        assert record["root"] == str(tmp_path / "pdk-a")
        assert data[1]["status"] == "pass"

    def test_show_reports_env_source(
        self, tmp_path, capsys, monkeypatch, create_cli_project, plain_records
    ):
        project_dir = create_cli_project(pdk_root="")
        env_dir = tmp_path / "env-pdk"
        env_dir.mkdir()
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_dir))
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["pdk", "show", "--project", project_dir, "--plain"])

        record = plain_records(capsys.readouterr().out)[0]
        assert rc == 0
        assert record["source"] == "CHIPCOMPILER_ICS55_PDK_ROOT"
        assert record["root"] == str(env_dir)

    def test_show_flags_missing_root(
        self, tmp_path, capsys, monkeypatch, create_cli_project, plain_records
    ):
        project_dir = create_cli_project(pdk_root=str(tmp_path / "ghost"))  # never created
        monkeypatch.delenv("CHIPCOMPILER_ICS55_PDK_ROOT", raising=False)
        monkeypatch.delenv("ICS55_PDK_ROOT", raising=False)

        rc = cli_main.run(["pdk", "show", "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0  # show is advisory
        assert data[1]["status"] == "missing"
        assert "set-root" in data[1]["set_root"]

    def test_show_reports_unreadable_config(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        project_dir = create_cli_project()

        def deny(_config_path):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr("chipcompiler.cli.project.config.load_project_config", deny)

        rc = cli_main.run(["pdk", "show", "--project", project_dir, "--plain"])

        assert rc == 1
        records = plain_records(capsys.readouterr().out)
        assert records[0]["kind"] == "error"
        assert records[0]["error"] == "config_error"
        assert records[0]["reason"].startswith("unreadable project config:")
        assert records[0]["inspect"] == f"ecc check --project {project_dir}"


class TestPdkUnset:
    def test_unset_restores_empty_root(self, tmp_path, capsys, create_cli_project, plain_records):
        project_dir = create_cli_project(pdk_root=str(tmp_path))

        rc = cli_main.run(["pdk", "unset", "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert data[0]["status"] == "unset"
        assert 'root = ""' in _read_toml(project_dir)

    def test_unset_then_show_falls_back_to_env(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        project_dir = create_cli_project(pdk_root=str(tmp_path))
        env_dir = tmp_path / "env-pdk"
        env_dir.mkdir()
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_dir))
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        cli_main.run(["pdk", "unset", "--project", project_dir, "--plain"])
        capsys.readouterr()
        rc = cli_main.run(["pdk", "show", "--project", project_dir, "--plain"])

        record = plain_records(capsys.readouterr().out)[0]
        assert rc == 0
        assert record["source"] == "CHIPCOMPILER_ICS55_PDK_ROOT"
