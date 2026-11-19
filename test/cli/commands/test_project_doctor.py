"""``ecc project doctor``: manifest ↔ workspace-directory consistency.

Fixtures build manifest-only projects (no ecc.toml) through the shared
``manifest_stubs`` scaffolding; workspace directories carry the real
``home/flow.json`` + ``home/params.toml`` pair so inspection validates
workspace files independently of cached manifest execution fields.
"""

import json
import os
import shutil

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter import Parameters, save_parameter
from test.flow_fixture import step_fields


def _make_workspace(project_dir, name, *, state="Success", start="synthesis", end="harden"):
    """A consistent workspace directory: range Synthesis..Harden, patch {}."""
    home = project_dir / name / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "steps": [
                    {
                        "name": start,
                        "tool": "yosys",
                        "state": state,
                        **step_fields(start, "yosys"),
                    }
                ],
            }
        )
    )
    assert save_parameter(
        Parameters(
            path=home / "params.toml",
            data={
                "pdk": "ics55",
                "design": "gcd",
                "top_module": "gcd",
                "clock": "clk",
                "frequency_max": 100,
                "_flow": {"start": start, "end": end},
            },
        )
    )


def _run_doctor(project_dir, *extra):
    return cli_main.run(["project", "doctor", "--project", str(project_dir), "--plain", *extra])


def _manifest(project_dir):
    return json.loads((project_dir / "project.json").read_text())


