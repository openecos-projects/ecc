"""``ecc project doctor``: manifest ↔ workspace-directory consistency.

Fixtures build manifest-only projects (no ecc.toml) through the shared
``manifest_stubs`` scaffolding; workspace directories carry the real
``home/flow.json`` + ``home/params.toml`` pair so inspection derives the
same fields a registration would write.
"""

import json

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter import Parameters, save_parameter


def _make_workspace(project_dir, name, *, state="Success", start="Synthesis", end="Harden"):
    """A consistent workspace directory: range Synthesis..Harden, patch {}."""
    home = project_dir / name / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps({"steps": [{"name": start, "tool": "yosys", "state": state}]})
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


def _make_partial_workspace(project_dir, name):
    """A consistent workspace whose ledger mixes Success/Unstart (partial)."""
    _make_workspace(project_dir, name)
    (project_dir / name / "home" / "flow.json").write_text(
        json.dumps(
            {
                "steps": [
                    {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                    {"name": "Floorplan", "tool": "ecc", "state": "Unstart"},
                ]
            }
        )
    )


def _run_doctor(project_dir, *extra):
    return cli_main.run(["project", "doctor", "--project", str(project_dir), "--plain", *extra])


def _manifest(project_dir):
    return json.loads((project_dir / "project.json").read_text())


class TestProjectDoctorReport:
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

    def test_derived_field_mismatch_is_reported_without_writes(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        entry = {
            **manifest_stubs.entry(project_dir, "ws_0001", status="failed"),
            "start_step": "Place",
            "parameter_patch": {"frequency_max": {"from": 100, "to": 125}},
        }
        manifest_stubs.write(project_dir, [entry])
        before = (project_dir / "project.json").read_bytes()

        rc = _run_doctor(project_dir)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert records[0] == {
            "doctor": "project",
            "status": "failed",
            "checked": "1",
            "inconsistent": "1",
        }
        finding = records[1]
        assert finding["check"] == "derived-field-mismatch"
        assert finding["status"] == "fail"
        assert finding["workspace_id"] == "ws_0001"
        assert finding["workspace"] == str(project_dir / "ws_0001")
        for field in ("start_step", "status", "parameter_patch"):
            assert field in finding["detail"]
        assert finding["remediation"] == f"ecc project doctor --fix --project {project_dir}"
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
        assert records[1]["check"] == "derived-field-mismatch"
        assert "workspace facts unreadable" in records[1]["detail"]

    def test_archived_entry_skips_derived_fields_but_not_existence(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        archived = {
            **manifest_stubs.entry(project_dir, "ws_0001", status="archived"),
            "start_step": "Place",
        }
        missing_archived = manifest_stubs.entry(project_dir, "ghost", status="archived")
        manifest_stubs.write(project_dir, [archived, missing_archived])

        rc = _run_doctor(project_dir)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert [r["check"] for r in records[1:]] == ["missing-directory"]
        assert records[1]["workspace_id"] == "ghost"

    def test_running_entry_skips_derived_fields_but_not_existence(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        running = {
            **manifest_stubs.entry(project_dir, "ws_0001", status="running"),
            "start_step": "Place",
            "parameter_patch": {"frequency_max": {"from": 100, "to": 125}},
        }
        missing_running = manifest_stubs.entry(project_dir, "ghost", status="running")
        manifest_stubs.write(project_dir, [running, missing_running])

        rc = _run_doctor(project_dir)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert [r["check"] for r in records[1:]] == ["missing-directory"]
        assert records[1]["workspace_id"] == "ghost"

    def test_failed_entry_with_ongoing_ledger_is_consistent(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        # A fatal completion-commit failure rolls steps back to Ongoing while
        # the terminal write-back records failed: not an inconsistency.
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001", state="Ongoing")
        manifest_stubs.write(
            project_dir, [manifest_stubs.entry(project_dir, "ws_0001", status="failed")]
        )

        rc = _run_doctor(project_dir)

        assert rc == 0
        assert plain_records(capsys.readouterr().out)[0]["status"] == "ok"

    def test_success_entry_with_partial_ledger_is_consistent(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        # A deliberate single-step/bounded run leaves a partial ledger next
        # to a success entry: not an inconsistency.
        project_dir = tmp_path / "gcd"
        _make_partial_workspace(project_dir, "ws_0001")
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = _run_doctor(project_dir)

        assert rc == 0
        assert plain_records(capsys.readouterr().out)[0]["status"] == "ok"

    def test_success_entry_with_failed_ledger_is_flagged(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001", state="Incomplete")
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = _run_doctor(project_dir)

        records = plain_records(capsys.readouterr().out)
        assert rc == 1
        assert records[1]["check"] == "derived-field-mismatch"
        assert "status" in records[1]["detail"]

    def test_project_without_manifest_is_an_error(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()

        rc = _run_doctor(project_dir)

        assert rc == 1
        assert plain_records(capsys.readouterr().out)[0]["error"] == "missing_manifest"


class TestProjectDoctorFix:
    def test_fix_rebuilds_derived_fields_from_directory_facts(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        entry = {
            **manifest_stubs.entry(project_dir, "ws_0001", status="failed"),
            "start_step": "Place",
            "parameter_patch": {"frequency_max": {"from": 100, "to": 125}},
            "source_workspace_id": "ws_0000",
        }
        manifest_stubs.write(project_dir, [entry])

        rc = _run_doctor(project_dir, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert records[0] == {
            "doctor": "project",
            "status": "fixed",
            "checked": "1",
            "inconsistent": "1",
            "fixed": "1",
        }
        assert records[1]["check"] == "derived-field-mismatch"
        assert records[1]["fix"] == "rebuilt"
        (repaired,) = _manifest(project_dir)["workspaces"]
        assert repaired["start_step"] == "Synth"
        assert repaired["end_step"] == "Harden"
        assert repaired["status"] == "success"
        assert repaired["parameter_patch"] == {}
        # Lineage is never rewritten by a derived-field repair.
        assert repaired["source_workspace_id"] == "ws_0000"

        capsys.readouterr()
        assert _run_doctor(project_dir) == 0
        assert plain_records(capsys.readouterr().out)[0]["status"] == "ok"

    def test_fix_maps_partial_ledger_to_in_progress(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        _make_partial_workspace(project_dir, "ws_0001")
        manifest_stubs.write(
            project_dir, [manifest_stubs.entry(project_dir, "ws_0001", status="not_started")]
        )

        rc = _run_doctor(project_dir, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert records[1]["check"] == "derived-field-mismatch"
        assert "status" in records[1]["detail"]
        assert records[1]["fix"] == "rebuilt"
        (repaired,) = _manifest(project_dir)["workspaces"]
        assert repaired["status"] == "in_progress"

        capsys.readouterr()
        assert _run_doctor(project_dir) == 0

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
        assert entry["start_step"] == "Synth"
        assert entry["end_step"] == "Harden"
        assert entry["status"] == "success"
        assert entry["parameter_patch"] == {}

        capsys.readouterr()
        assert _run_doctor(project_dir) == 0
        assert plain_records(capsys.readouterr().out)[0]["status"] == "ok"

    def test_fix_removes_uninspectable_directory_entry(
        self, tmp_path, capsys, manifest_stubs, plain_records
    ):
        project_dir = tmp_path / "gcd"
        (project_dir / "ws_0001").mkdir(parents=True)
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = _run_doctor(project_dir, "--fix")

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert records[1]["fix"] == "removed"
        assert _manifest(project_dir)["workspaces"] == []

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
