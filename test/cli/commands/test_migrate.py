import json
import os
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


def _create_legacy_workspace(project_dir, pdk_root, run_id, states):
    from chipcompiler.data import create_workspace

    rtl_path = os.path.join(project_dir, "rtl", "gcd.v")
    os.makedirs(os.path.dirname(rtl_path), exist_ok=True)
    with open(rtl_path, "w") as f:
        f.write("module gcd(input clk, output y); assign y = clk; endmodule\n")

    run_dir = os.path.join(project_dir, "runs", run_id)
    workspace = create_workspace(
        directory=run_dir,
        origin_def="",
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    steps = [
        {
            "name": "Synthesis",
            "tool": "yosys",
            "state": states[0],
            "runtime": "",
            "peak memory (mb)": 0,
            "info": {},
        },
        {
            "name": "Floorplan",
            "tool": "ecc",
            "state": states[1],
            "runtime": "",
            "peak memory (mb)": 0,
            "info": {},
        },
    ]
    with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
        json.dump({"steps": steps}, f)
    return run_dir


def _records(capsys):
    return json.loads(capsys.readouterr().out)["records"]


def _manifest(project_dir):
    with open(os.path.join(project_dir, "project.json")) as f:
        return json.load(f)


class TestMigrate:
    def test_full_migration_moves_rebases_and_registers(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])

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
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = cli_main.run(["migrate", "--project", project_dir, "--json"])

        assert rc != 0
        records = _records(capsys)
        assert records[-1]["error"] == "confirmation_required"
        assert os.path.exists(run_dir)
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_resume_appends_missing_entries(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        remaining = _create_legacy_workspace(
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
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "rtl", ["Success", "Success"])
        _create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])

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
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])

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
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        with open(f"{project_dir}/ecc.toml", "a") as f:
            f.write('\n[params.synth]\nmax_fanout = "loud"\n')

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        assert any(r.get("error") == "config_error" for r in records)
        assert os.path.exists(run_dir)  # nothing moved
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_registration_failure_moves_batch_back(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run1 = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        run2 = _create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])

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
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        with open(os.path.join(project_dir, "project.json"), "w") as f:
            f.write("{broken")

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "manifest_invalid"
        assert os.path.exists(run_dir)

    def test_incomplete_outranks_ongoing_in_status_mapping(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Ongoing", "Incomplete"])

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        manifest = _manifest(project_dir)
        assert manifest["workspaces"][0]["status"] == "failed"

    def test_legacy_pdk_config_path_rebased_after_move(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
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


class TestMigrationPreview:
    """One exact preview drives disclosure and execution: the manifest
    create document (or resume append set) is visible before mutation on
    every command surface, and execution consumes the very same object."""

    def test_yes_discloses_and_executes_the_exact_create_document(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])

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
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
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
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        rc = cli_main.run(["migrate", "--project", project_dir, "--json"])

        assert rc == 0
        # The TTY render shows the full manifest document, not an id summary.
        assert json.dumps(_manifest(project_dir), indent=2) in capsys.readouterr().err
        assert os.path.isfile(os.path.join(project_dir, "exp1", "home", "flow.json"))

    def test_resume_append_disclosed_in_preview(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        _create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Incomplete"])
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
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        """A failed first move must not own the manifest: workspaces and
        qor_baseline derive together from the successful moves."""
        import chipcompiler.data

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        _create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])

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


def _tree_snapshot(root):
    """{relpath: (kind, payload)} for every entry under root — files carry
    bytes, symlinks their target, directories a marker."""
    root_path = Path(root)
    snapshot = {}
    for path in sorted(root_path.rglob("*")):
        rel = str(path.relative_to(root_path))
        if path.is_symlink():
            snapshot[rel] = ("link", str(path.readlink()))
        elif path.is_file():
            snapshot[rel] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[rel] = ("dir", None)
        else:
            snapshot[rel] = ("other", None)
    return snapshot


