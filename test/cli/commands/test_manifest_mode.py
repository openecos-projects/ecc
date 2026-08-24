import json
import os

from chipcompiler.cli import main as cli_main


def _write_manifest(project_dir, workspaces, **overrides):
    document = {
        "schema_version": 1,
        "design_name": "gcd",
        "root_path": str(project_dir),
        "workspaces": workspaces,
    }
    document.update(overrides)
    (project_dir / "project.json").write_text(json.dumps(document))


def _workspace_entry(project_dir, workspace_id, status="success"):
    return {
        "workspace_id": workspace_id,
        "workspace_path": str(project_dir / workspace_id),
        "status": status,
    }


def _records(capsys):
    return json.loads(capsys.readouterr().out)["records"]


class TestManifestRunDiscovery:
    def test_single_active_workspace_auto_selected(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])
        run_dir = project_dir / "ws_0001"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert _records(capsys)[0]["workspace"] == str(run_dir)

    def test_run_id_selects_by_workspace_id_or_path_tail(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(
            project_dir,
            [
                _workspace_entry(project_dir, "ws_0001"),
                _workspace_entry(project_dir, "ws_0002"),
            ],
        )
        run_dir = project_dir / "ws_0002"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run(
            ["status", "--project", str(project_dir), "--run-id", "ws_0002", "--json"]
        )

        assert rc == 0
        assert _records(capsys)[0]["workspace"] == str(run_dir)

    def test_multiple_workspaces_without_run_id_errors(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(
            project_dir,
            [
                _workspace_entry(project_dir, "ws_0001"),
                _workspace_entry(project_dir, "ws_0002"),
            ],
        )

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["kind"] == "error"
        assert record["error"] == "workspace_not_declared"
        assert "ws_0001" in record["reason"]
        assert "ws_0002" in record["reason"]

    def test_unknown_run_id_errors_with_declared_ids(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["status", "--project", str(project_dir), "--run-id", "nope", "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "workspace_not_declared"
        assert "ws_0001" in record["reason"]

    def test_archived_workspace_not_auto_selected(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(
            project_dir,
            [
                _workspace_entry(project_dir, "ws_0001", status="archived"),
                _workspace_entry(project_dir, "ws_0002"),
            ],
        )
        run_dir = project_dir / "ws_0002"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert _records(capsys)[0]["workspace"] == str(run_dir)

    def test_invalid_manifest_errors(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "project.json").write_text("{broken")

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "manifest_invalid"


class TestManifestCheck:
    def test_check_reports_manifest_project(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = _records(capsys)
        assert records[0]["status"] == "checked"
        assert records[0]["config"] == "project.json"


class TestLegacyHint:
    def test_check_emits_legacy_hint_in_runs_project(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        os.makedirs(os.path.join(project_dir, "runs", "default"))

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = _records(capsys)
        hint = [r for r in records if r.get("warning") == "legacy_layout_detected"]
        assert len(hint) == 1
        assert "ecc migrate" in hint[0]["migrate"]

    def test_check_no_hint_in_virgin_project(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = _records(capsys)
        assert all(r.get("warning") != "legacy_layout_detected" for r in records)

    def test_check_no_hint_in_manifest_project(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = _records(capsys)
        assert all(r.get("warning") != "legacy_layout_detected" for r in records)

    def test_status_emits_legacy_hint_in_runs_project(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc == 0
        records = _records(capsys)
        hint = [r for r in records if r.get("warning") == "legacy_layout_detected"]
        assert len(hint) == 1
