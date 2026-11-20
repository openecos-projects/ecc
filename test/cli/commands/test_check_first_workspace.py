"""`ecc check` on a project that has no workspace yet (#463)."""

import json

from chipcompiler.cli import main as cli_main


class TestCheckBeforeTheFirstWorkspace:
    """`ecc init` hints `ecc check`, and the first workspace only comes with `ecc run`."""

    @staticmethod
    def _new_project(tmp_path, monkeypatch, *, with_rtl=True, with_pdk=True):
        project_dir = tmp_path / "project"
        assert cli_main.run(["init", str(project_dir)]) == 0
        if with_rtl:
            (project_dir / "rtl" / "project.v").write_text("module project(input clk); endmodule\n")
        monkeypatch.delenv("ICS55_PDK_ROOT", raising=False)
        if with_pdk:
            pdk = tmp_path / "pdk"
            pdk.mkdir()
            monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(pdk))
            monkeypatch.setattr(
                "chipcompiler.cli.project.config._validate_pdk_contents",
                lambda name, root, overrides=None: None,
            )
        else:
            monkeypatch.delenv("CHIPCOMPILER_ICS55_PDK_ROOT", raising=False)
        return project_dir

    @staticmethod
    def _check(project_dir, capsys, plain_records, *extra):
        capsys.readouterr()
        rc = cli_main.run(["check", "--project", str(project_dir), *extra, "--plain"])
        return rc, plain_records(capsys.readouterr().out)

    def test_check_validates_a_project_that_has_no_workspace(
        self, tmp_path, monkeypatch, capsys, plain_records
    ):
        project_dir = self._new_project(tmp_path, monkeypatch)
        manifest = (project_dir / "project.json").read_text()

        rc, records = self._check(project_dir, capsys, plain_records)

        assert rc == 0
        assert (records[0]["status"], records[0]["workspace"]) == ("checked", "default")
        assert (records[1]["check"], records[1]["status"]) == ("rtl", "pass")
        # A check does not create or declare anything.
        assert (project_dir / "project.json").read_text() == manifest
        assert json.loads(manifest)["workspaces"] == []
        assert not (project_dir / "default").exists()

    def test_check_from_inside_a_project_that_has_no_workspace(
        self, tmp_path, monkeypatch, capsys, plain_records
    ):
        project_dir = self._new_project(tmp_path, monkeypatch)
        monkeypatch.chdir(project_dir)
        capsys.readouterr()

        rc = cli_main.run(["check", "--plain"])

        assert rc == 0
        assert plain_records(capsys.readouterr().out)[0]["status"] == "checked"

    def test_check_reports_the_missing_rtl_of_a_new_project(
        self, tmp_path, monkeypatch, capsys, plain_records
    ):
        project_dir = self._new_project(tmp_path, monkeypatch, with_rtl=False)

        rc, records = self._check(project_dir, capsys, plain_records)

        assert rc == 1
        assert [(r.get("check"), r.get("status"), r.get("path")) for r in records] == [
            ("rtl", "fail", "rtl/project.v")
        ]

    def test_check_reports_the_missing_pdk_of_a_new_project(
        self, tmp_path, monkeypatch, capsys, plain_records
    ):
        project_dir = self._new_project(tmp_path, monkeypatch, with_pdk=False)

        rc, records = self._check(project_dir, capsys, plain_records)

        assert rc == 1
        assert "pdk.root is required" in [r.get("reason") for r in records]
        assert all(r.get("error") != "workspace_required" for r in records)

    def test_an_unknown_workspace_is_still_rejected(
        self, tmp_path, monkeypatch, capsys, plain_records
    ):
        project_dir = self._new_project(tmp_path, monkeypatch)

        rc, records = self._check(project_dir, capsys, plain_records, "--workspace", "default")

        assert rc == 1
        assert records[0]["error"] == "workspace_not_declared"

    def test_commands_that_need_a_workspace_still_ask_for_one(
        self, tmp_path, monkeypatch, capsys, plain_records
    ):
        project_dir = self._new_project(tmp_path, monkeypatch)
        capsys.readouterr()

        rc = cli_main.run(["status", "--project", str(project_dir), "--plain"])

        assert rc == 1
        assert plain_records(capsys.readouterr().out)[0]["error"] == "workspace_required"
