import os

import pytest

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


class _FakeResult:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


class TestPdkSetup:
    @pytest.fixture(autouse=True)
    def available_tools(self, monkeypatch):
        """Simulate a host with git/make so tests exercise clone/unzip behavior."""
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    def test_setup_missing_tool_fails_before_clone(
        self, tmp_path, capsys, monkeypatch, create_cli_project, plain_records
    ):
        project_dir = create_cli_project(pdk_root="")
        monkeypatch.setattr("shutil.which", lambda name: None if name == "git" else name)

        rc = cli_main.run(
            ["pdk", "setup", str(tmp_path / "fresh-pdk"), "--project", project_dir, "--plain"]
        )

        record = plain_records(capsys.readouterr().out)[0]
        assert rc == 1
        assert record["error"] == "missing_tool"
        assert "git" in record["reason"]

    def test_setup_refuses_unrecognized_nonempty_directory(
        self, tmp_path, capsys, monkeypatch, create_cli_project, plain_records
    ):
        project_dir = create_cli_project(pdk_root="")
        stranger = tmp_path / "stranger"
        stranger.mkdir()
        (stranger / "Makefile").write_text("all:\n\techo pwned\n")

        rc = cli_main.run(["pdk", "setup", str(stranger), "--project", project_dir, "--plain"])

        record = plain_records(capsys.readouterr().out)[0]
        assert rc == 1
        assert record["error"] == "invalid_pdk_dir"
        assert not list(stranger.iterdir()) or list(stranger.iterdir()) == [stranger / "Makefile"]

    def test_setup_complete_checkout_only_sets_root(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        project_dir = create_cli_project(pdk_root="")
        pdk_dir = tmp_path / "ready-pdk"
        pdk_dir.mkdir()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["pdk", "setup", str(pdk_dir), "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert data[0]["status"] == "ready"
        assert data[0]["actions"] == "[]"  # nothing fetched
        assert f'root = "{pdk_dir}"' in _read_toml(project_dir)

    def test_setup_clones_and_unzips_missing_checkout(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        import subprocess as real_subprocess

        project_dir = create_cli_project(pdk_root="")
        pdk_dir = tmp_path / "fresh-pdk"
        calls = {"clone": [], "make": []}

        def fake_run(cmd, cwd=None, *, capture_output=True, text=True, **kwargs):
            if cmd[:2] == ["git", "clone"]:
                calls["clone"].append(cmd)
                pdk_dir.mkdir(exist_ok=True)  # pretend the clone created the checkout
                (pdk_dir / ".git").mkdir()
                (pdk_dir / ".git" / "config").write_text(
                    '[remote "origin"]\n\turl = https://github.com/ecos-studio/icsprout55-pdk.git\n'
                )
                return _FakeResult()
            if cmd[0] == "make":
                calls["make"].append((cmd, cwd))
                return _FakeResult()
            return real_subprocess.run(
                cmd, cwd=cwd, capture_output=capture_output, text=text, **kwargs
            )

        monkeypatch.setattr("subprocess.run", fake_run)
        problems = {"first": "PDK has no liberty files"}

        def fake_validate(name, root, overrides=None):
            return problems.get("first") if not calls["make"] else None

        monkeypatch.setattr("chipcompiler.cli.project.config._validate_pdk_contents", fake_validate)

        rc = cli_main.run(["pdk", "setup", str(pdk_dir), "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert data[0]["actions"] == "['clone', 'unzip']"
        assert calls["clone"][0][-1] == str(pdk_dir)
        assert calls["make"][0][1] == str(pdk_dir)
        assert f'root = "{pdk_dir}"' in _read_toml(project_dir)

    def test_setup_clone_failure(
        self, tmp_path, capsys, monkeypatch, create_cli_project, plain_records
    ):
        import subprocess as real_subprocess

        project_dir = create_cli_project(pdk_root="")
        pdk_dir = tmp_path / "never-created"

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["git", "clone"]:
                return _FakeResult(returncode=128, stderr="fatal: repository not found")
            return real_subprocess.run(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", fake_run)

        rc = cli_main.run(["pdk", "setup", str(pdk_dir), "--project", project_dir, "--plain"])

        record = plain_records(capsys.readouterr().out)[0]
        assert rc == 1
        assert record["error"] == "clone_failed"
        assert "repository not found" in record["reason"]

    def test_setup_unzip_retries_then_fails(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        import subprocess as real_subprocess

        project_dir = create_cli_project(pdk_root="")
        pdk_dir = tmp_path / "stubborn-pdk"
        pdk_dir.mkdir()
        (pdk_dir / ".git").mkdir()
        (pdk_dir / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/ecos-studio/icsprout55-pdk.git\n'
        )
        make_calls = []

        def fake_run(cmd, cwd=None, **kwargs):
            if cmd[0] == "make":
                make_calls.append(cmd)
                return _FakeResult(returncode=2, stderr="curl: (28) timeout")
            return real_subprocess.run(cmd, cwd=cwd, **kwargs)

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: "PDK has no liberty files",
        )

        rc = cli_main.run(["pdk", "setup", str(pdk_dir), "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert len(make_calls) == 3  # retried three times
        assert data[0]["error"] == "unzip_failed"

    def test_setup_unzip_recovers_on_retry(
        self, tmp_path, capsys, monkeypatch, create_cli_project, plain_records
    ):
        import subprocess as real_subprocess

        project_dir = create_cli_project(pdk_root="")
        pdk_dir = tmp_path / "flaky-pdk"
        pdk_dir.mkdir()
        (pdk_dir / ".git").mkdir()
        (pdk_dir / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/ecos-studio/icsprout55-pdk.git\n'
        )
        attempts = {"n": 0}

        def fake_run(cmd, cwd=None, **kwargs):
            if cmd[0] == "make":
                attempts["n"] += 1
                ok = attempts["n"] >= 2
                return _FakeResult(returncode=0 if ok else 1)
            return real_subprocess.run(cmd, cwd=cwd, **kwargs)

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_validate(name, root, overrides=None):
            return None if attempts["n"] >= 2 else "PDK has no liberty files"

        monkeypatch.setattr("chipcompiler.cli.project.config._validate_pdk_contents", fake_validate)

        rc = cli_main.run(["pdk", "setup", str(pdk_dir), "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert attempts["n"] == 2
        assert data[0]["actions"] == "[unzip]"

    def test_setup_forwards_gh_proxy_to_make(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        import subprocess as real_subprocess

        project_dir = create_cli_project(pdk_root="")
        pdk_dir = tmp_path / "proxy-pdk"
        pdk_dir.mkdir()
        (pdk_dir / ".git").mkdir()
        (pdk_dir / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/ecos-studio/icsprout55-pdk.git\n'
        )
        seen = {}

        def fake_run(cmd, cwd=None, **kwargs):
            if cmd[0] == "make":
                seen["cmd"] = cmd
                return _FakeResult()
            return real_subprocess.run(cmd, cwd=cwd, **kwargs)

        monkeypatch.setattr("subprocess.run", fake_run)

        def fake_validate(name, root, overrides=None):
            return "PDK has no liberty files" if "cmd" not in seen else None

        monkeypatch.setattr("chipcompiler.cli.project.config._validate_pdk_contents", fake_validate)
        monkeypatch.setenv("GH_PROXY", "https://gh-proxy.org/")

        rc = cli_main.run(["pdk", "setup", str(pdk_dir), "--project", project_dir, "--plain"])

        assert rc == 0
        assert seen["cmd"] == [
            "make",
            "unzip",
            "USE_PROXY=true",
            "GH_PROXY=https://gh-proxy.org/",
        ]

    def test_setup_default_path_when_argument_omitted(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        project_dir = create_cli_project(pdk_root="")
        monkeypatch.setattr(
            "chipcompiler.cli.command_handlers.pdk.DEFAULT_PDK_DIR", str(tmp_path / "default-pdk")
        )
        (tmp_path / "default-pdk").mkdir()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["pdk", "setup", "--project", project_dir, "--plain"])

        data = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert data[0]["path"] == str(tmp_path / "default-pdk")