def _external_workspace(tmp_path):
    """A plausible workspace OUTSIDE the project, to be reached via runs/ links."""
    external = tmp_path / "external"
    home = external / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps({"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]})
    )
    (home / "home.json").write_text(
        json.dumps({"parameters": str(home / "ecc.toml"), "flow": str(home / "flow.json")})
    )
    (home / "ecc.toml").write_text('[design]\nname = "gcd"\n[pdk]\nname = "ics55"\n')
    (external / "keep.txt").write_text("precious\n")
    os.symlink("keep.txt", external / "keep-link.txt")
    return external


class TestMigrationSymlinkSafety:
    """AC-17: migration never follows a symlinked run source nor mutates a
    project-external tree — at discovery, at move time, and after rename."""

    def test_symlinked_run_source_never_mutates_external_tree(
        self, tmp_path, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        external = _external_workspace(tmp_path)
        os.symlink(external, os.path.join(project_dir, "runs", "linked"))
        before = _tree_snapshot(external)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        (failure,) = [r for r in records if r.get("error") == "migration_failed"]
        assert failure["run"] == "linked"
        # The external tree is untouched (bytes, dirs, and symlinks), the
        # link stays under runs/, and nothing was moved or registered.
        assert _tree_snapshot(external) == before
        assert os.path.islink(os.path.join(project_dir, "runs", "linked"))
        assert not os.path.exists(os.path.join(project_dir, "linked"))
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_real_sibling_migrates_while_unsafe_entry_stays(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        external = _external_workspace(tmp_path)
        os.symlink(external, os.path.join(project_dir, "runs", "linked"))
        before = _tree_snapshot(external)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        assert any(
            r.get("error") == "migration_failed" and r.get("run") == "linked" for r in records
        )
        assert any(r.get("status") == "migrated" and r.get("run") == "exp1" for r in records)
        # The real sibling migrated and registered alone; the link and
        # runs/ stay put, and the external tree is untouched.
        assert os.path.isfile(os.path.join(project_dir, "exp1", "home", "flow.json"))
        manifest = _manifest(project_dir)
        assert [w["workspace_id"] for w in manifest["workspaces"]] == ["exp1"]
        assert _tree_snapshot(external) == before
        assert os.path.islink(os.path.join(project_dir, "runs", "linked"))
        assert os.path.isdir(os.path.join(project_dir, "runs"))

    def test_source_substitution_after_preview_is_rejected(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        import shutil

        import chipcompiler.cli.project.migrate as migrate_module

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        external = _external_workspace(tmp_path)

        real_plan = migrate_module.plan_migration

        def swapping_plan(project_dir_arg):
            plan = real_plan(project_dir_arg)
            # Substitute the planned source with a symlink BEFORE execution.
            shutil.rmtree(run_dir)
            os.symlink(external, run_dir)
            return plan

        monkeypatch.setattr(migrate_module, "plan_migration", swapping_plan)
        before = _tree_snapshot(external)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        (failure,) = [r for r in records if r.get("error") == "migration_failed"]
        assert "unsafe run source" in failure["reason"]
        # The execution-time revalidation rejected the swapped source
        # without writing anywhere; the substituted link stays under runs/.
        assert _tree_snapshot(external) == before
        assert os.path.islink(run_dir)
        assert not os.path.exists(os.path.join(project_dir, "project.json"))


def _external_runs_with_workspace(tmp_path):
    """A real runs-like tree OUTSIDE the project, with one workspace inside."""
    home = tmp_path / "external-runs" / "exp1" / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps({"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]})
    )
    (home / "ecc.toml").write_text('[design]\nname = "gcd"\n[pdk]\nname = "ics55"\n')
    return tmp_path / "external-runs"


def _substitute_workspace(tmp_path, steps):
    """A real directory (with a keep file) standing by to replace a planned
    source after preview."""
    substitute = tmp_path / "substitute"
    home = substitute / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(json.dumps({"steps": steps}))
    (substitute / "keep.txt").write_text("precious\n")
    return substitute


class TestMigrationIdentityBinding:
    """AC-17: migration acts only on the exact confirmed objects — container,
    sources, and absent targets — across the plan→confirm→execute window."""

    def test_symlinked_runs_container_refused_before_enumeration(
        self, tmp_path, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        external_runs = _external_runs_with_workspace(tmp_path)
        os.rmdir(os.path.join(project_dir, "runs"))
        os.symlink(external_runs, os.path.join(project_dir, "runs"))
        before = _tree_snapshot(external_runs)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert "unsafe runs container" in failure["reason"]
        # Nothing enumerated or moved: the external tree is identical,
        # nothing landed at the project root, no manifest was written.
        assert _tree_snapshot(external_runs) == before
        assert not os.path.exists(os.path.join(project_dir, "exp1"))
        assert not os.path.exists(os.path.join(project_dir, "project.json"))
        assert os.path.islink(os.path.join(project_dir, "runs"))

    def test_real_source_substitution_after_preview_fails(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        import shutil

        import chipcompiler.cli.project.migrate as migrate_module

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        substitute = _substitute_workspace(
            tmp_path, [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]
        )
        before = _tree_snapshot(substitute)

        real_plan = migrate_module.plan_migration

        def swapping_plan(project_dir_arg):
            plan = real_plan(project_dir_arg)
            # Replace the confirmed source with a DIFFERENT real directory.
            shutil.rmtree(run_dir)
            shutil.move(str(substitute), run_dir)
            return plan

        monkeypatch.setattr(migrate_module, "plan_migration", swapping_plan)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert failure["reason"] == "run source changed after preview"
        # The substitute was never migrated or rebased: it sits unchanged
        # at the runs/ path, and no manifest was written.
        assert _tree_snapshot(run_dir) == before
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    @pytest.mark.parametrize("appearance", ["empty_dir", "file", "symlink"])
    def test_target_appearance_after_preview_is_collision(
        self,
        appearance,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
    ):
        import chipcompiler.cli.project.migrate as migrate_module

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        _create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])
        target = os.path.join(project_dir, "exp1")
        external = _external_workspace(tmp_path)
        external_before = _tree_snapshot(external)

        real_plan = migrate_module.plan_migration

        def appearing_plan(project_dir_arg):
            plan = real_plan(project_dir_arg)
            if appearance == "empty_dir":
                os.mkdir(target)
            elif appearance == "file":
                Path(target).write_text("occupied\n")
            else:
                os.symlink(external, target)
            return plan

        monkeypatch.setattr(migrate_module, "plan_migration", appearing_plan)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        (collision,) = [r for r in records if r.get("error") == "migration_collision"]
        assert collision["run"] == "exp1"
        # The appearing object is UNTOUCHED and the source stays under runs/.
        if appearance == "empty_dir":
            assert os.path.isdir(target) and not os.path.islink(target)
            assert os.listdir(target) == []
        elif appearance == "file":
            assert Path(target).read_text() == "occupied\n"
        else:
            assert os.path.islink(target)
            assert os.readlink(target) == str(external)
            assert _tree_snapshot(external) == external_before
        assert os.path.isfile(os.path.join(run_dir, "home", "flow.json"))
        # The safe sibling still migrates and registers alone.
        assert any(r.get("status") == "migrated" and r.get("run") == "exp2" for r in records)
        manifest = _manifest(project_dir)
        assert [w["workspace_id"] for w in manifest["workspaces"]] == ["exp2"]
        assert os.path.isdir(os.path.join(project_dir, "runs"))

    def test_substitution_between_preflight_and_rename_is_rejected_after_move(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        import shutil

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        substitute = _substitute_workspace(tmp_path, [])
        before = _tree_snapshot(substitute)

        real_rename = os.rename
        swapped = {"done": False}

        def swapping_rename(src, dst):
            if src == run_dir and not swapped["done"]:
                swapped["done"] = True
                shutil.rmtree(src)
                shutil.move(str(substitute), src)
            return real_rename(src, dst)

        monkeypatch.setattr(os, "rename", swapping_rename)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert "identity changed after rename" in failure["reason"]
        # The post-rename rejection moved the substitute back untouched:
        # no rebase/refresh reached it, and nothing stayed at the root.
        assert _tree_snapshot(run_dir) == before
        assert not os.path.exists(os.path.join(project_dir, "exp1"))
        assert not os.path.exists(os.path.join(project_dir, "project.json"))
