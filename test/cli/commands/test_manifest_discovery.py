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
        (run_dir / "home" / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert manifest_stubs.records()[0]["workspace"] == str(run_dir)

    def test_run_id_selects_by_workspace_id_or_path_tail(self, tmp_path, capsys, manifest_stubs):
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
        (run_dir / "home" / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run(
            ["status", "--project", str(project_dir), "--run-id", "ws_0002", "--json"]
        )

        assert rc == 0
        assert manifest_stubs.records()[0]["workspace"] == str(run_dir)

    def test_multiple_workspaces_without_run_id_errors(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(
            project_dir,
            [
                manifest_stubs.entry(project_dir, "ws_0001"),
                manifest_stubs.entry(project_dir, "ws_0002"),
            ],
        )

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["kind"] == "error"
        assert record["error"] == "workspace_not_declared"
        assert "ws_0001" in record["reason"]
        assert "ws_0002" in record["reason"]

    def test_nested_run_id_is_invalid_not_undeclared(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = cli_main.run(
            ["status", "--project", str(project_dir), "--run-id", "sweeps/s1", "--json"]
        )

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "invalid_run_id"

    def test_absolute_run_id_is_invalid_not_undeclared(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = cli_main.run(["status", "--project", str(project_dir), "--run-id", "/tmp/x", "--json"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "invalid_run_id"

    def test_unknown_run_id_errors_with_declared_ids(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = cli_main.run(["status", "--project", str(project_dir), "--run-id", "nope", "--json"])

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
        (run_dir / "home" / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert manifest_stubs.records()[0]["workspace"] == str(run_dir)

    def test_invalid_manifest_errors(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "project.json").write_text("{broken")

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

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

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "checked"
        assert records[0]["config"] == "project.json"


class TestLegacyHint:
    def test_check_emits_legacy_hint_in_runs_project(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, manifest_stubs
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        os.makedirs(os.path.join(project_dir, "runs", "default"))

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        hint = [r for r in records if r.get("warning") == "legacy_layout_detected"]
        assert len(hint) == 1
        assert "ecc migrate" in hint[0]["migrate"]

    def test_check_no_hint_in_virgin_project(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, manifest_stubs
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert all(r.get("warning") != "legacy_layout_detected" for r in records)

    def test_check_no_hint_in_manifest_project(
        self, tmp_path, capsys, minimal_ics55_pdk_factory, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        minimal_ics55_pdk_factory(project_dir / "pdk")

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert all(r.get("warning") != "legacy_layout_detected" for r in records)

    def test_status_emits_legacy_hint_in_runs_project(
        self, tmp_path, capsys, create_cli_project, create_flow_json, manifest_stubs
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        hint = [r for r in records if r.get("warning") == "legacy_layout_detected"]
        assert len(hint) == 1


class TestLegacyHintBoundary:
    """AC-16: the hint rides every run/check/status outcome on legacy
    projects — success and error alike — and never appears elsewhere."""

    @staticmethod
    def _hints(records):
        return [r for r in records if r.get("warning") == "legacy_layout_detected"]

    @pytest.mark.parametrize("command", ["check", "status"])
    def test_success_outcome_carries_hint(
        self,
        command,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_flow_json,
        manifest_stubs,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_flow_json(os.path.join(project_dir, "runs", "default"), profile="main")

        rc = cli_main.run([command, "--project", project_dir, "--json"])

        assert rc == 0
        assert len(self._hints(manifest_stubs.records())) == 1

    def test_run_success_carries_hint(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        flow_mocks,
        manifest_stubs,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        # Legacy shape without an existing default run: a fresh run succeeds.
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        assert len(self._hints(manifest_stubs.records())) == 1

    def test_status_missing_flow_carries_hint(
        self, tmp_path, capsys, create_cli_project, manifest_stubs
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"))

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc != 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "missing"
        assert len(self._hints(records)) == 1

    def test_status_corrupt_flow_carries_hint(
        self, tmp_path, capsys, create_cli_project, manifest_stubs
    ):
        project_dir = create_cli_project()
        home = os.path.join(project_dir, "runs", "default", "home")
        os.makedirs(home)
        with open(os.path.join(home, "flow.json"), "w") as f:
            f.write("{broken")

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc != 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "corrupt"
        assert len(self._hints(records)) == 1

    def test_run_failure_carries_hint(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        flow_mocks,
        manifest_stubs,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        flow_mocks.flow.run_steps_value = False

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "failed"
        assert len(self._hints(records)) == 1

    def test_config_error_carries_hint(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, manifest_stubs
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        with open(os.path.join(project_dir, "ecc.toml"), "a") as f:
            f.write("\n[params.cts]\nmax_fanout = 0\n")

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc != 0
        assert len(self._hints(manifest_stubs.records())) == 1

    @pytest.mark.parametrize("command", ["check", "status"])
    def test_manifest_project_never_hints(
        self,
        command,
        tmp_path,
        capsys,
        minimal_ics55_pdk_factory,
        manifest_stubs,
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        minimal_ics55_pdk_factory(project_dir / "pdk")
        home = project_dir / "ws_0001" / "home"
        home.mkdir(parents=True)
        (home / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run([command, "--project", str(project_dir), "--json"])

        assert rc == 0
        assert self._hints(manifest_stubs.records()) == []

    def test_manifest_run_never_hints(
        self,
        tmp_path,
        capsys,
        minimal_ics55_pdk_factory,
        flow_mocks,
        manifest_stubs,
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        minimal_ics55_pdk_factory(project_dir / "pdk")

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert self._hints(manifest_stubs.records()) == []


class TestParamManifestMode:
    def _manifest_project(self, manifest_stubs, tmp_path):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        return project_dir

    def test_param_list_requires_ecc_toml(self, tmp_path, capsys, manifest_stubs):
        project_dir = self._manifest_project(manifest_stubs, tmp_path)

        rc = cli_main.run(["param", "list", "--project", str(project_dir), "--json"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "param_requires_ecc_toml"

    def test_param_set_requires_ecc_toml(self, tmp_path, capsys, manifest_stubs):
        project_dir = self._manifest_project(manifest_stubs, tmp_path)

        rc = cli_main.run(
            ["param", "set", "cts.max_fanout", "16", "--project", str(project_dir), "--json"]
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

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "workspace_not_declared"

    def test_check_ok_with_single_workspace(
        self, tmp_path, capsys, minimal_ics55_pdk_factory, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        minimal_ics55_pdk_factory(project_dir / "pdk")

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

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

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "workspace_not_declared"
