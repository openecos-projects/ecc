import json
import os
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


def _records(capsys):
    return json.loads(capsys.readouterr().out)["records"]


def _manifest(project_dir):
    with open(os.path.join(project_dir, "project.json")) as f:
        return json.load(f)


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
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        import shutil

        import chipcompiler.cli.project.migrate as migrate_module

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
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
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        import shutil

        import chipcompiler.cli.project.migrate as migrate_module

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
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
        create_legacy_workspace,
    ):
        import chipcompiler.cli.project.migrate as migrate_module

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])
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

    def test_substitution_reaching_the_move_is_rejected_after_it(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        import shutil

        import chipcompiler.cli.project.migrate_fs as migrate_fs

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        substitute = _substitute_workspace(tmp_path, [])
        before = _tree_snapshot(substitute)

        real_move = migrate_fs.move_noreplace
        swapped = {"done": False}

        def swapping_move(src_fd, src_name, dst_fd, dst_name):
            if src_name == "exp1" and not swapped["done"]:
                swapped["done"] = True
                shutil.rmtree(run_dir)
                shutil.move(str(substitute), run_dir)
            return real_move(src_fd, src_name, dst_fd, dst_name)

        monkeypatch.setattr(migrate_fs, "move_noreplace", swapping_move)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert "identity changed after rename" in failure["reason"]
        # The post-move rejection moved the substitute back untouched:
        # no rebase/refresh reached it, and nothing stayed at the root.
        assert _tree_snapshot(run_dir) == before
        assert not os.path.exists(os.path.join(project_dir, "exp1"))
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_container_replacement_after_validation_refuses_batch(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        import shutil

        import chipcompiler.cli.project.migrate as migrate_module

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        replacement_runs = tmp_path / "replacement-runs"
        (replacement_runs / "exp1").mkdir(parents=True)
        replacement_before = _tree_snapshot(replacement_runs)

        real_plan = migrate_module.plan_migration
        original_runs = os.path.join(project_dir, "runs")

        def swapping_plan(project_dir_arg):
            plan = real_plan(project_dir_arg)
            # Swap the whole confirmed runs/ container for a different one.
            os.rename(original_runs, str(tmp_path / "original-runs"))
            shutil.move(str(replacement_runs), original_runs)
            return plan

        monkeypatch.setattr(migrate_module, "plan_migration", swapping_plan)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert failure["reason"] == "runs/ container changed after preview"
        # The batch was refused before any move: nothing at the root, no
        # manifest, and the replacement container is untouched.
        assert not os.path.exists(os.path.join(project_dir, "exp1"))
        assert not os.path.exists(os.path.join(project_dir, "project.json"))
        assert _tree_snapshot(original_runs) == replacement_before

    def test_reappeared_source_is_never_touched_by_rollback(
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
        target = os.path.join(project_dir, "exp1")
        replacement_home_json = {"flow": os.path.join(run_dir, "home", "flow.json")}

        def failing_refresh(workspace):
            # A rebase failure AFTER a replacement appeared at the source.
            (Path(run_dir) / "home").mkdir(parents=True)
            (Path(run_dir) / "home" / "home.json").write_text(json.dumps(replacement_home_json))
            raise RuntimeError("boom")

        monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", failing_refresh)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert "rollback incomplete" in failure["reason"]
        # The replacement was NEVER reverse-rebased or refreshed, and the
        # honestly-reported moved workspace stays at the root untouched.
        current = json.loads((Path(run_dir) / "home" / "home.json").read_text())
        assert current == replacement_home_json
        moved_home = json.loads((Path(target) / "home" / "home.json").read_text())
        assert moved_home["flow"] == os.path.join(target, "home", "flow.json")
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_target_replacement_before_move_back_is_skipped(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        import shutil

        import chipcompiler.cli.project.migrate_fs as migrate_fs

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        target = os.path.join(project_dir, "exp1")
        substitute = _substitute_workspace(tmp_path / "sub-a", [])
        third = _substitute_workspace(tmp_path / "sub-b", [])
        third_before = _tree_snapshot(third)

        real_move = migrate_fs.move_noreplace
        real_screen = migrate_fs._unsafe_workspace_source
        swapped = {"done": False}

        def swapping_move(src_fd, src_name, dst_fd, dst_name):
            if src_name == "exp1" and not swapped["done"]:
                swapped["done"] = True
                shutil.rmtree(run_dir)
                shutil.move(str(substitute), run_dir)
            return real_move(src_fd, src_name, dst_fd, dst_name)

        def swapping_screen(source):
            # A third party replaces the just-moved object before the
            # identity-bound move-back can run.
            if source == target:
                shutil.rmtree(target)
                shutil.move(str(third), target)
            return real_screen(source)

        monkeypatch.setattr(migrate_fs, "move_noreplace", swapping_move)
        monkeypatch.setattr(migrate_fs, "_unsafe_workspace_source", swapping_screen)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert "rollback incomplete" in failure["reason"]
        # The move-back refused to move the wrong object: the third-party
        # directory stays at the root untouched, and no manifest was written.
        assert _tree_snapshot(target) == third_before
        assert not os.path.exists(run_dir)
        assert not os.path.exists(os.path.join(project_dir, "project.json"))


class TestMigrationFailLoud:
    """Fail-loud detection: a replaced/removed workspace is never mutated or
    registered — it is reported with the exact paths for manual resolution."""

    def test_replaced_before_content_phase_is_refused(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        import shutil

        import chipcompiler.cli.project.migrate_fs as migrate_fs

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        target = os.path.join(project_dir, "exp1")
        third = _substitute_workspace(tmp_path / "sub", [])
        third_before = _tree_snapshot(third)

        real_screen = migrate_fs._unsafe_workspace_source

        def swapping_screen(source):
            # A third party replaces the moved workspace right after the
            # post-move screen, before any content write.
            if source == target:
                shutil.rmtree(target)
                shutil.move(str(third), target)
            return real_screen(source)

        monkeypatch.setattr(migrate_fs, "_unsafe_workspace_source", swapping_screen)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert "replaced during migration" in failure["reason"]
        # The pre-content gate fired: the replacement was never loaded or
        # registered, and sits untouched for manual inspection.
        assert _tree_snapshot(target) == third_before
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_replaced_during_content_phase_is_never_registered(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        import shutil

        import chipcompiler.data

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        target = os.path.join(project_dir, "exp1")
        # The replacement must be refreshable so the flow reaches the
        # registration gate: a real workspace at a sibling location.
        third = create_legacy_workspace(
            str(tmp_path / "sibling"), pdk_root, "exp1", ["Success", "Success"]
        )

        real_refresh = chipcompiler.data.refresh_workspace_config

        def swapping_refresh(workspace):
            # A third party replaces the moved workspace mid-content-phase.
            shutil.rmtree(target)
            shutil.move(str(third), target)
            return real_refresh(workspace)

        monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", swapping_refresh)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        (failure,) = [r for r in records if r.get("error") == "migration_failed"]
        assert "NOT registered" in failure["reason"]
        # The registration gate caught the identity change: project.json was
        # never written, and the replacement stays unregistered at the root.
        assert not os.path.exists(os.path.join(project_dir, "project.json"))
        assert os.path.isdir(target)
        assert not os.path.exists(os.path.join(project_dir, "runs", "exp1"))

    def test_missing_target_with_unproven_source_is_incomplete_rollback(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        create_legacy_workspace,
    ):
        import shutil

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        target = os.path.join(project_dir, "exp1")
        replacement_home_json = {"flow": os.path.join(run_dir, "home", "flow.json")}

        def failing_refresh(workspace):
            # The moved target disappears and an unconfirmed replacement
            # appears at the source before the failure surfaces.
            shutil.rmtree(target)
            (Path(run_dir) / "home").mkdir(parents=True)
            (Path(run_dir) / "home" / "home.json").write_text(json.dumps(replacement_home_json))
            raise RuntimeError("boom")

        monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", failing_refresh)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert "rollback incomplete" in failure["reason"]
        # The unconfirmed replacement was never reverse-rebased.
        current = json.loads((Path(run_dir) / "home" / "home.json").read_text())
        assert current == replacement_home_json
        assert not os.path.exists(os.path.join(project_dir, "project.json"))


def _hold_lock_briefly(project_dir, seconds=0.4):
    """Hold the project migration lock exclusively in a thread; returns
    (thread, released_event) so callers can assert the CLI waited."""
    import fcntl
    import threading
    import time

    fd = os.open(os.path.join(project_dir, ".migrate.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    released = threading.Event()

    def release():
        time.sleep(seconds)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        released.set()

    thread = threading.Thread(target=release, daemon=True)
    thread.start()
    return thread, released


class TestMigrationProjectLock:
    """The .migrate.lock serializes cooperating writers: a migration and a
    run creation in the same project wait for each other instead of racing."""

    def test_second_migrate_waits_for_the_first_lock(
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
        thread, released = _hold_lock_briefly(project_dir)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        thread.join()
        assert rc == 0
        # The migrate returned only AFTER the holder released: it blocked
        # on the shared lock rather than racing or failing.
        assert released.is_set()
        assert os.path.isfile(os.path.join(project_dir, "exp1", "home", "flow.json"))

    def test_run_creation_waits_for_migration_lock(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        thread, released = _hold_lock_briefly(project_dir)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        thread.join()
        assert rc == 0
        assert released.is_set()
        assert flow_mocks.capture["create_kwargs"]["directory"] == os.path.join(
            project_dir, "default"
        )


class TestDestinationBinding:
    def test_retargeted_project_symlink_is_refused_before_any_move(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
        monkeypatch,
    ):
        import chipcompiler.cli.project.migrate as migrate_module

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        link_dir = tmp_path / "links"
        link_dir.mkdir()
        link = str(link_dir / "project_link")
        os.symlink(project_dir, link)
        other = tmp_path / "other_project"
        other.mkdir()

        real_plan = migrate_module.plan_migration

        def retargeting_plan(project_dir_arg):
            plan = real_plan(project_dir_arg)
            # The project symlink is retargeted after the preview.
            os.unlink(link)
            os.symlink(other, link)
            return plan

        monkeypatch.setattr(migrate_module, "plan_migration", retargeting_plan)

        rc = cli_main.run(["migrate", "--project", link, "--yes", "--json"])

        assert rc != 0
        (failure,) = [r for r in _records(capsys) if r.get("error") == "migration_failed"]
        assert failure["reason"] == "project directory changed after preview"
        # Nothing was moved into the retargeted destination and nothing was
        # written anywhere: the real workspace stays under runs/.
        assert os.path.isfile(os.path.join(project_dir, "runs", "exp1", "home", "flow.json"))
        assert not (other / "exp1").exists()
        assert not os.path.exists(os.path.join(project_dir, "project.json"))
        assert not (other / "project.json").exists()
