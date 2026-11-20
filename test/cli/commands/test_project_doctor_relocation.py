"""`ecc project doctor` on a project directory that was renamed, moved or copied (#453)."""

import json
import os
import shutil
from pathlib import Path

import pytest

from test.cli.commands.test_project_doctor import _make_workspace, _manifest, _run_doctor


def _write_tool_config(workspace_dir):
    """Tool configuration with the absolute paths a real workspace keeps."""
    config = workspace_dir / "config"
    config.mkdir()
    (config / "db_ecc.json").write_text(
        json.dumps(
            {
                "INPUT": {
                    "sdc_path": str(workspace_dir / "origin" / "pre_CTS" / "TYP_25_TYPICAL.tcl"),
                    "lef_paths": ["/pdk/cells.lef"],
                }
            }
        )
    )
    (config / "emir_ecc.json").write_text(
        json.dumps({"technology_file_path": str(config / "ics55_synthetic.tech")})
    )


def _tool_config(workspace_dir):
    config = workspace_dir / "config"
    return (
        json.loads((config / "db_ecc.json").read_text())["INPUT"],
        json.loads((config / "emir_ecc.json").read_text())["technology_file_path"],
    )


class TestProjectDoctorMovedProject:
    """A project directory that was renamed, moved or copied (root_path mismatch)."""

    @staticmethod
    def _project(tmp_path, manifest_stubs, name="gcd"):
        project_dir = tmp_path / name
        _make_workspace(project_dir, "ws_0001")
        _write_tool_config(project_dir / "ws_0001")
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        return project_dir

    def test_moved_project_is_reported_and_not_touched(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = self._project(tmp_path, manifest_stubs)
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)
        before = (moved / "project.json").read_bytes()

        rc = _run_doctor(moved)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert records[0] == {
            "doctor": "project",
            "status": "failed",
            "checked": "0",
            "inconsistent": "1",
        }
        assert records[1]["check"] == "moved-project"
        assert records[1]["recorded_root"] == str(project_dir)
        assert records[1]["project"] == str(moved)
        assert "ws_0001" in records[1]["workspaces"]
        assert "ecc project doctor --fix" in records[1]["remediation"]
        assert (moved / "project.json").read_bytes() == before

    def test_fix_relocates_a_moved_project(self, tmp_path, capsys, manifest_stubs, plain_records):
        from chipcompiler.project.manifest import load_manifest

        project_dir = self._project(tmp_path, manifest_stubs)
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        rc = _run_doctor(moved, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert records[0] == {
            "doctor": "project",
            "status": "fixed",
            "checked": "1",
            "inconsistent": "1",
            "fixed": "1",
        }
        assert records[1]["check"] == "moved-project"
        assert records[1]["fix"] == "relocated"
        assert "ws_0001" in records[1]["workspaces"]
        manifest = _manifest(moved)
        assert manifest["root_path"] == str(moved)
        assert manifest["workspaces"][0]["workspace_path"] == os.path.realpath(moved / "ws_0001")
        loaded = load_manifest(str(moved))
        assert [w.workspace_path for w in loaded.workspaces] == [
            os.path.realpath(moved / "ws_0001")
        ]
        workspace = os.path.realpath(moved / "ws_0001")
        assert _tool_config(moved / "ws_0001") == (
            {
                "sdc_path": f"{workspace}/origin/pre_CTS/TYP_25_TYPICAL.tcl",
                "lef_paths": ["/pdk/cells.lef"],
            },
            f"{workspace}/config/ics55_synthetic.tech",
        )

        assert _run_doctor(moved) == 0
        assert plain_records(capsys.readouterr().out) == [
            {"doctor": "project", "status": "ok", "checked": "1", "inconsistent": "0"}
        ]

    def test_fix_makes_a_copy_independent_of_the_original(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = self._project(tmp_path, manifest_stubs)
        original = (project_dir / "project.json").read_bytes()
        copy = tmp_path / "gcd-copy"
        shutil.copytree(project_dir, copy)

        assert _run_doctor(copy, "--fix") == 0
        capsys.readouterr()

        manifest = _manifest(copy)
        assert manifest["root_path"] == str(copy)
        assert manifest["workspaces"][0]["workspace_path"] == os.path.realpath(copy / "ws_0001")
        assert _tool_config(copy / "ws_0001")[1] == (
            f"{os.path.realpath(copy / 'ws_0001')}/config/ics55_synthetic.tech"
        )
        assert (project_dir / "project.json").read_bytes() == original
        assert _tool_config(project_dir / "ws_0001")[1] == (
            f"{project_dir / 'ws_0001'}/config/ics55_synthetic.tech"
        )
        assert _run_doctor(project_dir) == 0

    def test_fix_keeps_the_path_of_an_external_workspace(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        _make_workspace(tmp_path / "elsewhere", "ws_ext")
        _write_tool_config(tmp_path / "elsewhere" / "ws_ext")
        external_config = (
            tmp_path / "elsewhere" / "ws_ext" / "config" / "db_ecc.json"
        ).read_bytes()
        external = {
            "workspace_id": "ws_ext",
            "workspace_path": str(tmp_path / "elsewhere" / "ws_ext"),
            "status": "success",
        }
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001"), external])
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        rc = _run_doctor(moved, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert "ws_0001" in records[1]["workspaces"]
        assert "ws_ext" not in records[1]["workspaces"]
        paths = {w["workspace_id"]: w["workspace_path"] for w in _manifest(moved)["workspaces"]}
        assert paths == {
            "ws_0001": os.path.realpath(moved / "ws_0001"),
            "ws_ext": str(tmp_path / "elsewhere" / "ws_ext"),
        }
        assert (
            tmp_path / "elsewhere" / "ws_ext" / "config" / "db_ecc.json"
        ).read_bytes() == external_config

    def test_fix_follows_a_root_recorded_through_a_symlink(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        # root_path is stored as typed, workspace paths are stored resolved.
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        _make_workspace(real / "gcd", "ws_0001")
        manifest_stubs.write(real / "gcd", [manifest_stubs.entry(real / "gcd", "ws_0001")])
        document = _manifest(real / "gcd")
        document["root_path"] = str(link / "gcd")
        (real / "gcd" / "project.json").write_text(json.dumps(document))
        assert _run_doctor(link / "gcd") == 0
        capsys.readouterr()
        moved = tmp_path / "gcd-moved"
        (real / "gcd").rename(moved)

        assert _run_doctor(moved, "--fix") == 0

        capsys.readouterr()
        assert _manifest(moved)["workspaces"][0]["workspace_path"] == os.path.realpath(
            moved / "ws_0001"
        )

    def test_fix_relocates_and_repairs_other_findings_in_one_call(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        manifest_stubs.write(
            project_dir,
            [
                manifest_stubs.entry(project_dir, "ws_0001"),
                manifest_stubs.entry(project_dir, "gone"),
            ],
        )
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        rc = _run_doctor(moved, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert records[0]["status"] == "fixed"
        assert (records[0]["inconsistent"], records[0]["fixed"]) == ("2", "2")
        assert [record["check"] for record in records[1:]] == ["moved-project", "missing-directory"]
        assert records[2]["workspace"] == os.path.realpath(moved / "gone")
        assert [w["workspace_id"] for w in _manifest(moved)["workspaces"]] == ["ws_0001"]

    def test_failed_workspace_rewrite_leaves_the_manifest_for_a_retry(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = self._project(tmp_path, manifest_stubs)
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)
        broken = moved / "ws_0001" / "config" / "db_ecc.json"
        intact = broken.read_text()
        broken.write_text("{ not json")
        before = (moved / "project.json").read_bytes()

        rc = _run_doctor(moved, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert records[0]["status"] == "failed"
        assert records[1]["fix"] == "failed"
        assert "ws_0001" in records[1]["fix_detail"]
        assert (moved / "project.json").read_bytes() == before

        broken.write_text(intact)
        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()
        assert _manifest(moved)["root_path"] == str(moved)

    def test_fix_does_not_follow_a_config_link_into_the_original(
        self, tmp_path, capsys, manifest_stubs
    ):
        """A link-preserving copy shares the linked directory with the original."""
        project_dir = self._project(tmp_path, manifest_stubs)
        shared = tmp_path / "shared-config"
        (project_dir / "ws_0001" / "config").rename(shared)
        (project_dir / "ws_0001" / "config").symlink_to(shared, target_is_directory=True)
        original = {path.name: path.read_bytes() for path in shared.iterdir()}
        copy = tmp_path / "gcd-copy"
        shutil.copytree(project_dir, copy, symlinks=True)
        assert (copy / "ws_0001" / "config").resolve() == shared

        assert _run_doctor(copy, "--fix") == 0
        capsys.readouterr()

        assert _manifest(copy)["root_path"] == str(copy)
        assert {path.name: path.read_bytes() for path in shared.iterdir()} == original
        assert _run_doctor(project_dir) == 0

    def test_fix_follows_a_config_link_that_stays_inside_the_project(
        self, tmp_path, capsys, manifest_stubs
    ):
        project_dir = self._project(tmp_path, manifest_stubs)
        inside = project_dir / "shared-config"
        (project_dir / "ws_0001" / "config").rename(inside)
        (project_dir / "ws_0001" / "config").symlink_to(
            os.path.join("..", "shared-config"), target_is_directory=True
        )
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()

        sdc_path = _tool_config(moved / "ws_0001")[0]["sdc_path"]
        assert sdc_path == f"{os.path.realpath(moved)}/ws_0001/origin/pre_CTS/TYP_25_TYPICAL.tcl"

    def test_interrupted_fix_of_a_copy_inside_the_original_can_be_repeated(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        """The copy lies below the root it records: rebased paths still start with it."""
        project_dir = self._project(tmp_path, manifest_stubs)
        staging = tmp_path / "staging"
        shutil.copytree(project_dir, staging)
        copy = project_dir / "copy"
        staging.rename(copy)
        workspace = copy / "ws_0001"
        expected = f"{os.path.realpath(workspace)}/origin/pre_CTS/TYP_25_TYPICAL.tcl"
        broken = workspace / "config" / "emir_ecc.json"
        intact = broken.read_text()
        broken.write_text("{ not json")
        before = (workspace / "config" / "db_ecc.json").read_bytes()

        assert _run_doctor(copy, "--fix") == 1
        capsys.readouterr()
        # Nothing is written while one file cannot be read.
        assert (workspace / "config" / "db_ecc.json").read_bytes() == before

        broken.write_text(intact)
        assert _run_doctor(copy, "--fix") == 0
        assert _tool_config(workspace)[0]["sdc_path"] == expected
        # A repair on top of rewritten paths leaves them where they are.
        manifest = _manifest(copy)
        manifest["root_path"] = str(project_dir)
        (copy / "project.json").write_text(json.dumps(manifest))
        assert _run_doctor(copy, "--fix") == 0
        capsys.readouterr()
        assert _tool_config(workspace)[0]["sdc_path"] == expected
        assert _manifest(copy)["workspaces"][0]["workspace_path"] == os.path.realpath(workspace)

    def test_fix_relocates_a_workspace_registered_with_a_relative_path(
        self, tmp_path, capsys, manifest_stubs
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        _write_tool_config(project_dir / "ws_0001")
        entry = manifest_stubs.entry(project_dir, "ws_0001")
        entry["workspace_path"] = "ws_0001"
        manifest_stubs.write(project_dir, [entry])
        assert _run_doctor(project_dir) == 0
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()

        workspace = os.path.realpath(moved / "ws_0001")
        inputs, technology = _tool_config(moved / "ws_0001")
        assert inputs["sdc_path"] == f"{workspace}/origin/pre_CTS/TYP_25_TYPICAL.tcl"
        assert technology == f"{workspace}/config/ics55_synthetic.tech"
        manifest = _manifest(moved)
        assert manifest["root_path"] == str(moved)
        # The registration stays as it was written.
        assert manifest["workspaces"][0]["workspace_path"] == "ws_0001"
        assert _run_doctor(moved) == 0

    def test_fix_reads_the_configuration_under_the_workspace_lock(
        self, tmp_path, capsys, manifest_stubs, monkeypatch
    ):
        """Nobody can change a configuration between its read and its rewrite."""
        import threading

        from chipcompiler.project import consistency
        from chipcompiler.utility.workspace_lock import workspace_lock

        project_dir = self._project(tmp_path, manifest_stubs)
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)
        planner = consistency._planned_config_rewrites
        seen = []

        def planned(workspace_dir, *arguments):
            def probe() -> None:
                try:
                    with workspace_lock(Path(workspace_dir), blocking=False):
                        seen.append("free")
                except BlockingIOError:
                    seen.append("held")

            thread = threading.Thread(target=probe)
            thread.start()
            thread.join()
            return planner(workspace_dir, *arguments)

        monkeypatch.setattr(consistency, "_planned_config_rewrites", planned)

        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()

        assert seen == ["held"]
        assert _manifest(moved)["root_path"] == str(moved)

    def test_fix_leaves_a_busy_workspace_and_the_manifest_alone(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        import threading

        from chipcompiler.utility.workspace_lock import workspace_lock

        project_dir = self._project(tmp_path, manifest_stubs)
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)
        before = (moved / "project.json").read_bytes()
        config = (moved / "ws_0001" / "config" / "db_ecc.json").read_bytes()
        held, release = threading.Event(), threading.Event()

        def hold() -> None:
            with workspace_lock(moved / "ws_0001"):
                held.set()
                release.wait(3)

        holder = threading.Thread(target=hold)
        holder.start()
        assert held.wait(10)
        try:
            rc = _run_doctor(moved, "--fix")
        finally:
            release.set()
            holder.join()

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert "busy" in records[1]["fix_detail"]
        assert (moved / "project.json").read_bytes() == before
        assert (moved / "ws_0001" / "config" / "db_ecc.json").read_bytes() == config

    def test_fix_rebases_the_paths_base_design_keeps_inside_the_project(
        self, tmp_path, capsys, manifest_stubs
    ):
        """A PDK kept in the project moves with it; a PDK elsewhere stays where it is."""
        project_dir = self._project(tmp_path, manifest_stubs)
        assert _manifest(project_dir)["base_design"]["pdk_root"] == str(project_dir / "pdk")
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()

        base_design = _manifest(moved)["base_design"]
        assert base_design["pdk_root"] == f"{os.path.realpath(moved)}/pdk"
        assert os.path.isdir(base_design["pdk_root"])
        assert base_design["rtl_list"] == ["rtl/gcd.v"]

        external = tmp_path / "external-pdk"
        external.mkdir()
        manifest = _manifest(moved)
        manifest["base_design"]["pdk_root"] = str(external)
        (moved / "project.json").write_text(json.dumps(manifest))
        again = tmp_path / "gcd-again"
        moved.rename(again)

        assert _run_doctor(again, "--fix") == 0
        capsys.readouterr()

        assert _manifest(again)["base_design"]["pdk_root"] == str(external)

    def test_fix_relocates_a_workspace_directory_that_is_not_registered(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        """The repair registers it afterwards; its configuration has to be right by then."""
        project_dir = self._project(tmp_path, manifest_stubs)
        _make_workspace(project_dir, "ws_0002")
        _write_tool_config(project_dir / "ws_0002")
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()

        for name in ("ws_0001", "ws_0002"):
            workspace = os.path.realpath(moved / name)
            inputs, technology = _tool_config(moved / name)
            assert inputs["sdc_path"] == f"{workspace}/origin/pre_CTS/TYP_25_TYPICAL.tcl"
            assert technology == f"{workspace}/config/ics55_synthetic.tech"
        assert {entry["workspace_id"] for entry in _manifest(moved)["workspaces"]} == {
            "ws_0001",
            "ws_0002",
        }
        assert _run_doctor(moved) == 0

    def test_fix_detaches_a_copy_from_the_runs_of_the_original(
        self, tmp_path, capsys, manifest_stubs
    ):
        """The copy must not keep the run registration of the original's workspace."""
        project_dir = self._project(tmp_path, manifest_stubs)
        manifest = _manifest(project_dir)
        manifest["runtime_processes"] = {
            "ws_0001": {"run_id": "original-run", "workspace_path": "ws_0001"},
            "elsewhere": {"run_id": "external-run", "workspace_path": "/external/ws"},
        }
        (project_dir / "project.json").write_text(json.dumps(manifest))
        original = (project_dir / "project.json").read_bytes()
        copy = tmp_path / "gcd-copy"
        shutil.copytree(project_dir, copy)

        assert _run_doctor(copy, "--fix") == 0
        capsys.readouterr()

        processes = _manifest(copy)["runtime_processes"]
        assert "ws_0001" not in processes
        assert processes["elsewhere"]["run_id"] == "external-run"
        assert (project_dir / "project.json").read_bytes() == original

    def test_fix_rebases_the_pdk_root_a_workspace_keeps(self, tmp_path, capsys, manifest_stubs):
        """The workspace loader validates the PDK root stored in home/params.toml."""
        from chipcompiler.data.parameter import load_parameter, save_parameter

        project_dir = self._project(tmp_path, manifest_stubs)
        params = project_dir / "ws_0001" / "home" / "params.toml"
        parameters = load_parameter(params)
        parameters.data["pdk_root"] = str(project_dir / "pdk")
        assert save_parameter(parameters)
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()

        data = load_parameter(moved / "ws_0001" / "home" / "params.toml").data
        assert data["pdk_root"] == f"{os.path.realpath(moved)}/pdk"
        assert data["design"] == "gcd"
        assert data["_flow"] == {"start": "synthesis", "end": "harden"}

    def test_fix_keeps_generated_configs_unmodified_for_refresh(
        self, tmp_path, capsys, manifest_stubs
    ):
        """A rewritten generated config is not a hand edit; an earlier edit stays one."""
        from chipcompiler.data.workspace.config_manifest import (
            derived_config_manifest_path,
            modified_derived_configs,
        )
        from chipcompiler.utility import file_digest

        project_dir = self._project(tmp_path, manifest_stubs)
        config = project_dir / "ws_0001" / "config"
        records = {}
        for name in ("db_ecc.json", "emir_ecc.json"):
            digest = file_digest(config / name)
            assert digest is not None
            records[name] = {"sha256": digest[0], "size": digest[1]}
        derived_config_manifest_path(project_dir / "ws_0001").write_text(
            json.dumps({"files": records})
        )
        # emir_ecc.json was edited by hand before the move.
        emir = json.loads((config / "emir_ecc.json").read_text())
        emir["note"] = "edited"
        (config / "emir_ecc.json").write_text(json.dumps(emir))
        assert modified_derived_configs(project_dir / "ws_0001") == ["emir_ecc.json"]
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()

        assert modified_derived_configs(moved / "ws_0001") == ["emir_ecc.json"]
        sdc_path = _tool_config(moved / "ws_0001")[0]["sdc_path"]
        assert sdc_path.startswith(os.path.realpath(moved))

    def test_fix_settles_an_interrupted_configuration_update_first(
        self, tmp_path, capsys, manifest_stubs
    ):
        """A pending backup would otherwise be restored over the repair by the next load."""
        from chipcompiler.data.workspace import transaction as module

        project_dir = self._project(tmp_path, manifest_stubs)
        workspace = project_dir / "ws_0001"
        config = workspace / "config" / "db_ecc.json"
        pending = module.WorkspaceFileTransaction.begin(workspace, [config])
        half_written = json.loads(config.read_text())
        half_written["INPUT"]["half_written"] = True
        config.write_text(json.dumps(half_written))
        # The process that began the update is gone without committing.
        pending.lock.close()
        module._ACTIVE.discard(workspace.resolve())
        assert (workspace / "home" / module._BACKUP_NAME).exists()
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()

        assert not (moved / "ws_0001" / "home" / module._BACKUP_NAME).exists()
        inputs = _tool_config(moved / "ws_0001")[0]
        assert "half_written" not in inputs
        assert inputs["sdc_path"].startswith(os.path.realpath(moved))

    def test_fix_rebases_absolute_ecc_toml_paths_into_the_former_location(
        self, tmp_path, capsys, manifest_stubs
    ):
        project_dir = self._project(tmp_path, manifest_stubs)
        (project_dir / "pdk").mkdir(exist_ok=True)
        external = tmp_path / "external.sdc"
        external.write_text("# sdc\n")
        (project_dir / "ecc.toml").write_text(
            "# keep this comment\n"
            "[design]\n"
            'name = "gcd"\n'
            f'rtl = ["rtl/gcd.v", "{project_dir}/rtl/extra.v"]\n'
            f'sdc = "{external}"\n'
            "\n[pdk]\n"
            'name = "ics55"\n'
            f'root = "{project_dir}/pdk"\n'
        )
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        assert _run_doctor(moved, "--fix") == 0
        capsys.readouterr()

        import tomllib

        text = (moved / "ecc.toml").read_text()
        config = tomllib.loads(text)
        new_root = os.path.realpath(moved)
        assert config["pdk"]["root"] == f"{new_root}/pdk"
        assert config["design"]["rtl"] == ["rtl/gcd.v", f"{new_root}/rtl/extra.v"]
        assert config["design"]["sdc"] == str(external)
        assert text.startswith("# keep this comment\n")

    def test_loader_names_the_repair_for_a_moved_project(self, tmp_path, manifest_stubs):
        from chipcompiler.project.manifest import ManifestError, load_manifest

        project_dir = self._project(tmp_path, manifest_stubs)
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        with pytest.raises(ManifestError, match="does not match .*ecc project doctor --fix"):
            load_manifest(str(moved))
