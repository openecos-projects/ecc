import json
import os
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


def _records(capsys):
    return json.loads(capsys.readouterr().out)["records"]


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


def _substitute_workspace(tmp_path, steps):
    """A real directory (with a keep file) standing by to replace a planned
    source after preview."""
    substitute = tmp_path / "substitute"
    home = substitute / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(json.dumps({"steps": steps}))
    (substitute / "keep.txt").write_text("precious\n")
    return substitute


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


class TestRunMigrationRace:
    """A run whose context was built before a concurrent migration must not
    act on the stale legacy layout: the locked dispatch revalidates the
    project state and refuses, instead of recreating runs/<id> next to the
    moved, registered workspace."""

    def test_stale_legacy_run_does_not_recreate_migrated_workspace(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
        monkeypatch,
    ):

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])

        created = []

        def fake_create_workspace(**kwargs):
            created.append(kwargs)
            return None

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create_workspace)

        # A legacy project is refused BEFORE any locked decision, so no
        # stale-classification window exists: the run never mutates the
        # tree, and the legacy workspace stays exactly where it was.
        rc = cli_main.run(["run", "--project", project_dir, "--workspace", "exp1", "--json"])

        assert rc != 0
        records = _records(capsys)
        assert any(r.get("error") == "legacy_workspace_migration_required" for r in records)
        assert any(
            r.get("warning") == "legacy_layout_detected" and "ecc migrate" in r.get("migrate", "")
            for r in records
        )
        assert os.path.isfile(os.path.join(project_dir, "runs", "exp1", "home", "flow.json"))
        assert not os.path.exists(os.path.join(project_dir, "exp1"))
        assert created == []


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
        import chipcompiler.cli.project.migrate_plan as migrate_module

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


class TestRollbackMalformedState:
    """Rollback re-reads the same state files after a failed content phase;
    a malformed home.json downgrades the rebase to a warning — it never
    escapes the rollback as an uncaught exception."""

    @pytest.mark.parametrize("payload", [b"\xff", b"[]"], ids=["undecodable", "not_an_object"])
    def test_corrupt_home_json_does_not_crash_rollback(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
        monkeypatch,
        payload,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        target = os.path.join(project_dir, "exp1")

        def corrupting_refresh(workspace):
            # The forward load heals home.json, so the rollback's re-read
            # only sees a malformed file when it turns corrupt mid-flight.
            Path(target, "home", "home.json").write_bytes(payload)
            raise RuntimeError("boom")

        monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", corrupting_refresh)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        assert any(r.get("error") == "migration_failed" for r in records)
        # The move was rolled back; nothing was registered.
        assert os.path.isfile(os.path.join(project_dir, "runs", "exp1", "home", "flow.json"))
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_manifest_lock_failure_rolls_back_the_moves(
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
        manifest_stubs.write(Path(project_dir), [])
        # The registration's lock cannot be taken: update_manifest degrades
        # to False and the moved workspace rolls back instead of stranding.
        os.mkdir(os.path.join(project_dir, ".manifest.lock"))

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        assert any(r.get("error") == "manifest_update_failed" for r in records)
        assert any(r.get("error") == "migration_rolled_back" for r in records)
        assert os.path.isfile(os.path.join(project_dir, "runs", "exp1", "home", "flow.json"))
        manifest = json.loads(Path(project_dir, "project.json").read_text())
        assert manifest["workspaces"] == []


def _hold_workspace_lock_briefly(workspace_dir, seconds=0.4):
    """Hold the sibling <workspace>.lock in a thread; returns (thread, released)."""
    import fcntl
    import threading
    import time

    lock_path = os.path.join(
        os.path.dirname(workspace_dir), os.path.basename(workspace_dir) + ".lock"
    )
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
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


class TestMigrationExecutionLock:
    def test_migrate_waits_for_an_active_workspace_execution(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        """An explicit --workspace run holds the sibling lock; the migration
        moves the workspace only after the run releases it."""
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        thread, released = _hold_workspace_lock_briefly(os.path.join(project_dir, "runs", "exp1"))

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        thread.join()
        assert rc == 0
        assert released.is_set()
        assert os.path.isfile(os.path.join(project_dir, "exp1", "home", "flow.json"))

    def test_rollback_with_unrestored_content_reports_incomplete(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
        manifest_stubs,
        monkeypatch,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        manifest_stubs.write(Path(project_dir), [])
        target = os.path.join(project_dir, "exp1")

        def corrupting_update(project_dir_arg, mutator):
            # Registration fails AND the moved workspace's home.json is now
            # undecodable: the rollback moves it back but cannot reverse the
            # rebase — that is incomplete, not "rolled back".
            Path(target, "home", "home.json").write_bytes(b"\xff")
            return False

        monkeypatch.setattr("chipcompiler.cli.project.migrate.update_manifest", corrupting_update)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        assert any(r.get("error") == "migration_rollback_incomplete" for r in records)
        assert not any(r.get("error") == "migration_rolled_back" for r in records)
        assert os.path.isfile(os.path.join(project_dir, "runs", "exp1", "home", "flow.json"))
        manifest = json.loads(Path(project_dir, "project.json").read_text())
        assert manifest["workspaces"] == []
