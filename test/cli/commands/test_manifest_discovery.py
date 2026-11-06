import json
import os

import pytest

from chipcompiler.cli import main as cli_main


class TestManifestRunDiscovery:
    def test_single_active_workspace_auto_selected(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        run_dir = project_dir / "ws_0001"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text('{"schema_version": 2, "steps": []}')

        rc = cli_main.run(["status", "--project", str(project_dir), "--plain"])

        assert rc == 0
        assert manifest_stubs.records()[0]["workspace"] == str(run_dir)

    def test_workspace_selects_by_declared_id(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(
            project_dir,
            [
                manifest_stubs.entry(project_dir, "ws_0001"),
                manifest_stubs.entry(project_dir, "ws_0002"),
            ],
        )
        run_dir = project_dir / "ws_0002"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text('{"schema_version": 2, "steps": []}')

        rc = cli_main.run(
            ["status", "--project", str(project_dir), "--workspace", "ws_0002", "--plain"]
        )

        assert rc == 0
        assert manifest_stubs.records()[0]["workspace"] == str(run_dir)

    def test_multiple_workspaces_without_selector_errors(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(
            project_dir,
            [
                manifest_stubs.entry(project_dir, "ws_0001"),
                manifest_stubs.entry(project_dir, "ws_0002"),
            ],
        )

        rc = cli_main.run(["status", "--project", str(project_dir), "--plain"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["kind"] == "error"
        assert record["error"] == "workspace_required"
        assert "ws_0001" in record["reason"]
        assert "ws_0002" in record["reason"]

    def test_nested_workspace_name_is_invalid_not_undeclared(
        self, tmp_path, capsys, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = cli_main.run(
            ["status", "--project", str(project_dir), "--workspace", "sweeps/s1", "--plain"]
        )

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["kind"] == "error"
        assert record["error"] == "invalid_workspace"
        assert record["reason"].startswith("invalid_workspace:")

    def test_absolute_workspace_path_is_not_declared(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = cli_main.run(
            ["status", "--project", str(project_dir), "--workspace", "/tmp/x", "--plain"]
        )

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["kind"] == "error"
        assert record["error"] == "workspace_not_declared"
        assert "x" in record["reason"]

    def test_unknown_workspace_errors_with_declared_ids(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = cli_main.run(
            ["status", "--project", str(project_dir), "--workspace", "nope", "--plain"]
        )

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "workspace_not_declared"
        assert "ws_0001" in record["reason"]

    def test_archived_workspace_not_auto_selected(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(
            project_dir,
            [
                manifest_stubs.entry(project_dir, "ws_0001", status="archived"),
                manifest_stubs.entry(project_dir, "ws_0002"),
            ],
        )
        run_dir = project_dir / "ws_0002"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text('{"schema_version": 2, "steps": []}')

        rc = cli_main.run(["status", "--project", str(project_dir), "--plain"])

        assert rc == 0
        assert manifest_stubs.records()[0]["workspace"] == str(run_dir)

    def test_invalid_manifest_errors(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "project.json").write_text("{broken")

        rc = cli_main.run(["status", "--project", str(project_dir), "--plain"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "manifest_invalid"


class TestManifestCheck:
    def test_check_reports_manifest_project(
        self, tmp_path, capsys, minimal_ics55_pdk_factory, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        minimal_ics55_pdk_factory(project_dir / "pdk")

        rc = cli_main.run(["check", "--project", str(project_dir), "--plain"])

        assert rc == 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "checked"
        assert records[0]["config"] == "project.json"


class TestLegacyWorkspaceRejected:
    @pytest.mark.parametrize("command", ["check", "status", "run"])
    def test_legacy_runs_project_is_rejected(
        self,
        command,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        manifest_stubs,
        monkeypatch,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        os.makedirs(os.path.join(project_dir, "runs", "default"), exist_ok=True)
        handler = {
            "run": "chipcompiler.cli.command_handlers.project.run",
            "check": "chipcompiler.cli.command_handlers.project.check",
            "status": "chipcompiler.cli.command_handlers.inspect.status",
        }[command]
        monkeypatch.setattr(
            handler,
            lambda *_args, **_kwargs: pytest.fail("legacy project handler must not run"),
        )

        rc = cli_main.run([command, "--project", project_dir, "--plain"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "legacy_workspace_unsupported"
        assert "create a new project and workspace" in record["reason"]


class TestParamManifestMode:
    def _manifest_project(self, manifest_stubs, tmp_path):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        return project_dir

    def test_param_list_requires_ecc_toml(self, tmp_path, capsys, manifest_stubs):
        project_dir = self._manifest_project(manifest_stubs, tmp_path)

        rc = cli_main.run(["param", "list", "--project", str(project_dir), "--plain"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "param_requires_ecc_toml"

    def test_param_set_requires_ecc_toml(self, tmp_path, capsys, manifest_stubs):
        project_dir = self._manifest_project(manifest_stubs, tmp_path)

        rc = cli_main.run(
            ["param", "set", "cts.max_fanout", "16", "--project", str(project_dir), "--plain"]
        )

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "param_requires_ecc_toml"
        assert not (project_dir / "ecc.toml").exists()


class TestCheckManifestSelection:
    def test_check_errors_when_workspace_selection_ambiguous(
        self, tmp_path, capsys, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(
            project_dir,
            [
                manifest_stubs.entry(project_dir, "ws_0001"),
                manifest_stubs.entry(project_dir, "ws_0002"),
            ],
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--plain"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "workspace_required"

    def test_check_ok_with_single_workspace(
        self, tmp_path, capsys, minimal_ics55_pdk_factory, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        minimal_ics55_pdk_factory(project_dir / "pdk")

        rc = cli_main.run(["check", "--project", str(project_dir)])

        assert rc == 0


class TestHybridCheck:
    def test_hybrid_check_errors_on_ambiguous_selection(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, manifest_stubs
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        (tmp_path / "gcd" / "project.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "design_name": "gcd",
                    "root_path": project_dir,
                    "workspaces": [
                        {"workspace_id": "ws_0001", "workspace_path": f"{project_dir}/ws_0001"},
                        {"workspace_id": "ws_0002", "workspace_path": f"{project_dir}/ws_0002"},
                    ],
                }
            )
        )

        rc = cli_main.run(["check", "--project", project_dir, "--plain"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "workspace_required"