class TestProjectDoctorReport:
    @pytest.mark.parametrize("extra", [(), ("--fix",)])
    def test_cached_execution_fields_do_not_require_manifest_repair(
        self, tmp_path, capsys, manifest_stubs, plain_records, extra
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0004")
        entry = {
            **manifest_stubs.entry(project_dir, "ws_0004", status="not_started"),
            "start_step": "placement",
            "parameter_patch": {"frequency_max": {"from": 100, "to": 125}},
        }
        manifest_stubs.write(project_dir, [entry])
        before = (project_dir / "project.json").read_bytes()

        assert _run_doctor(project_dir, *extra) == 0
        assert plain_records(capsys.readouterr().out) == [
            {"doctor": "project", "status": "ok", "checked": "1", "inconsistent": "0"}
        ]
        assert (project_dir / "project.json").read_bytes() == before

    def test_consistent_project_passes_and_writes_nothing(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        before = (project_dir / "project.json").read_bytes()

        rc = _run_doctor(project_dir)

        assert rc == 0
        assert plain_records(capsys.readouterr().out) == [
            {"doctor": "project", "status": "ok", "checked": "1", "inconsistent": "0"}
        ]
        assert (project_dir / "project.json").read_bytes() == before

    def test_missing_directory_is_reported(self, tmp_path, capsys, manifest_stubs, plain_records):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        manifest_stubs.write(
            project_dir,
            [
                manifest_stubs.entry(project_dir, "ghost"),
                manifest_stubs.entry(project_dir, "ws_0001"),
            ],
        )

        rc = _run_doctor(project_dir)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert records[0]["inconsistent"] == "1"
        assert records[1]["check"] == "missing-directory"
        assert records[1]["workspace_id"] == "ghost"
        assert records[1]["workspace"] == str(project_dir / "ghost")

    def test_unregistered_directory_is_reported(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0002")
        manifest_stubs.write(project_dir, [])

        rc = _run_doctor(project_dir)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert records[0]["checked"] == "0"
        assert records[0]["inconsistent"] == "1"
        assert records[1]["check"] == "unregistered-directory"
        assert records[1]["workspace_id"] == "ws_0002"

    def test_uninspectable_directory_is_reported(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        (project_dir / "ws_0001").mkdir(parents=True)
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = _run_doctor(project_dir)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert records[1]["check"] == "invalid-workspace"
        assert "workspace facts unreadable" in records[1]["detail"]

    def test_archived_entry_keeps_lifecycle_but_checks_existence(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        archived = {
            **manifest_stubs.entry(project_dir, "ws_0001", status="archived"),
            "start_step": "placement",
        }
        missing_archived = manifest_stubs.entry(project_dir, "ghost", status="archived")
        manifest_stubs.write(project_dir, [archived, missing_archived])

        rc = _run_doctor(project_dir)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert [r["check"] for r in records[1:]] == ["missing-directory"]
        assert records[1]["workspace_id"] == "ghost"

    def test_cached_running_entry_still_checks_existence(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        running = {
            **manifest_stubs.entry(project_dir, "ws_0001", status="running"),
            "start_step": "placement",
            "parameter_patch": {"frequency_max": {"from": 100, "to": 125}},
        }
        missing_running = manifest_stubs.entry(project_dir, "ghost", status="running")
        manifest_stubs.write(project_dir, [running, missing_running])

        rc = _run_doctor(project_dir)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert [r["check"] for r in records[1:]] == ["missing-directory"]
        assert records[1]["workspace_id"] == "ghost"

    def test_stale_runtime_entry_does_not_hide_unreadable_workspace(
        self, tmp_path, capsys, manifest_stubs, plain_records, monkeypatch
    ):
        project_dir = tmp_path / "gcd"
        (project_dir / "ws_0001").mkdir(parents=True)
        entry = manifest_stubs.entry(project_dir, "ws_0001")
        manifest_stubs.write(
            project_dir,
            [entry],
            runtime_processes={"ws_0001": {"run_id": "stale"}},
        )
        monkeypatch.setattr(
            "chipcompiler.project.runtime_processes.identity_is_live",
            lambda _entry: False,
        )

        assert _run_doctor(project_dir) == 1
        records = plain_records(capsys.readouterr().out)
        assert records[1]["check"] == "invalid-workspace"

    def test_project_without_manifest_is_an_error(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()

        rc = _run_doctor(project_dir)

        assert rc == 1
        assert plain_records(capsys.readouterr().out)[0]["error"] == "missing_manifest"


class TestProjectDoctorFix:
    def test_fix_removes_missing_directory_entry_and_nulls_references(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        surviving = {
            **manifest_stubs.entry(project_dir, "ws_0001"),
            "source_workspace_id": "ghost",
        }
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ghost"), surviving],
            qor_baseline={"workspace_id": "ghost", "reason": "Project QoR baseline"},
            best_workspace={"workspace_id": "ghost"},
        )

        rc = _run_doctor(project_dir, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert records[0]["status"] == "fixed"
        assert records[1]["check"] == "missing-directory"
        assert records[1]["fix"] == "removed"
        manifest = _manifest(project_dir)
        assert [w["workspace_id"] for w in manifest["workspaces"]] == ["ws_0001"]
        assert manifest["qor_baseline"] is None
        assert manifest["best_workspace"] is None
        assert manifest["workspaces"][0]["source_workspace_id"] is None

    def test_fix_registers_unregistered_directory(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0002")
        manifest_stubs.write(project_dir, [])

        rc = _run_doctor(project_dir, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert records[0]["status"] == "fixed"
        assert records[1]["check"] == "unregistered-directory"
        assert records[1]["fix"] == "registered"
        (entry,) = _manifest(project_dir)["workspaces"]
        assert entry["workspace_id"] == "ws_0002"
        assert entry["workspace_path"] == str(project_dir / "ws_0002")
        assert entry["start_step"] == "synthesis"
        assert entry["end_step"] == "harden"
        assert entry["status"] == "success"

        capsys.readouterr()
        assert _run_doctor(project_dir) == 0
        assert plain_records(capsys.readouterr().out)[0]["status"] == "ok"

    def test_fix_preserves_uninspectable_workspace_registration(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        (project_dir / "ws_0001").mkdir(parents=True)
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        before = (project_dir / "project.json").read_bytes()

        rc = _run_doctor(project_dir, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert records[1]["check"] == "invalid-workspace"
        assert records[1]["fix"] == "failed"
        assert "restore the workspace files" in records[1]["fix_detail"]
        assert (project_dir / "project.json").read_bytes() == before

    def test_fix_on_consistent_project_changes_nothing(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        before = (project_dir / "project.json").read_bytes()

        rc = _run_doctor(project_dir, "--fix")

        assert rc == 0
        assert plain_records(capsys.readouterr().out) == [
            {"doctor": "project", "status": "ok", "checked": "1", "inconsistent": "0"}
        ]
        assert (project_dir / "project.json").read_bytes() == before

    def test_fix_is_idempotent(self, tmp_path, capsys, manifest_stubs, plain_records):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        _make_workspace(project_dir, "ws_0002")
        entry = {**manifest_stubs.entry(project_dir, "ws_0001", status="failed")}
        manifest_stubs.write(project_dir, [entry, manifest_stubs.entry(project_dir, "ghost")])

        assert _run_doctor(project_dir, "--fix") == 0
        capsys.readouterr()
        after_fix = (project_dir / "project.json").read_bytes()

        assert _run_doctor(project_dir, "--fix") == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0]["status"] == "ok"
        assert (project_dir / "project.json").read_bytes() == after_fix


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

    def test_loader_names_the_repair_for_a_moved_project(self, tmp_path, manifest_stubs):
        from chipcompiler.project.manifest import ManifestError, load_manifest

        project_dir = self._project(tmp_path, manifest_stubs)
        moved = tmp_path / "gcd-moved"
        project_dir.rename(moved)

        with pytest.raises(ManifestError, match="does not match .*ecc project doctor --fix"):
            load_manifest(str(moved))
