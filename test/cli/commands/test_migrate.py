import json
import os
from pathlib import Path

from chipcompiler.cli import main as cli_main


def _records(capsys):
    return json.loads(capsys.readouterr().out)["records"]


def _manifest(project_dir):
    with open(os.path.join(project_dir, "project.json")) as f:
        return json.load(f)


class TestMigrate:
    def test_full_migration_moves_rebases_and_registers(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        target = os.path.join(project_dir, "exp1")
        assert not os.path.exists(run_dir)
        assert os.path.isfile(os.path.join(target, "home", "ecc.toml"))
        assert not os.path.exists(os.path.join(project_dir, "runs"))

        with open(os.path.join(target, "home", "home.json")) as f:
            home = json.load(f)
        assert home["parameters"] == os.path.join(target, "home", "ecc.toml")
        assert home["flow"] == os.path.join(target, "home", "flow.json")
        assert "runs" not in home["flow"]

        manifest = _manifest(project_dir)
        (entry,) = manifest["workspaces"]
        assert entry["workspace_id"] == "exp1"
        assert entry["workspace_path"] == target
        assert entry["start_step"] == "Synth"
        assert entry["end_step"] == "Floor"
        assert entry["status"] == "success"
        assert manifest["design_name"] == "gcd"
        assert manifest["qor_baseline"]["workspace_id"] == "exp1"
        # The migration base is built exactly like virgin generation:
        # declared source spellings, GUI-flat parameters.
        assert manifest["base_design"] == {
            "pdk": "ics55",
            "pdk_root": str(pdk_root),
            "top_module": "gcd",
            "clock": "clk",
            "rtl_list": ["rtl/gcd.v"],
            "origin_verilog": "rtl/gcd.v",
            "parameters": {
                "design": "gcd",
                "top_module": "gcd",
                "clock": "clk",
                "frequency_max": 100.0,
                "die_area_mode": "utilitization_margin",
            },
        }

        records = _records(capsys)
        assert any(r.get("status") == "migrated" and r.get("run") == "exp1" for r in records)

    def test_non_tty_requires_yes(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = cli_main.run(["migrate", "--project", project_dir, "--json"])

        assert rc != 0
        records = _records(capsys)
        assert records[-1]["error"] == "confirmation_required"
        assert os.path.exists(run_dir)
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_resume_appends_missing_entries(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        remaining = create_legacy_workspace(
            project_dir, pdk_root, "exp2", ["Success", "Incomplete"]
        )
        # Partial prior migration: exp1 already at root + registered.
        os.rename(os.path.join(project_dir, "runs", "exp1"), os.path.join(project_dir, "exp1"))
        document = {
            "schema_version": 1,
            "design_name": "gcd",
            "root_path": project_dir,
            "base_design": {"parameters": {"design": "gcd"}},
            "workspaces": [
                {
                    "workspace_id": "exp1",
                    "workspace_path": os.path.join(project_dir, "exp1"),
                    "status": "success",
                    "start_step": "Synth",
                    "end_step": "Floor",
                }
            ],
        }
        with open(os.path.join(project_dir, "project.json"), "w") as f:
            json.dump(document, f)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        manifest = _manifest(project_dir)
        ids = [w["workspace_id"] for w in manifest["workspaces"]]
        assert ids == ["exp1", "exp2"]
        assert manifest["workspaces"][1]["status"] == "failed"
        assert not os.path.exists(remaining)
        assert not os.path.exists(os.path.join(project_dir, "runs"))

    def test_already_migrated_noop(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        document = {
            "schema_version": 1,
            "design_name": "gcd",
            "root_path": project_dir,
            "workspaces": [],
        }
        with open(os.path.join(project_dir, "project.json"), "w") as f:
            json.dump(document, f)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        (record,) = _records(capsys)
        assert record["status"] == "already_migrated"

    def test_collision_skips_that_workspace(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "rtl", ["Success", "Success"])
        create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        collisions = [r for r in records if r.get("error") == "migration_collision"]
        assert len(collisions) == 1
        assert collisions[0]["run"] == "rtl"
        # The colliding workspace stays; the other one moved.
        assert os.path.exists(run_dir)
        assert os.path.exists(os.path.join(project_dir, "exp2"))
        assert os.path.exists(os.path.join(project_dir, "runs"))

    def test_rebase_failure_rolls_back(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])

        def failing_refresh(workspace):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "chipcompiler.data.refresh_workspace_config",
            failing_refresh,
        )

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        failures = [r for r in records if r.get("error") == "migration_failed"]
        assert len(failures) == 1
        # Rolled back: the workspace is back under runs/, no manifest, and
        # the rebased home.json pointers were restored to the source path.
        assert os.path.isfile(os.path.join(run_dir, "home", "flow.json"))
        assert not os.path.exists(os.path.join(project_dir, "exp1"))
        assert not os.path.exists(os.path.join(project_dir, "project.json"))
        with open(os.path.join(run_dir, "home", "home.json")) as f:
            home = json.load(f)
        assert home["flow"] == os.path.join(run_dir, "home", "flow.json")

    def test_migrate_rejects_broken_ecc_toml(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        with open(f"{project_dir}/ecc.toml", "a") as f:
            f.write('\n[params.synth]\nmax_fanout = "loud"\n')

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        assert any(r.get("error") == "config_error" for r in records)
        assert os.path.exists(run_dir)  # nothing moved
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_registration_failure_moves_batch_back(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run1 = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        run2 = create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])

        monkeypatch.setattr(
            "chipcompiler.cli.project.manifest.write_manifest_if_absent",
            lambda *a, **k: False,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.migrate.find_manifest",
            lambda _dir: None,
        )

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        assert any(r.get("error") == "manifest_update_failed" for r in records)
        assert any(r.get("error") == "migration_rolled_back" for r in records)
        # The whole batch is back under runs/; nothing stranded at the root.
        assert os.path.isfile(os.path.join(run1, "home", "flow.json"))
        assert os.path.isfile(os.path.join(run2, "home", "flow.json"))
        assert not os.path.exists(os.path.join(project_dir, "exp1"))
        assert not os.path.exists(os.path.join(project_dir, "exp2"))
        assert not os.path.exists(os.path.join(project_dir, "project.json"))
        assert os.path.exists(os.path.join(project_dir, "runs"))

    def test_invalid_existing_manifest_fails_before_any_move(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        with open(os.path.join(project_dir, "project.json"), "w") as f:
            f.write("{broken")

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "manifest_invalid"
        assert os.path.exists(run_dir)

    def test_incomplete_outranks_ongoing_in_status_mapping(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Ongoing", "Incomplete"])

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        manifest = _manifest(project_dir)
        assert manifest["workspaces"][0]["status"] == "failed"

    def test_legacy_pdk_config_path_rebased_after_move(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        # Downgrade to a legacy workspace with an absolute PDK Config path.
        from chipcompiler.data.parameter import load_parameter

        parameters = load_parameter(Path(run_dir, "home", "ecc.toml"))
        legacy = dict(parameters.data)
        legacy["PDK Config"] = os.path.join(run_dir, "home", "pdk.json")
        Path(run_dir, "home", "pdk.json").write_text("{}")
        os.unlink(os.path.join(run_dir, "home", "ecc.toml"))
        import json as _json

        long_keys = {"Design": "gcd", "Top module": "gcd", "Clock": "clk", "PDK": "ics55"}
        long_keys["PDK Config"] = legacy["PDK Config"]
        Path(run_dir, "home", "parameters.json").write_text(_json.dumps(long_keys))

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        from chipcompiler.data.parameter import load_parameter as lp

        moved = lp(Path(project_dir, "exp1", "home", "ecc.toml"))
        assert moved.data["pdk_config"] == os.path.join(project_dir, "exp1", "home", "pdk.json")


class TestMigrationPlanningRobustness:
    """Planning never crashes on malformed workspace state: an unreadable
    flow ledger degrades to the empty-ledger defaults, not an exception."""

    def test_non_object_flow_json_migrates_with_defaults(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        # JSON-valid but not an object: unreadable as a flow ledger.
        Path(run_dir, "home", "flow.json").write_text("[]")

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        assert not os.path.exists(os.path.join(project_dir, "runs", "exp1"))
        assert os.path.isfile(os.path.join(project_dir, "exp1", "home", "flow.json"))
        (workspace,) = _manifest(project_dir)["workspaces"]
        assert workspace["status"] == "not_started"

    def test_undecodable_flow_json_migrates_with_defaults(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        Path(run_dir, "home", "flow.json").write_bytes(b"\xff")

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        assert not os.path.exists(os.path.join(project_dir, "runs", "exp1"))
        (workspace,) = _manifest(project_dir)["workspaces"]
        assert workspace["status"] == "not_started"

    def test_undecodable_manifest_is_a_recorded_error_not_a_crash(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        # Resume layout (project.json + runs/): the malformed winner must
        # fail BEFORE the first rename, not escape as UnicodeDecodeError.
        Path(project_dir, "project.json").write_bytes(b"\xff")

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "manifest_invalid"]
        assert "invalid project manifest" in failure["reason"]
        assert os.path.isfile(os.path.join(run_dir, "home", "flow.json"))


class TestMigrationPreview:
    """One exact preview drives disclosure and execution: the manifest
    create document (or resume append set) is visible before mutation on
    every command surface, and execution consumes the very same object."""

    def test_yes_discloses_and_executes_the_exact_create_document(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        records = _records(capsys)
        moves = [r for r in records if r.get("kind") == "plan" and "run" in r]
        assert [(r["run"], r["from"], r["to"]) for r in moves] == [
            (
                "exp1",
                os.path.join(project_dir, "runs", "exp1"),
                os.path.join(project_dir, "exp1"),
            )
        ]
        (create,) = [r for r in records if r.get("manifest") == "create"]
        # Execution consumed the previewed document byte-for-byte.
        assert create["document"] == _manifest(project_dir)

    def test_non_tty_refusal_discloses_preview_without_mutation(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = cli_main.run(["migrate", "--project", project_dir, "--json"])

        assert rc != 0
        records = _records(capsys)
        (create,) = [r for r in records if r.get("manifest") == "create"]
        assert [w["workspace_id"] for w in create["document"]["workspaces"]] == ["exp1"]
        assert records[-1]["error"] == "confirmation_required"
        # Disclosure only: nothing moved, nothing created.
        assert os.path.exists(run_dir)
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_tty_accept_renders_preview_and_executes(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        rc = cli_main.run(["migrate", "--project", project_dir, "--json"])

        assert rc == 0
        # The TTY render shows the full manifest document, not an id summary.
        assert json.dumps(_manifest(project_dir), indent=2) in capsys.readouterr().err
        assert os.path.isfile(os.path.join(project_dir, "exp1", "home", "flow.json"))

    def test_resume_append_disclosed_in_preview(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Incomplete"])
        # Partial prior migration: exp1 already at root + registered.
        os.rename(os.path.join(project_dir, "runs", "exp1"), os.path.join(project_dir, "exp1"))
        document = {
            "schema_version": 1,
            "design_name": "gcd",
            "root_path": project_dir,
            "base_design": {"parameters": {"design": "gcd"}},
            "workspaces": [
                {
                    "workspace_id": "exp1",
                    "workspace_path": os.path.join(project_dir, "exp1"),
                    "status": "success",
                    "start_step": "Synth",
                    "end_step": "Floor",
                }
            ],
        }
        with open(os.path.join(project_dir, "project.json"), "w") as f:
            json.dump(document, f)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        records = _records(capsys)
        (append,) = [r for r in records if r.get("manifest") == "append"]
        (appended,) = [
            w for w in _manifest(project_dir)["workspaces"] if w["workspace_id"] == "exp2"
        ]
        # The applied entry IS the previewed entry, complete and verbatim.
        (previewed,) = append["workspaces"]
        assert appended == previewed

    def test_mixed_result_baseline_follows_first_success(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        """A failed first move must not own the manifest: workspaces and
        qor_baseline derive together from the successful moves."""
        import chipcompiler.data

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])

        real_refresh = chipcompiler.data.refresh_workspace_config

        def selective_refresh(workspace):
            if str(workspace.directory).endswith("exp1"):
                raise RuntimeError("boom")
            return real_refresh(workspace)

        monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", selective_refresh)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        manifest = _manifest(project_dir)
        assert [w["workspace_id"] for w in manifest["workspaces"]] == ["exp2"]
        assert manifest["qor_baseline"]["workspace_id"] == "exp2"
        # The failed move was rolled back under runs/.
        assert os.path.isfile(os.path.join(project_dir, "runs", "exp1", "home", "flow.json"))
        assert not os.path.exists(os.path.join(project_dir, "exp1"))

    def test_resume_with_huge_integer_mpc_index_does_not_crash(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
        manifest_stubs,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        # The resume path validates the existing manifest BEFORE moving:
        # a huge MPC index must pass the parser without OverflowError.
        manifest_stubs.write(
            Path(project_dir),
            [],
            mpc={
                "resource_id": "mpc:x",
                "display_name": "d",
                "installed_version": "1",
                "path": "/p",
                "spec_path": "/p/spec/spec.json.in",
                "design": {"index": 10**400, "design_name": "gcd"},
                "core_template": {},
            },
        )

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        assert not os.path.exists(os.path.join(project_dir, "runs", "exp1"))
        assert os.path.isfile(os.path.join(project_dir, "exp1", "home", "flow.json"))
